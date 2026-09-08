package engine

import (
	"errors"
	"fmt"
	"io"
	"log/slog"
	"os"
	"time"
)

var (
	// ErrBackupExists guards against a backup command silently clobbering
	// an existing file at the destination.
	ErrBackupExists = errors.New("minikv: backup destination already exists")
	// ErrInvalidBackup is returned by Restore when the source file does
	// not look like a MiniKV log at all (empty, or its very first record
	// fails validation).
	ErrInvalidBackup = errors.New("minikv: backup file failed validation")
)

// Backup writes a point-in-time copy of the database's log file to dest.
// It takes a read lock for the duration of the copy, so concurrent Get
// calls proceed normally but writers block until the backup completes.
// Because the log is append-only, everything up to the size observed at
// lock-acquisition time is a fully self-consistent snapshot: nothing in
// that byte range will ever be mutated in place.
//
// Backup refuses to overwrite an existing file at dest.
func (db *Database) Backup(dest string) error {
	if _, err := os.Stat(dest); err == nil {
		return ErrBackupExists
	} else if !errors.Is(err, os.ErrNotExist) {
		return err
	}

	db.mu.RLock()
	defer db.mu.RUnlock()
	if db.closed {
		return ErrClosed
	}

	out, err := os.OpenFile(dest, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600)
	if err != nil {
		return err
	}
	defer out.Close()

	section := io.NewSectionReader(db.store.file, 0, db.store.size)
	if _, err := io.Copy(out, section); err != nil {
		return err
	}
	return out.Sync()
}

// ValidateBackup performs a structural check of a backup file (or any
// MiniKV log file) without mutating anything: it must exist, be
// non-empty, and its records must replay cleanly from the very first
// byte. It returns the RecoveryReport describing what it found.
func ValidateBackup(path string) (RecoveryReport, error) {
	info, err := os.Stat(path)
	if err != nil {
		return RecoveryReport{}, err
	}
	if info.Size() == 0 {
		return RecoveryReport{}, fmt.Errorf("%w: file is empty", ErrInvalidBackup)
	}

	f, err := os.Open(path)
	if err != nil {
		return RecoveryReport{}, err
	}
	defer f.Close()

	_, validSize, report, err := recoverIndex(f, slog.New(slog.NewTextHandler(io.Discard, nil)))
	if err != nil {
		return RecoveryReport{}, err
	}
	if report.RecordsReplayed == 0 {
		return report, fmt.Errorf("%w: no valid records found", ErrInvalidBackup)
	}
	if validSize == 0 {
		return report, fmt.Errorf("%w: first record is corrupt", ErrInvalidBackup)
	}
	return report, nil
}

// Restore replaces the database file at targetPath with the contents of
// backupPath. The backup is validated first (see ValidateBackup). If a
// file already exists at targetPath, it is preserved alongside the
// restored one (renamed with a timestamped ".preRestore" suffix) rather
// than being silently discarded, so a bad restore is always recoverable.
//
// Restore operates on a closed database: callers must Close() any open
// Database at targetPath before calling this, and Open() a fresh one
// afterwards.
func Restore(backupPath, targetPath string) error {
	if _, err := ValidateBackup(backupPath); err != nil {
		return err
	}

	if _, err := os.Stat(targetPath); err == nil {
		preserved := fmt.Sprintf("%s.preRestore.%d", targetPath, time.Now().Unix())
		if err := os.Rename(targetPath, preserved); err != nil {
			return fmt.Errorf("minikv: could not preserve existing database before restore: %w", err)
		}
	} else if !errors.Is(err, os.ErrNotExist) {
		return err
	}

	src, err := os.Open(backupPath)
	if err != nil {
		return err
	}
	defer src.Close()

	dst, err := os.OpenFile(targetPath, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600)
	if err != nil {
		return err
	}
	defer dst.Close()

	if _, err := io.Copy(dst, src); err != nil {
		return err
	}
	return dst.Sync()
}
