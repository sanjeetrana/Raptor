package engine

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

func tempDBPath(t *testing.T) string {
	t.Helper()
	return filepath.Join(t.TempDir(), "minikv.db")
}

func openTestDB(t *testing.T, opts Options) *Database {
	t.Helper()
	db, err := Open(tempDBPath(t), opts)
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	t.Cleanup(func() { db.Close() })
	return db
}

// ---------------------------------------------------------------------------
// Core CRUD
// ---------------------------------------------------------------------------

func TestSetGet(t *testing.T) {
	db := openTestDB(t, Options{})
	if err := db.Set([]byte("name"), []byte("Shraddha"), 0); err != nil {
		t.Fatalf("Set: %v", err)
	}
	v, err := db.Get([]byte("name"))
	if err != nil {
		t.Fatalf("Get: %v", err)
	}
	if string(v) != "Shraddha" {
		t.Fatalf("got %q, want %q", v, "Shraddha")
	}
}

func TestGetMissing(t *testing.T) {
	db := openTestDB(t, Options{})
	if _, err := db.Get([]byte("missing")); err != ErrNotFound {
		t.Fatalf("got %v, want ErrNotFound", err)
	}
}

func TestDelete(t *testing.T) {
	db := openTestDB(t, Options{})
	mustSet(t, db, "k", "v")
	if err := db.Delete([]byte("k")); err != nil {
		t.Fatalf("Delete: %v", err)
	}
	if _, err := db.Get([]byte("k")); err != ErrNotFound {
		t.Fatalf("got %v after delete, want ErrNotFound", err)
	}
	if err := db.Delete([]byte("k")); err != ErrNotFound {
		t.Fatalf("second delete: got %v, want ErrNotFound", err)
	}
}

func TestExists(t *testing.T) {
	db := openTestDB(t, Options{})
	mustSet(t, db, "k", "v")
	ok, err := db.Exists([]byte("k"))
	if err != nil || !ok {
		t.Fatalf("Exists: got (%v, %v), want (true, nil)", ok, err)
	}
	ok, err = db.Exists([]byte("nope"))
	if err != nil || ok {
		t.Fatalf("Exists: got (%v, %v), want (false, nil)", ok, err)
	}
}

func TestList(t *testing.T) {
	db := openTestDB(t, Options{})
	mustSet(t, db, "b", "2")
	mustSet(t, db, "a", "1")
	mustSet(t, db, "c", "3")
	got := db.List()
	want := []string{"a", "b", "c"}
	if len(got) != len(want) {
		t.Fatalf("got %v, want %v", got, want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("got %v, want %v", got, want)
		}
	}
}

// ---------------------------------------------------------------------------
// Persistence: close, reopen, verify
// ---------------------------------------------------------------------------

func TestPersistenceAcrossReopen(t *testing.T) {
	path := tempDBPath(t)
	db, err := Open(path, Options{})
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	mustSet(t, db, "name", "Shraddha")
	mustSet(t, db, "city", "Pune")
	if err := db.Close(); err != nil {
		t.Fatalf("Close: %v", err)
	}

	db2, err := Open(path, Options{})
	if err != nil {
		t.Fatalf("reopen: %v", err)
	}
	defer db2.Close()

	v, err := db2.Get([]byte("name"))
	if err != nil || string(v) != "Shraddha" {
		t.Fatalf("got (%q, %v), want (Shraddha, nil)", v, err)
	}
	v, err = db2.Get([]byte("city"))
	if err != nil || string(v) != "Pune" {
		t.Fatalf("got (%q, %v), want (Pune, nil)", v, err)
	}
}

// ---------------------------------------------------------------------------
// Updates
// ---------------------------------------------------------------------------

func TestRepeatedUpdatesToSameKey(t *testing.T) {
	db := openTestDB(t, Options{})
	for i := 0; i < 50; i++ {
		mustSet(t, db, "counter", string(rune('a'+i%26)))
	}
	v, err := db.Get([]byte("counter"))
	if err != nil {
		t.Fatalf("Get: %v", err)
	}
	want := string(rune('a' + 49%26))
	if string(v) != want {
		t.Fatalf("got %q, want %q", v, want)
	}
	if len(db.List()) != 1 {
		t.Fatalf("expected exactly one key after repeated updates, got %v", db.List())
	}
}

// ---------------------------------------------------------------------------
// Edge cases
// ---------------------------------------------------------------------------

func TestEmptyKeyRejected(t *testing.T) {
	db := openTestDB(t, Options{})
	if err := db.Set([]byte(""), []byte("v"), 0); err != ErrEmptyKey {
		t.Fatalf("Set with empty key: got %v, want ErrEmptyKey", err)
	}
	if _, err := db.Get([]byte("")); err != ErrEmptyKey {
		t.Fatalf("Get with empty key: got %v, want ErrEmptyKey", err)
	}
}

func TestLongKeyAndLargeValue(t *testing.T) {
	db := openTestDB(t, Options{})
	longKey := strings.Repeat("k", 10_000)
	largeValue := bytes.Repeat([]byte("v"), 5_000_000)
	if err := db.Set([]byte(longKey), largeValue, 0); err != nil {
		t.Fatalf("Set: %v", err)
	}
	got, err := db.Get([]byte(longKey))
	if err != nil {
		t.Fatalf("Get: %v", err)
	}
	if !bytes.Equal(got, largeValue) {
		t.Fatalf("large value mismatch: got %d bytes, want %d bytes", len(got), len(largeValue))
	}
}

func TestUnicodeAndSpecialCharacters(t *testing.T) {
	db := openTestDB(t, Options{})
	cases := map[string]string{
		"emoji-key-🔑":      "value-🎉",
		"日本語のキー":           "日本語の値",
		"newline\nin\nkey": "newline\nin\nvalue",
		"tab\tkey":         "tab\tvalue",
		"quote\"key":       "quote\"value",
	}
	for k, v := range cases {
		if err := db.Set([]byte(k), []byte(v), 0); err != nil {
			t.Fatalf("Set(%q): %v", k, err)
		}
	}
	for k, v := range cases {
		got, err := db.Get([]byte(k))
		if err != nil {
			t.Fatalf("Get(%q): %v", k, err)
		}
		if string(got) != v {
			t.Fatalf("Get(%q): got %q, want %q", k, got, v)
		}
	}
}

func mustSet(t *testing.T, db *Database, key, value string) {
	t.Helper()
	if err := db.Set([]byte(key), []byte(value), 0); err != nil {
		t.Fatalf("Set(%q, %q): %v", key, value, err)
	}
}

// ---------------------------------------------------------------------------
// Recovery
// ---------------------------------------------------------------------------

func TestRecoveryTruncatedFinalRecord(t *testing.T) {
	path := tempDBPath(t)
	db, err := Open(path, Options{})
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	mustSet(t, db, "a", "1")
	mustSet(t, db, "b", "2")
	mustSet(t, db, "c", "3")
	if err := db.Close(); err != nil {
		t.Fatalf("Close: %v", err)
	}

	info, err := os.Stat(path)
	if err != nil {
		t.Fatalf("Stat: %v", err)
	}
	if err := os.Truncate(path, info.Size()-3); err != nil {
		t.Fatalf("Truncate: %v", err)
	}

	db2, err := Open(path, Options{})
	if err != nil {
		t.Fatalf("reopen after truncation: %v", err)
	}
	defer db2.Close()

	if _, err := db2.Get([]byte("a")); err != nil {
		t.Fatalf("expected 'a' to survive truncation, got %v", err)
	}
	if _, err := db2.Get([]byte("b")); err != nil {
		t.Fatalf("expected 'b' to survive truncation, got %v", err)
	}
	if _, err := db2.Get([]byte("c")); err != ErrNotFound {
		t.Fatalf("expected 'c' (torn write) to be gone, got %v", err)
	}
	s := db2.Stats()
	if s.TruncatedBytes == 0 {
		t.Fatalf("expected TruncatedBytes > 0")
	}
}

func TestRecoveryChecksumFailure(t *testing.T) {
	path := tempDBPath(t)
	db, err := Open(path, Options{})
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	mustSet(t, db, "a", "1")
	mustSet(t, db, "b", "2")
	if err := db.Close(); err != nil {
		t.Fatalf("Close: %v", err)
	}

	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("ReadFile: %v", err)
	}
	// Flip a bit near the end of the file, inside the second record.
	data[len(data)-6] ^= 0xFF
	if err := os.WriteFile(path, data, 0o600); err != nil {
		t.Fatalf("WriteFile: %v", err)
	}

	db2, err := Open(path, Options{})
	if err != nil {
		t.Fatalf("reopen after corruption: %v", err)
	}
	defer db2.Close()

	if _, err := db2.Get([]byte("a")); err != nil {
		t.Fatalf("expected 'a' to survive corruption of a later record, got %v", err)
	}
	s := db2.Stats()
	if !s.CorruptionFound {
		t.Fatalf("expected CorruptionFound = true")
	}
}

func TestRecoveryMultipleUpdatesToOneKey(t *testing.T) {
	path := tempDBPath(t)
	db, err := Open(path, Options{})
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	mustSet(t, db, "k", "v1")
	mustSet(t, db, "k", "v2")
	mustSet(t, db, "k", "v3")
	if err := db.Close(); err != nil {
		t.Fatalf("Close: %v", err)
	}

	db2, err := Open(path, Options{})
	if err != nil {
		t.Fatalf("reopen: %v", err)
	}
	defer db2.Close()

	v, err := db2.Get([]byte("k"))
	if err != nil || string(v) != "v3" {
		t.Fatalf("got (%q, %v), want (v3, nil)", v, err)
	}
}

// ---------------------------------------------------------------------------
// Concurrency
// ---------------------------------------------------------------------------

func TestConcurrentReadsAndWrites(t *testing.T) {
	db := openTestDB(t, Options{})
	var wg sync.WaitGroup

	// Writers: each goroutine owns a distinct key so there's no
	// application-level race on the expected value, only on the engine's
	// internal locking (which -race will catch if it's wrong).
	for i := 0; i < 20; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			key := []byte{byte('a' + i%26)}
			for j := 0; j < 50; j++ {
				_ = db.Set(key, []byte{byte(j)}, 0)
			}
		}(i)
	}

	// Readers hammer Get/List/Exists concurrently with the writers above.
	for i := 0; i < 20; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			key := []byte{byte('a' + i%26)}
			for j := 0; j < 50; j++ {
				_, _ = db.Get(key)
				_, _ = db.Exists(key)
				_ = db.List()
			}
		}(i)
	}

	wg.Wait()
}

// ---------------------------------------------------------------------------
// TTL
// ---------------------------------------------------------------------------

func TestTTLExpiration(t *testing.T) {
	// MiniKV stores expiration as whole unix seconds (see ttl.go), so the
	// smallest TTL that can be tested reliably without racing rounding
	// behavior is on the order of a second, not milliseconds.
	db := openTestDB(t, Options{})
	if err := db.Set([]byte("session"), []byte("abc"), 2*time.Second); err != nil {
		t.Fatalf("Set: %v", err)
	}
	if v, err := db.Get([]byte("session")); err != nil || string(v) != "abc" {
		t.Fatalf("expected live value before expiry, got (%q, %v)", v, err)
	}
	time.Sleep(2500 * time.Millisecond)
	if _, err := db.Get([]byte("session")); err != ErrNotFound {
		t.Fatalf("expected ErrNotFound after expiry, got %v", err)
	}
}

func TestTTLNonExpiringByDefault(t *testing.T) {
	db := openTestDB(t, Options{})
	mustSet(t, db, "forever", "value")
	time.Sleep(50 * time.Millisecond)
	if v, err := db.Get([]byte("forever")); err != nil || string(v) != "value" {
		t.Fatalf("expected key without ttl to survive, got (%q, %v)", v, err)
	}
}

func TestTTLSurvivesRestart(t *testing.T) {
	path := tempDBPath(t)
	db, err := Open(path, Options{})
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	if err := db.Set([]byte("session"), []byte("abc"), 1*time.Second); err != nil {
		t.Fatalf("Set: %v", err)
	}
	if err := db.Close(); err != nil {
		t.Fatalf("Close: %v", err)
	}

	time.Sleep(1500 * time.Millisecond)

	db2, err := Open(path, Options{})
	if err != nil {
		t.Fatalf("reopen: %v", err)
	}
	defer db2.Close()

	if _, err := db2.Get([]byte("session")); err != ErrNotFound {
		t.Fatalf("expected expired key to stay expired after restart, got %v", err)
	}
}

// ---------------------------------------------------------------------------
// Backup / restore
// ---------------------------------------------------------------------------

func TestBackupAndRestore(t *testing.T) {
	dir := t.TempDir()
	dbPath := filepath.Join(dir, "minikv.db")
	backupPath := filepath.Join(dir, "minikv.bak")

	db, err := Open(dbPath, Options{})
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	mustSet(t, db, "x", "1")
	mustSet(t, db, "y", "2")
	if err := db.Backup(backupPath); err != nil {
		t.Fatalf("Backup: %v", err)
	}
	mustSet(t, db, "z", "3") // written after the backup, should not appear in it
	if err := db.Close(); err != nil {
		t.Fatalf("Close: %v", err)
	}

	if err := os.Remove(dbPath); err != nil {
		t.Fatalf("Remove: %v", err)
	}
	if err := Restore(backupPath, dbPath); err != nil {
		t.Fatalf("Restore: %v", err)
	}

	db2, err := Open(dbPath, Options{})
	if err != nil {
		t.Fatalf("reopen restored db: %v", err)
	}
	defer db2.Close()

	if _, err := db2.Get([]byte("x")); err != nil {
		t.Fatalf("expected 'x' in restored db: %v", err)
	}
	if _, err := db2.Get([]byte("z")); err != ErrNotFound {
		t.Fatalf("expected 'z' (written after backup) to be absent, got %v", err)
	}
}

func TestBackupRefusesToOverwrite(t *testing.T) {
	dir := t.TempDir()
	dbPath := filepath.Join(dir, "minikv.db")
	backupPath := filepath.Join(dir, "minikv.bak")

	db, err := Open(dbPath, Options{})
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	defer db.Close()
	mustSet(t, db, "x", "1")

	if err := os.WriteFile(backupPath, []byte("existing"), 0o600); err != nil {
		t.Fatalf("WriteFile: %v", err)
	}
	if err := db.Backup(backupPath); err != ErrBackupExists {
		t.Fatalf("got %v, want ErrBackupExists", err)
	}
}

func TestRestoreRejectsInvalidBackup(t *testing.T) {
	dir := t.TempDir()
	dbPath := filepath.Join(dir, "minikv.db")
	badBackup := filepath.Join(dir, "bad.bak")

	if err := os.WriteFile(badBackup, []byte("this is not a minikv log"), 0o600); err != nil {
		t.Fatalf("WriteFile: %v", err)
	}
	if err := Restore(badBackup, dbPath); err == nil {
		t.Fatalf("expected Restore to reject an invalid backup")
	}
}

// ---------------------------------------------------------------------------
// Compaction
// ---------------------------------------------------------------------------

func TestCompactionPreservesLiveDropsDeadRestartOK(t *testing.T) {
	path := tempDBPath(t)
	db, err := Open(path, Options{})
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	mustSet(t, db, "keep1", "v1")
	mustSet(t, db, "keep2", "v2")
	mustSet(t, db, "gone", "v3")
	if err := db.Delete([]byte("gone")); err != nil {
		t.Fatalf("Delete: %v", err)
	}
	mustSet(t, db, "keep1", "v1-updated") // superseded old version should be dropped too

	before := db.Stats().LogSizeBytes
	result, err := db.Compact()
	if err != nil {
		t.Fatalf("Compact: %v", err)
	}
	if result.LiveKeysKept != 2 {
		t.Fatalf("got %d live keys kept, want 2", result.LiveKeysKept)
	}
	if result.BytesAfter >= before {
		t.Fatalf("expected compaction to shrink the log: before=%d after=%d", before, result.BytesAfter)
	}

	if v, err := db.Get([]byte("keep1")); err != nil || string(v) != "v1-updated" {
		t.Fatalf("got (%q, %v), want (v1-updated, nil)", v, err)
	}
	if _, err := db.Get([]byte("gone")); err != ErrNotFound {
		t.Fatalf("expected 'gone' to stay gone after compaction, got %v", err)
	}
	if err := db.Close(); err != nil {
		t.Fatalf("Close: %v", err)
	}

	// Restart after compaction must still work and see the compacted state.
	db2, err := Open(path, Options{})
	if err != nil {
		t.Fatalf("reopen after compaction: %v", err)
	}
	defer db2.Close()
	if v, err := db2.Get([]byte("keep1")); err != nil || string(v) != "v1-updated" {
		t.Fatalf("after restart: got (%q, %v), want (v1-updated, nil)", v, err)
	}
	if len(db2.List()) != 2 {
		t.Fatalf("after restart: got %v, want 2 keys", db2.List())
	}
}
