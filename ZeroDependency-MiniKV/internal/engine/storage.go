package engine

import (
	"io"
	"os"
)

// storage wraps the single append-only log file that backs a Database.
// All reads use ReadAt (pread) so they never disturb the file's write
// offset, and all writes go through appendAt, which is only ever called
// while the Database holds its write lock.
type storage struct {
	file *os.File
	// size tracks the logical end of valid data in the file. It is the
	// single source of truth for "where does the next record go" and is
	// always mutated under Database.mu.
	size int64
}

func openStorage(path string) (*storage, error) {
	f, err := os.OpenFile(path, os.O_CREATE|os.O_RDWR, 0o600)
	if err != nil {
		return nil, err
	}
	info, err := f.Stat()
	if err != nil {
		f.Close()
		return nil, err
	}
	return &storage{file: f, size: info.Size()}, nil
}

// readAt reads exactly n bytes starting at offset.
func (s *storage) readAt(offset int64, n int) ([]byte, error) {
	buf := make([]byte, n)
	_, err := s.file.ReadAt(buf, offset)
	if err != nil {
		return nil, err
	}
	return buf, nil
}

// appendRecord writes buf at the current logical end of the file and
// advances size. It must be called with the Database write lock held.
func (s *storage) appendRecord(buf []byte, sync bool) (offset int64, err error) {
	offset = s.size
	n, err := s.file.WriteAt(buf, offset)
	if err != nil {
		return 0, err
	}
	if n != len(buf) {
		return 0, io.ErrShortWrite
	}
	if sync {
		if err := s.file.Sync(); err != nil {
			return 0, err
		}
	}
	s.size += int64(n)
	return offset, nil
}

// truncateTrailingGarbage cuts the file back to validSize, discarding any
// bytes after the last known-good record. It is only invoked during
// recovery, and only when validSize < current file size.
func (s *storage) truncateTrailingGarbage(validSize int64) error {
	if err := s.file.Truncate(validSize); err != nil {
		return err
	}
	s.size = validSize
	return nil
}

func (s *storage) sync() error {
	return s.file.Sync()
}

func (s *storage) close() error {
	return s.file.Close()
}
