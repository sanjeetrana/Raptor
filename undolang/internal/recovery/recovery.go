package recovery

import (
	json "encoding/json/v2"
	"errors"
	"fmt"
	"os"

	"github.com/daniel-oluwadunsin/undolang/internal/fsop"
	"github.com/daniel-oluwadunsin/undolang/internal/journal"
	"github.com/daniel-oluwadunsin/undolang/internal/pathcap"
	"github.com/daniel-oluwadunsin/undolang/internal/state"
)

const (
	Required = "E_RECOVERY_REQUIRED"
	Failed   = "E_RECOVERY_FAILED"
	Corrupt  = "E_JOURNAL_CORRUPT"
)

type Error struct {
	Code, Message, TransactionID string
	Cause                        error
}

func (e *Error) Error() string {
	if e.TransactionID != "" {
		return fmt.Sprintf("%s: %s (transaction %s)", e.Code, e.Message, e.TransactionID)
	}
	return e.Code + ": " + e.Message
}
func (e *Error) Unwrap() error { return e.Cause }

type Options struct{ Checkpoint func(string) }

type Result struct {
	TransactionID string       `json:"transaction_id,omitempty"`
	Status        state.Status `json:"status"`
	Recovered     int          `json:"recovered_operations"`
	TornTail      bool         `json:"torn_tail_repaired,omitzero"`
}

type operation struct {
	prepared         fsop.Prepared
	applied          bool
	rollbackPrepared bool
	rollbackApplied  bool
}

func checkpoint(options Options, name string) {
	if options.Checkpoint != nil {
		options.Checkpoint(name)
	}
}

// Pending reports a recovery-owned transaction. A lock is diagnostic; the
// transaction metadata/journal remain authoritative.
func Pending(store *state.Store) (string, error) {
	lock, lockErr := store.Active()
	if !errors.Is(lockErr, os.ErrNotExist) {
		if lockErr != nil {
			return "", &Error{Code: Failed, Message: "cannot validate active transaction lock", Cause: lockErr}
		}
	}
	unresolved, err := store.Unresolved()
	if err != nil {
		return "", err
	}
	if lockErr == nil {
		for _, meta := range unresolved {
			if meta.ID != lock.TransactionID {
				return "", &Error{Code: Failed, Message: "active lock coexists with another unresolved transaction"}
			}
		}
		if _, err = store.Inspect(lock.TransactionID); err != nil {
			return "", &Error{Code: Failed, Message: "active lock transaction metadata is invalid", Cause: err}
		}
		return lock.TransactionID, nil
	}
	if len(unresolved) == 0 {
		return "", nil
	}
	if len(unresolved) > 1 {
		return "", &Error{Code: Failed, Message: "multiple unresolved transactions require manual inspection"}
	}
	return unresolved[0].ID, nil
}

func RecoverRoot(root string, options Options) (Result, error) {
	store, err := state.Open(root)
	if err != nil {
		return Result{}, err
	}
	id, err := Pending(store)
	if err != nil {
		return Result{}, err
	}
	if id == "" {
		return Result{Status: state.RolledBack}, nil
	}
	return Recover(store, id, options)
}

func Recover(store *state.Store, id string, options Options) (result Result, retErr error) {
	result.TransactionID = id
	tx, replay, err := store.OpenTransaction(id, true)
	if err != nil {
		code := Failed
		if errors.Is(err, journal.ErrCorrupt) {
			code = Corrupt
		}
		return result, &Error{Code: code, Message: "cannot replay transaction journal", TransactionID: id, Cause: err}
	}
	defer tx.Close()
	result.TornTail = replay.TornTail
	if replay.Committed || replay.RolledBack {
		terminal := state.Committed
		if replay.RolledBack {
			terminal = state.RolledBack
		}
		if err = tx.ReconcileStatus(terminal); err != nil {
			return terminalFail(result, id, "cannot reconcile terminal transaction status", err)
		}
		if !tx.Meta.BackupCleaned {
			if err = tx.CleanupBackups(); err != nil {
				return terminalFail(result, id, "cannot clean terminal transaction backups", err)
			}
		}
		if err = tx.Release(); err != nil {
			return terminalFail(result, id, "cannot release terminal transaction lock", err)
		}
		result.Status = terminal
		return result, nil
	}

	if err = tx.ReconcileStatus(state.Status(replay.State)); err != nil {
		return fail(tx, result, "cannot reconcile transaction state from journal", err)
	}
	if tx.Meta.Status != state.RollingBack {
		if err = tx.Transition(state.RollingBack); err != nil {
			return result, err
		}
	}

	caps, err := pathcap.Open(tx.Meta.Root, tx.Meta.AllowedRoots)
	if err != nil {
		return fail(tx, result, "cannot reopen transaction capabilities", err)
	}
	defer caps.Close()
	engine, err := fsop.Open(caps, tx.BackupDir)
	if err != nil {
		return fail(tx, result, "cannot open transaction backups", err)
	}
	defer engine.Close()

	ordered, operations, err := replayOperations(replay)
	if err != nil {
		return fail(tx, result, "cannot decode prepared operation metadata", err)
	}
	for index := len(ordered) - 1; index >= 0; index-- {
		id := ordered[index]
		op := operations[id]
		if err = engine.CleanupTemporaries(op.prepared); err != nil {
			return fail(tx, result, "cannot clean transaction temporary file", err)
		}
		disposition, classifyErr := engine.Classify(op.prepared)
		if classifyErr != nil || disposition == fsop.Ambiguous {
			if classifyErr == nil {
				classifyErr = errors.New("filesystem matches neither durable before nor after state")
			}
			return fail(tx, result, "operation recovery state is ambiguous", classifyErr)
		}
		if op.rollbackApplied {
			if disposition != fsop.Before {
				return fail(tx, result, "rollback record conflicts with filesystem state", errors.New(id))
			}
			continue
		}
		if !op.rollbackPrepared {
			if _, err = tx.Journal.Append(journal.RollbackPrepared, journal.Payload{TransactionID: tx.Meta.ID, OperationID: id}); err != nil {
				return fail(tx, result, "cannot persist rollback preparation", err)
			}
		}
		if disposition == fsop.After {
			if err = engine.Undo(&op.prepared); err != nil {
				return fail(tx, result, "inverse operation failed", err)
			}
		}
		disposition, err = engine.Classify(op.prepared)
		if err != nil || disposition != fsop.Before {
			if err == nil {
				err = errors.New("inverse verification did not restore before state")
			}
			return fail(tx, result, "inverse verification failed", err)
		}
		checkpoint(options, "rollback_inverse_applied")
		if _, err = tx.Journal.Append(journal.RollbackApplied, journal.Payload{TransactionID: tx.Meta.ID, OperationID: id}); err != nil {
			return fail(tx, result, "cannot persist rollback completion", err)
		}
		result.Recovered++
	}
	if _, err = tx.Journal.Append(journal.TXRollbackComplete, journal.Payload{TransactionID: tx.Meta.ID}); err != nil {
		return fail(tx, result, "cannot persist transaction rollback completion", err)
	}
	checkpoint(options, "rollback_complete_recorded")
	if err = tx.Transition(state.RolledBack); err != nil {
		return fail(tx, result, "cannot persist rolled-back state", err)
	}
	if err = tx.CleanupBackups(); err != nil {
		return fail(tx, result, "cannot clean finalized backups", err)
	}
	if err = tx.Release(); err != nil {
		return fail(tx, result, "cannot release finalized transaction lock", err)
	}
	result.Status = state.RolledBack
	return result, nil
}

func terminalFail(result Result, id, message string, cause error) (Result, error) {
	result.Status = state.RecoveryFailed
	return result, &Error{Code: Failed, Message: message, TransactionID: id, Cause: cause}
}

func fail(tx *state.Transaction, result Result, message string, cause error) (Result, error) {
	result.Status = state.RecoveryFailed
	if tx.Meta.Status == state.RollingBack {
		_ = tx.Transition(state.RecoveryFailed)
	} else {
		_ = tx.ReconcileStatus(state.RecoveryFailed)
	}
	return result, &Error{Code: Failed, Message: message, TransactionID: tx.Meta.ID, Cause: cause}
}

func replayOperations(replay journal.Replay) ([]string, map[string]*operation, error) {
	var ordered []string
	operations := make(map[string]*operation)
	for _, record := range replay.Records {
		var payload struct {
			OperationID string        `json:"operation_id"`
			Data        fsop.Prepared `json:"data"`
		}
		if err := json.Unmarshal(record.Payload, &payload); err != nil {
			return nil, nil, err
		}
		switch record.Type {
		case journal.OPPrepared:
			copy := payload.Data
			if copy.OperationID != payload.OperationID || copy.OperationID == "" {
				return nil, nil, errors.New("prepared operation id mismatch")
			}
			operations[payload.OperationID] = &operation{prepared: copy}
			ordered = append(ordered, payload.OperationID)
		case journal.OPApplied:
			operations[payload.OperationID].applied = true
		case journal.RollbackPrepared:
			operations[payload.OperationID].rollbackPrepared = true
		case journal.RollbackApplied:
			operations[payload.OperationID].rollbackApplied = true
		}
	}
	return ordered, operations, nil
}
