package engine

import (
	"errors"
	"io"
	"log/slog"
	"sort"
	"sync"
	"time"
)

// ---------------------------------------------------------------------------
// Durability semantics (read this before trusting any write)
//
// MiniKV appends every mutation to its log file via os.File.WriteAt. By
// default (SyncMode = false) that write reaches the OS page cache but is
// NOT forced to disk: a process crash after a successful Set() call is
// safe (the OS still holds the data and a clean process restart, or even
// an OS-level restart with a clean shutdown, will not lose it), but a
// power loss or kernel panic before the page cache is flushed CAN lose
// recently written records.
//
// With SyncMode = true, every write is followed by File.Sync() (fsync),
// which blocks until the data is durable on the underlying storage medium
// before Set()/Delete() returns. This is slower but survives power loss,
// subject to the disk/controller itself honoring fsync (which, on most
// consumer SSDs and virtualized disks, it does).
//
// There is no group-commit / batched fsync in this implementation: each
// synchronous write pays its own fsync cost. That is a deliberate
// simplicity trade-off, documented in README.md, not an oversight.
// ---------------------------------------------------------------------------

var (
	// ErrNotFound is returned by Get/Delete when the key does not exist
	// (or has expired).
	ErrNotFound = errors.New("minikv: key not found")
	// ErrEmptyKey is returned when an operation is attempted with an
	// empty key.
	ErrEmptyKey = errors.New("minikv: key must not be empty")
	// ErrClosed is returned when an operation is attempted on a Database
	// that has already been closed.
	ErrClosed = errors.New("minikv: database is closed")
)

// Options configures a Database on Open.
type Options struct {
	// Sync enables fsync-after-every-write durability mode. See the
	// package-level durability comment above for exact semantics.
	Sync bool
	// Logger receives structured diagnostic events (recovery findings,
	// compaction results, etc). If nil, a no-op logger is used.
	Logger *slog.Logger
}

// Database is a single embedded MiniKV store backed by one append-only
// log file plus an in-memory index. It is safe for concurrent use by
// multiple goroutines.
type Database struct {
	mu     sync.RWMutex
	path   string
	store  *storage
	idx    index
	opts   Options
	closed bool
	report RecoveryReport
}

// Open opens (creating if necessary) the MiniKV database at path,
// replaying its log and rebuilding the in-memory index as described in
// docs/ARCHITECTURE.md.
func Open(path string, opts Options) (*Database, error) {
	if opts.Logger == nil {
		opts.Logger = slog.New(slog.NewTextHandler(io.Discard, nil))
	}

	st, err := openStorage(path)
	if err != nil {
		return nil, err
	}

	idx, validSize, report, err := recoverIndex(st.file, opts.Logger)
	if err != nil {
		st.close()
		return nil, err
	}
	if validSize < st.size {
		opts.Logger.Warn("minikv: discarding trailing incomplete/corrupt data",
			"discarded_bytes", st.size-validSize)
		if err := st.truncateTrailingGarbage(validSize); err != nil {
			st.close()
			return nil, err
		}
	}

	db := &Database{
		path:   path,
		store:  st,
		idx:    idx,
		opts:   opts,
		report: report,
	}
	return db, nil
}

// Close flushes and closes the underlying log file. It is safe to call
// Close more than once.
func (db *Database) Close() error {
	db.mu.Lock()
	defer db.mu.Unlock()
	if db.closed {
		return nil
	}
	db.closed = true
	if err := db.store.sync(); err != nil {
		// Still attempt to close even if the final sync failed.
		db.store.close()
		return err
	}
	return db.store.close()
}

// Set writes key=value, optionally expiring after ttl (0 = never).
func (db *Database) Set(key, value []byte, ttl time.Duration) error {
	if len(key) == 0 {
		return ErrEmptyKey
	}
	rec := &record{
		Op:        opSet,
		Key:       key,
		Value:     value,
		ExpiresAt: expiresAtFromTTL(ttl),
	}
	buf := rec.encode()

	db.mu.Lock()
	defer db.mu.Unlock()
	if db.closed {
		return ErrClosed
	}
	offset, err := db.store.appendRecord(buf, db.opts.Sync)
	if err != nil {
		return err
	}
	db.idx[string(key)] = indexEntry{
		offset:    offset,
		keyLen:    uint32(len(key)),
		valueLen:  uint32(len(value)),
		expiresAt: rec.ExpiresAt,
	}
	return nil
}

// Get retrieves the current value for key. It returns ErrNotFound if the
// key does not exist or has expired.
func (db *Database) Get(key []byte) ([]byte, error) {
	if len(key) == 0 {
		return nil, ErrEmptyKey
	}

	db.mu.RLock()
	defer db.mu.RUnlock()
	if db.closed {
		return nil, ErrClosed
	}

	entry, ok := db.idx[string(key)]
	if !ok {
		return nil, ErrNotFound
	}
	if isExpired(entry.expiresAt, time.Now()) {
		return nil, ErrNotFound
	}

	value, err := db.store.readAt(entry.valueOffset(), int(entry.valueLen))
	if err != nil {
		return nil, err
	}
	return value, nil
}

// Exists reports whether key currently has a live (non-expired) value,
// without paying the cost of reading and copying it.
func (db *Database) Exists(key []byte) (bool, error) {
	if len(key) == 0 {
		return false, ErrEmptyKey
	}
	db.mu.RLock()
	defer db.mu.RUnlock()
	if db.closed {
		return false, ErrClosed
	}
	entry, ok := db.idx[string(key)]
	if !ok {
		return false, nil
	}
	if isExpired(entry.expiresAt, time.Now()) {
		return false, nil
	}
	return true, nil
}

// Delete removes key. It returns ErrNotFound if the key does not
// currently exist (or has already expired).
func (db *Database) Delete(key []byte) error {
	if len(key) == 0 {
		return ErrEmptyKey
	}

	db.mu.Lock()
	defer db.mu.Unlock()
	if db.closed {
		return ErrClosed
	}

	entry, ok := db.idx[string(key)]
	if !ok || isExpired(entry.expiresAt, time.Now()) {
		return ErrNotFound
	}

	rec := &record{Op: opDelete, Key: key}
	buf := rec.encode()
	if _, err := db.store.appendRecord(buf, db.opts.Sync); err != nil {
		return err
	}
	delete(db.idx, string(key))
	return nil
}

// List returns every currently live (non-expired) key, sorted for stable
// output. It does not touch disk beyond what recovery already loaded.
func (db *Database) List() []string {
	db.mu.RLock()
	defer db.mu.RUnlock()

	now := time.Now()
	keys := make([]string, 0, len(db.idx))
	for k, e := range db.idx {
		if isExpired(e.expiresAt, now) {
			continue
		}
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}

// Stats describes the current state of the database, for the CLI "stats"
// command and the optional dashboard.
type Stats struct {
	Path            string
	LiveKeys        int
	ExpiredKeys     int
	LogSizeBytes    int64
	SyncMode        bool
	RecordsReplayed int
	TombstonesSeen  int
	TruncatedBytes  int64
	CorruptionFound bool
}

func (db *Database) Stats() Stats {
	db.mu.RLock()
	defer db.mu.RUnlock()

	now := time.Now()
	live, expired := 0, 0
	for _, e := range db.idx {
		if isExpired(e.expiresAt, now) {
			expired++
		} else {
			live++
		}
	}

	return Stats{
		Path:            db.path,
		LiveKeys:        live,
		ExpiredKeys:     expired,
		LogSizeBytes:    db.store.size,
		SyncMode:        db.opts.Sync,
		RecordsReplayed: db.report.RecordsReplayed,
		TombstonesSeen:  db.report.TombstonesSeen,
		TruncatedBytes:  db.report.TruncatedBytes,
		CorruptionFound: db.report.CorruptionFound,
	}
}
