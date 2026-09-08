package state

import (
	json "encoding/json/v2"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"time"
	"uuid"

	"github.com/daniel-oluwadunsin/undolang/internal/journal"
)

type Status string

const (
	Planned          Status = "PLANNED"
	Prepared         Status = "PREPARED"
	Running          Status = "RUNNING"
	Verifying        Status = "VERIFYING"
	Committing       Status = "COMMITTING"
	Committed        Status = "COMMITTED"
	RollingBack      Status = "ROLLING_BACK"
	RolledBack       Status = "ROLLED_BACK"
	RecoveryRequired Status = "RECOVERY_REQUIRED"
	RecoveryFailed   Status = "RECOVERY_FAILED"
)

var transitions = map[Status]map[Status]bool{
	Planned: {Prepared: true, RollingBack: true, RecoveryRequired: true}, Prepared: {Running: true, RollingBack: true, RecoveryRequired: true}, Running: {Verifying: true, RollingBack: true, RecoveryRequired: true}, Verifying: {Committing: true, RollingBack: true, RecoveryRequired: true}, Committing: {Committed: true, RollingBack: true, RecoveryRequired: true}, RollingBack: {RolledBack: true, RecoveryFailed: true}, RecoveryRequired: {RollingBack: true, RecoveryFailed: true}, RecoveryFailed: {RollingBack: true},
}

func ValidateTransition(from, to Status) error {
	if transitions[from][to] {
		return nil
	}
	return fmt.Errorf("invalid transaction state transition %s -> %s", from, to)
}
func Terminal(s Status) bool { return s == Committed || s == RolledBack }

type Metadata struct {
	ID            string    `json:"id"`
	Name          string    `json:"name"`
	ScriptPath    string    `json:"script_path"`
	ScriptSHA256  string    `json:"script_sha256"`
	Root          string    `json:"root"`
	AllowedRoots  []string  `json:"allowed_roots,omitempty"`
	StartedAt     time.Time `json:"started_at"`
	Status        Status    `json:"status"`
	BackupCleaned bool      `json:"backup_cleaned"`
}
type Lock struct {
	TransactionID string    `json:"transaction_id"`
	PID           int       `json:"pid"`
	StartedAt     time.Time `json:"started_at"`
	ScriptSHA256  string    `json:"script_sha256"`
}
type Store struct{ root, stateDir, transactionsDir string }

type BeginOptions struct {
	Name, ScriptPath, ScriptHash string
	AllowedRoots                 []string
}

func Open(root string) (*Store, error) {
	absolute, err := filepath.Abs(root)
	if err != nil {
		return nil, err
	}
	absolute, err = filepath.EvalSymlinks(absolute)
	if err != nil {
		return nil, err
	}
	info, err := os.Stat(absolute)
	if err != nil {
		return nil, err
	}
	if !info.IsDir() {
		return nil, errors.New("transaction root is not a directory")
	}
	return &Store{root: absolute, stateDir: filepath.Join(absolute, ".undo"), transactionsDir: filepath.Join(absolute, ".undo", "transactions")}, nil
}
func (s *Store) Ensure() error {
	for _, dir := range []string{s.stateDir, s.transactionsDir, filepath.Join(s.stateDir, "history")} {
		if err := os.MkdirAll(dir, 0o700); err != nil {
			return err
		}
		info, err := os.Lstat(dir)
		if err != nil {
			return err
		}
		if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
			return fmt.Errorf("state path is not a real directory: %s", dir)
		}
		if err := os.Chmod(dir, 0o700); err != nil {
			return err
		}
	}
	return syncDir(s.root)
}

type Transaction struct {
	Meta                        Metadata
	Dir, BackupDir, JournalPath string
	Journal                     *journal.Appender
	store                       *Store
}

func (s *Store) Begin(name, scriptPath, scriptHash string) (*Transaction, error) {
	return s.BeginWithOptions(BeginOptions{Name: name, ScriptPath: scriptPath, ScriptHash: scriptHash})
}

func (s *Store) BeginWithOptions(options BeginOptions) (_ *Transaction, retErr error) {
	if err := s.Ensure(); err != nil {
		return nil, err
	}
	id := uuid.NewV7().String()
	now := time.Now().UTC()
	meta := Metadata{ID: id, Name: options.Name, ScriptPath: options.ScriptPath, ScriptSHA256: options.ScriptHash, Root: s.root, AllowedRoots: append([]string(nil), options.AllowedRoots...), StartedAt: now, Status: Planned}
	lockPath := filepath.Join(s.stateDir, "active.lock")
	lockFile, err := os.OpenFile(lockPath, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600)
	if err != nil {
		return nil, err
	}
	cleanup := true
	var transactionDir string
	defer func() {
		if cleanup {
			if transactionDir != "" {
				_ = os.RemoveAll(transactionDir)
			}
			_ = os.Remove(lockPath)
			_ = syncDir(s.stateDir)
		}
	}()
	lock := Lock{TransactionID: id, PID: os.Getpid(), StartedAt: now, ScriptSHA256: options.ScriptHash}
	data, err := json.Marshal(&lock)
	if err == nil {
		err = writeAndSync(lockFile, data)
	}
	closeErr := lockFile.Close()
	if err == nil {
		err = closeErr
	}
	if err != nil {
		return nil, err
	}
	if err = syncDir(s.stateDir); err != nil {
		return nil, err
	}
	dir := filepath.Join(s.transactionsDir, id)
	transactionDir = dir
	backup := filepath.Join(dir, "backup")
	if err = os.MkdirAll(backup, 0o700); err != nil {
		return nil, err
	}
	if err = writeAtomic(filepath.Join(dir, "meta.json"), meta); err != nil {
		return nil, err
	}
	if err = writeAtomic(filepath.Join(dir, "status"), []byte(meta.Status)); err != nil {
		return nil, err
	}
	journalPath := filepath.Join(dir, "journal.bin")
	appender, err := journal.Create(journalPath)
	if err != nil {
		return nil, err
	}
	if _, err = appender.Append(journal.TXBegin, journal.Payload{TransactionID: id, State: string(Planned)}); err != nil {
		appender.Close()
		return nil, err
	}
	cleanup = false
	return &Transaction{Meta: meta, Dir: dir, BackupDir: backup, JournalPath: journalPath, Journal: appender, store: s}, nil
}

func (t *Transaction) Transition(to Status) error {
	if err := ValidateTransition(t.Meta.Status, to); err != nil {
		return err
	}
	if _, err := t.Journal.Append(journal.TXState, journal.Payload{TransactionID: t.Meta.ID, State: string(to)}); err != nil {
		return err
	}
	t.Meta.Status = to
	if err := writeAtomic(filepath.Join(t.Dir, "status"), []byte(to)); err != nil {
		return err
	}
	return writeAtomic(filepath.Join(t.Dir, "meta.json"), t.Meta)
}
func (t *Transaction) Close() error {
	if t.Journal == nil {
		return nil
	}
	err := t.Journal.Close()
	t.Journal = nil
	return err
}
func (t *Transaction) Release() error {
	if !Terminal(t.Meta.Status) {
		return errors.New("cannot release active lock before terminal status")
	}
	if err := t.Close(); err != nil {
		return err
	}
	lock, err := t.store.Active()
	if errors.Is(err, os.ErrNotExist) {
		return syncDir(t.store.stateDir)
	}
	if err != nil {
		return err
	}
	if lock.TransactionID != t.Meta.ID {
		return errors.New("active lock transaction id mismatch")
	}
	if err := os.Remove(filepath.Join(t.store.stateDir, "active.lock")); err != nil {
		return err
	}
	return syncDir(t.store.stateDir)
}

func (s *Store) Inspect(id string) (Metadata, error) {
	var meta Metadata
	parsed, err := uuid.Parse(id)
	if err != nil || parsed.String() != id {
		return meta, fmt.Errorf("invalid transaction id")
	}
	data, err := readLimited(filepath.Join(s.transactionsDir, id, "meta.json"), 1<<20)
	if err != nil {
		return meta, err
	}
	if err = json.Unmarshal(data, &meta); err != nil {
		return meta, err
	}
	if meta.ID != id {
		return Metadata{}, fmt.Errorf("transaction metadata id mismatch")
	}
	return meta, nil
}

func (s *Store) Active() (Lock, error) {
	var lock Lock
	data, err := readLimited(filepath.Join(s.stateDir, "active.lock"), 64<<10)
	if err != nil {
		return lock, err
	}
	if err = json.Unmarshal(data, &lock); err != nil {
		return Lock{}, err
	}
	parsed, err := uuid.Parse(lock.TransactionID)
	if err != nil || parsed.String() != lock.TransactionID {
		return Lock{}, errors.New("invalid transaction id in active lock")
	}
	return lock, nil
}

func (s *Store) OpenTransaction(id string, recoverTail bool) (*Transaction, journal.Replay, error) {
	meta, err := s.Inspect(id)
	if err != nil {
		return nil, journal.Replay{}, err
	}
	dir := filepath.Join(s.transactionsDir, id)
	journalPath := filepath.Join(dir, "journal.bin")
	var appender *journal.Appender
	var replay journal.Replay
	if recoverTail {
		appender, replay, err = journal.OpenAppendRecovery(journalPath)
	} else {
		appender, err = journal.OpenAppend(journalPath)
		if err == nil {
			file, openErr := os.Open(journalPath)
			if openErr == nil {
				replay, openErr = journal.Decode(file)
				_ = file.Close()
			}
			err = openErr
		}
	}
	if err != nil {
		return nil, replay, err
	}
	if replay.TransactionID != id {
		appender.Close()
		return nil, replay, errors.New("journal transaction id mismatch")
	}
	return &Transaction{Meta: meta, Dir: dir, BackupDir: filepath.Join(dir, "backup"), JournalPath: journalPath, Journal: appender, store: s}, replay, nil
}

func (t *Transaction) ReconcileStatus(status Status) error {
	t.Meta.Status = status
	if err := writeAtomic(filepath.Join(t.Dir, "status"), []byte(status)); err != nil {
		return err
	}
	return writeAtomic(filepath.Join(t.Dir, "meta.json"), t.Meta)
}

func (t *Transaction) CleanupBackups() error {
	if err := os.RemoveAll(t.BackupDir); err != nil {
		return err
	}
	if err := syncDir(t.Dir); err != nil {
		return err
	}
	t.Meta.BackupCleaned = true
	return writeAtomic(filepath.Join(t.Dir, "meta.json"), t.Meta)
}

func (s *Store) Root() string { return s.root }

func readLimited(path string, limit int64) ([]byte, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil {
		return nil, err
	}
	if info.Size() > limit {
		return nil, errors.New("state file exceeds size limit")
	}
	data := make([]byte, info.Size())
	_, err = file.ReadAt(data, 0)
	if errors.Is(err, os.ErrClosed) {
		return nil, err
	}
	if err != nil && len(data) > 0 {
		// ReadAt returns io.EOF only when fewer bytes were read; a stable regular
		// file of the statted size should fill the buffer.
		return nil, err
	}
	return data, nil
}
func (s *Store) History() ([]Metadata, error) {
	entries, err := os.ReadDir(s.transactionsDir)
	if errors.Is(err, os.ErrNotExist) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	var out []Metadata
	for _, entry := range entries {
		if !entry.IsDir() {
			continue
		}
		meta, err := s.Inspect(entry.Name())
		if err != nil {
			return nil, err
		}
		out = append(out, meta)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].StartedAt.Before(out[j].StartedAt) })
	return out, nil
}

func (s *Store) Unresolved() ([]Metadata, error) {
	history, err := s.History()
	if err != nil {
		return nil, err
	}
	result := history[:0]
	for _, meta := range history {
		if !Terminal(meta.Status) {
			result = append(result, meta)
		}
	}
	return result, nil
}

func writeAtomic(path string, value any) error {
	var data []byte
	var err error
	switch v := value.(type) {
	case []byte:
		data = v
	default:
		data, err = json.Marshal(&v)
		if err != nil {
			return err
		}
	}
	dir := filepath.Dir(path)
	temp, err := os.CreateTemp(dir, ".undo-state-")
	if err != nil {
		return err
	}
	name := temp.Name()
	defer os.Remove(name)
	if err = temp.Chmod(0o600); err == nil {
		err = writeAndSync(temp, data)
	}
	closeErr := temp.Close()
	if err == nil {
		err = closeErr
	}
	if err != nil {
		return err
	}
	if err = os.Rename(name, path); err != nil {
		return err
	}
	return syncDir(dir)
}
func writeAndSync(file *os.File, data []byte) error {
	for len(data) > 0 {
		n, err := file.Write(data)
		if err != nil {
			return err
		}
		if n == 0 {
			return errors.New("short write")
		}
		data = data[n:]
	}
	return file.Sync()
}
func syncDir(path string) error {
	dir, err := os.Open(path)
	if err != nil {
		return err
	}
	defer dir.Close()
	return dir.Sync()
}
