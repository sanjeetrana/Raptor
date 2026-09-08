package recovery

import (
	"errors"
	"os"
	"path/filepath"
	"testing"

	"github.com/daniel-oluwadunsin/undolang/internal/fsop"
	"github.com/daniel-oluwadunsin/undolang/internal/journal"
	"github.com/daniel-oluwadunsin/undolang/internal/lang/ast"
	"github.com/daniel-oluwadunsin/undolang/internal/pathcap"
	"github.com/daniel-oluwadunsin/undolang/internal/state"
)

func interruptedWrite(t *testing.T, apply, appliedRecord bool) (string, string) {
	t.Helper()
	root := t.TempDir()
	store, err := state.Open(root)
	if err != nil {
		t.Fatal(err)
	}
	tx, err := store.Begin("test", "test.undo", "hash")
	if err != nil {
		t.Fatal(err)
	}
	if err = tx.Transition(state.Prepared); err != nil {
		t.Fatal(err)
	}
	if err = tx.Transition(state.Running); err != nil {
		t.Fatal(err)
	}
	caps, err := pathcap.Open(root, nil)
	if err != nil {
		t.Fatal(err)
	}
	engine, err := fsop.Open(caps, tx.BackupDir)
	if err != nil {
		t.Fatal(err)
	}
	op := ast.Statement{Kind: ast.Write, Path: "file", Content: "after"}
	prepared, err := engine.Prepare("000001", op)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = tx.Journal.Append(journal.OPPrepared, journal.Payload{TransactionID: tx.Meta.ID, OperationID: prepared.OperationID, Data: prepared}); err != nil {
		t.Fatal(err)
	}
	if apply {
		if err = engine.Apply(&prepared, op); err != nil {
			t.Fatal(err)
		}
	}
	if appliedRecord {
		if _, err = tx.Journal.Append(journal.OPApplied, journal.Payload{TransactionID: tx.Meta.ID, OperationID: prepared.OperationID}); err != nil {
			t.Fatal(err)
		}
	}
	if err = errors.Join(engine.Close(), caps.Close(), tx.Close()); err != nil {
		t.Fatal(err)
	}
	return root, tx.Meta.ID
}

func TestRecoveryPreparedButNotMutated(t *testing.T) {
	root, id := interruptedWrite(t, false, false)
	result, err := RecoverRoot(root, Options{})
	if err != nil {
		t.Fatal(err)
	}
	if result.TransactionID != id || result.Status != state.RolledBack {
		t.Fatalf("result=%#v", result)
	}
	if _, err := os.Stat(filepath.Join(root, "file")); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("unexpected target: %v", err)
	}
}

func TestRecoveryMutationWithoutAppliedRecord(t *testing.T) {
	root, id := interruptedWrite(t, true, false)
	result, err := RecoverRoot(root, Options{})
	if err != nil || result.TransactionID != id {
		t.Fatalf("result=%#v err=%v", result, err)
	}
	if _, err := os.Stat(filepath.Join(root, "file")); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("mutation was not reversed: %v", err)
	}
}

func TestRecoveryAppliedRecordAndIdempotency(t *testing.T) {
	root, _ := interruptedWrite(t, true, true)
	if _, err := RecoverRoot(root, Options{}); err != nil {
		t.Fatal(err)
	}
	result, err := RecoverRoot(root, Options{})
	if err != nil || result.Status != state.RolledBack {
		t.Fatalf("second recovery=%#v err=%v", result, err)
	}
}

func TestRecoveryWithoutActiveLockUsesSingleUnresolvedTransaction(t *testing.T) {
	root, id := interruptedWrite(t, true, true)
	if err := os.Remove(filepath.Join(root, ".undo", "active.lock")); err != nil {
		t.Fatal(err)
	}
	result, err := RecoverRoot(root, Options{})
	if err != nil || result.TransactionID != id || result.Status != state.RolledBack {
		t.Fatalf("result=%#v err=%v", result, err)
	}
	if _, err := os.Stat(filepath.Join(root, ".undo", "active.lock")); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("unexpected lock after recovery: %v", err)
	}
}

func TestRecoveryReconcilesCommittedJournalWithStaleLock(t *testing.T) {
	root := t.TempDir()
	store, err := state.Open(root)
	if err != nil {
		t.Fatal(err)
	}
	tx, err := store.Begin("committed", "test.undo", "hash")
	if err != nil {
		t.Fatal(err)
	}
	for _, status := range []state.Status{state.Prepared, state.Running, state.Verifying, state.Committing} {
		if err = tx.Transition(status); err != nil {
			t.Fatal(err)
		}
	}
	if _, err = tx.Journal.Append(journal.TXCommit, journal.Payload{TransactionID: tx.Meta.ID}); err != nil {
		t.Fatal(err)
	}
	if err = tx.Transition(state.Committed); err != nil {
		t.Fatal(err)
	}
	if err = tx.Close(); err != nil {
		t.Fatal(err)
	}
	result, err := RecoverRoot(root, Options{})
	if err != nil || result.Status != state.Committed || result.TransactionID != tx.Meta.ID {
		t.Fatalf("result=%#v err=%v", result, err)
	}
	if _, err = os.Stat(filepath.Join(root, ".undo", "active.lock")); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("stale lock remains: %v", err)
	}
}

func TestPendingFailsClosedWithMultipleUnresolvedTransactions(t *testing.T) {
	root := t.TempDir()
	store, _ := state.Open(root)
	first, err := store.Begin("first", "test.undo", "hash")
	if err != nil {
		t.Fatal(err)
	}
	_ = first.Close()
	if err = os.Remove(filepath.Join(root, ".undo", "active.lock")); err != nil {
		t.Fatal(err)
	}
	second, err := store.Begin("second", "test.undo", "hash")
	if err != nil {
		t.Fatal(err)
	}
	_ = second.Close()
	if _, err = Pending(store); err == nil {
		t.Fatal("active lock masked another unresolved transaction")
	}
	if err = os.Remove(filepath.Join(root, ".undo", "active.lock")); err != nil {
		t.Fatal(err)
	}
	if _, err = Pending(store); err == nil {
		t.Fatal("multiple lockless unresolved transactions were accepted")
	}
}

func TestRecoveryTruncatesOnlyTornFinalFrame(t *testing.T) {
	root, _ := interruptedWrite(t, true, true)
	store, _ := state.Open(root)
	lock, err := store.Active()
	if err != nil {
		t.Fatal(err)
	}
	meta, err := store.Inspect(lock.TransactionID)
	if err != nil {
		t.Fatal(err)
	}
	journalPath := filepath.Join(root, ".undo", "transactions", meta.ID, "journal.bin")
	file, err := os.OpenFile(journalPath, os.O_APPEND|os.O_WRONLY, 0)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = file.Write([]byte("UND")); err != nil {
		t.Fatal(err)
	}
	if err = file.Close(); err != nil {
		t.Fatal(err)
	}
	result, err := RecoverRoot(root, Options{})
	if err != nil || !result.TornTail {
		t.Fatalf("result=%#v err=%v", result, err)
	}
}

func TestRecoveryFailsClosedOnAmbiguousMutation(t *testing.T) {
	root, id := interruptedWrite(t, true, true)
	if err := os.WriteFile(filepath.Join(root, "file"), []byte("external"), 0o644); err != nil {
		t.Fatal(err)
	}
	result, err := RecoverRoot(root, Options{})
	var recoveryError *Error
	if !errors.As(err, &recoveryError) || recoveryError.Code != Failed || result.Status != state.RecoveryFailed {
		t.Fatalf("result=%#v err=%v", result, err)
	}
	if _, statErr := os.Stat(filepath.Join(root, ".undo", "transactions", id, "backup")); statErr != nil {
		t.Fatalf("backup was not retained: %v", statErr)
	}
}

func TestRecoveryResumesAfterInverseBeforeRecord(t *testing.T) {
	root, _ := interruptedWrite(t, true, true)
	func() {
		defer func() { _ = recover() }()
		_, _ = RecoverRoot(root, Options{Checkpoint: func(point string) {
			if point == "rollback_inverse_applied" {
				panic("simulated process loss")
			}
		}})
	}()
	result, err := RecoverRoot(root, Options{})
	if err != nil || result.Status != state.RolledBack {
		t.Fatalf("resumed result=%#v err=%v", result, err)
	}
	if _, err := os.Stat(filepath.Join(root, "file")); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("resumed recovery did not restore target: %v", err)
	}
}
