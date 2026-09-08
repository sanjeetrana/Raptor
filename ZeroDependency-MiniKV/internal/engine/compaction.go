package engine

import (
	"fmt"
	"os"
	"time"
)

// CompactResult reports what a compaction pass did, for the CLI and any
// dashboard to display.
type CompactResult struct {
	LiveKeysKept     int
	BytesBefore      int64
	BytesAfter       int64
	TombstonesPruned int
}

// Compact rewrites the log file so that it contains exactly one SET
// record per live (non-expired) key and nothing else: no tombstones, no
// superseded old versions of updated keys. It holds the database's write
// lock for its full duration, so it is safe but not concurrent with other
// operations — by design, since it is rewriting the very file everything
// else reads from.
//
// The rewrite happens in a temporary file which is fsynced and then
// atomically renamed over the original (os.Rename on the same filesystem
// is atomic on Linux, macOS and Windows), so a crash mid-compaction
// leaves the original, uncompacted log untouched and fully recoverable.
func (db *Database) Compact() (CompactResult, error) {
	db.mu.Lock()
	defer db.mu.Unlock()

	if db.closed {
		return CompactResult{}, ErrClosed
	}

	tmpPath := fmt.Sprintf("%s.compact.tmp", db.path)
	os.Remove(tmpPath) // best-effort cleanup of any stale temp file

	tmp, err := os.OpenFile(tmpPath, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600)
	if err != nil {
		return CompactResult{}, err
	}

	now := time.Now()
	newIdx := make(index, len(db.idx))
	var offset int64
	kept := 0

	for key, entry := range db.idx {
		if isExpired(entry.expiresAt, now) {
			continue
		}
		value, rerr := db.store.readAt(entry.valueOffset(), int(entry.valueLen))
		if rerr != nil {
			tmp.Close()
			os.Remove(tmpPath)
			return CompactResult{}, rerr
		}
		rec := &record{Op: opSet, Key: []byte(key), Value: value, ExpiresAt: entry.expiresAt}
		buf := rec.encode()
		if _, werr := tmp.Write(buf); werr != nil {
			tmp.Close()
			os.Remove(tmpPath)
			return CompactResult{}, werr
		}
		newIdx[key] = indexEntry{
			offset:    offset,
			keyLen:    uint32(len(key)),
			valueLen:  entry.valueLen,
			expiresAt: entry.expiresAt,
		}
		offset += int64(len(buf))
		kept++
	}

	if err := tmp.Sync(); err != nil {
		tmp.Close()
		os.Remove(tmpPath)
		return CompactResult{}, err
	}
	if err := tmp.Close(); err != nil {
		os.Remove(tmpPath)
		return CompactResult{}, err
	}

	before := db.store.size
	tombstonesPruned := db.report.TombstonesSeen

	if err := db.store.close(); err != nil {
		os.Remove(tmpPath)
		return CompactResult{}, err
	}
	if err := os.Rename(tmpPath, db.path); err != nil {
		return CompactResult{}, err
	}

	newStore, err := openStorage(db.path)
	if err != nil {
		return CompactResult{}, err
	}

	db.store = newStore
	db.idx = newIdx
	db.report.RecordsReplayed = kept
	db.report.TombstonesSeen = 0
	db.report.TruncatedBytes = 0
	db.report.CorruptionFound = false

	return CompactResult{
		LiveKeysKept:     kept,
		BytesBefore:      before,
		BytesAfter:       offset,
		TombstonesPruned: tombstonesPruned,
	}, nil
}
