package txn

import (
	"errors"
	"fmt"

	"github.com/daniel-oluwadunsin/undolang/internal/condition"
	"github.com/daniel-oluwadunsin/undolang/internal/fsop"
	"github.com/daniel-oluwadunsin/undolang/internal/journal"
	"github.com/daniel-oluwadunsin/undolang/internal/lang/validate"
	"github.com/daniel-oluwadunsin/undolang/internal/pathcap"
	"github.com/daniel-oluwadunsin/undolang/internal/plan"
	"github.com/daniel-oluwadunsin/undolang/internal/recovery"
	"github.com/daniel-oluwadunsin/undolang/internal/state"
)

const (
	PreconditionFailed  = "E_PRECONDITION_FAILED"
	PostconditionFailed = "E_POSTCONDITION_FAILED"
	TransactionFailed   = "E_TRANSACTION_FAILED"
)

type Error struct {
	Code, Message, TransactionID string
	Cause                        error
	RolledBack                   bool
}

func (e *Error) Error() string {
	if e.TransactionID != "" {
		return fmt.Sprintf("%s: %s (transaction %s)", e.Code, e.Message, e.TransactionID)
	}
	return e.Code + ": " + e.Message
}
func (e *Error) Unwrap() error { return e.Cause }

type Options struct {
	ScriptPath, ScriptSHA256 string
	Checkpoint               func(string)
}

type Result struct {
	TransactionID string       `json:"transaction_id"`
	Status        state.Status `json:"status"`
}

func Execute(transaction validate.Transaction, capabilities *pathcap.Set, options Options) (Result, error) {
	store, err := state.Open(capabilities.Primary())
	if err != nil {
		return Result{}, err
	}
	if id, pendingErr := recovery.Pending(store); pendingErr != nil {
		return Result{}, pendingErr
	} else if id != "" {
		return Result{}, &recovery.Error{Code: recovery.Required, Message: "an unresolved transaction blocks execution", TransactionID: id}
	}
	tx, err := store.BeginWithOptions(state.BeginOptions{
		Name:         transaction.Name,
		ScriptPath:   options.ScriptPath,
		ScriptHash:   options.ScriptSHA256,
		AllowedRoots: allowedRoots(capabilities),
	})
	if err != nil {
		return Result{}, err
	}
	result := Result{TransactionID: tx.Meta.ID, Status: state.Planned}
	checkpoint(options, "tx_begin")

	exact, err := exactPlan(transaction, capabilities, options)
	if err != nil {
		return rollbackFailure(tx, result, options, TransactionFailed, "post-lock planning failed", err)
	}
	if !exact.SafeToExecute {
		return rollbackFailure(tx, result, options, PreconditionFailed, "precondition failed after lock acquisition", errors.New(joinReasons(exact.Reasons)))
	}
	if err = tx.Transition(state.Prepared); err != nil {
		return Result{TransactionID: tx.Meta.ID, Status: state.RecoveryRequired}, &recovery.Error{Code: recovery.Required, Message: "cannot persist prepared state", TransactionID: tx.Meta.ID, Cause: err}
	}
	if err = tx.Transition(state.Running); err != nil {
		return rollbackFailure(tx, result, options, TransactionFailed, "cannot enter running state", err)
	}
	engine, err := fsop.Open(capabilities, tx.BackupDir)
	if err != nil {
		return rollbackFailure(tx, result, options, TransactionFailed, "cannot open operation engine", err)
	}
	for index, operation := range transaction.Operations {
		operationID := fmt.Sprintf("%06d", index+1)
		prepared, operationErr := engine.Prepare(operationID, operation)
		if operationErr != nil {
			_ = engine.Close()
			return rollbackFailure(tx, result, options, TransactionFailed, "operation preparation failed", operationErr)
		}
		checkpoint(options, "backup_prepared")
		if _, operationErr = tx.Journal.Append(journal.OPPrepared, journal.Payload{TransactionID: tx.Meta.ID, OperationID: operationID, Data: prepared}); operationErr != nil {
			_ = engine.Close()
			return Result{TransactionID: tx.Meta.ID, Status: state.RecoveryRequired}, &recovery.Error{Code: recovery.Required, Message: "operation preparation could not be journaled", TransactionID: tx.Meta.ID, Cause: operationErr}
		}
		checkpoint(options, "op_prepared")
		if operationErr = engine.Apply(&prepared, operation); operationErr == nil {
			checkpoint(options, "mutation_applied")
			operationErr = engine.Verify(&prepared, operation)
		}
		if operationErr != nil {
			_ = engine.Close()
			return rollbackFailure(tx, result, options, TransactionFailed, "operation failed", operationErr)
		}
		if _, operationErr = tx.Journal.Append(journal.OPApplied, journal.Payload{TransactionID: tx.Meta.ID, OperationID: operationID}); operationErr != nil {
			_ = engine.Close()
			return Result{TransactionID: tx.Meta.ID, Status: state.RecoveryRequired}, &recovery.Error{Code: recovery.Required, Message: "applied operation could not be journaled", TransactionID: tx.Meta.ID, Cause: operationErr}
		}
		checkpoint(options, "op_applied")
	}
	if err = engine.Close(); err != nil {
		return rollbackFailure(tx, result, options, TransactionFailed, "cannot close operation engine", err)
	}
	if err = tx.Transition(state.Verifying); err != nil {
		return rollbackFailure(tx, result, options, TransactionFailed, "cannot enter verification state", err)
	}
	checkpoint(options, "verifying")
	for index, assertion := range transaction.Assertions {
		assertionResult, assertionErr := condition.Evaluate(assertion, capabilities)
		data := struct {
			Index  int              `json:"index"`
			Result condition.Result `json:"result"`
		}{Index: index, Result: assertionResult}
		if _, journalErr := tx.Journal.Append(journal.AssertResult, journal.Payload{TransactionID: tx.Meta.ID, Data: data}); journalErr != nil {
			return Result{TransactionID: tx.Meta.ID, Status: state.RecoveryRequired}, &recovery.Error{Code: recovery.Required, Message: "assertion result could not be journaled", TransactionID: tx.Meta.ID, Cause: journalErr}
		}
		if assertionErr != nil {
			return rollbackFailure(tx, result, options, PostconditionFailed, "postcondition evaluation failed", assertionErr)
		}
		if !assertionResult.Value {
			return rollbackFailure(tx, result, options, PostconditionFailed, "postcondition failed", fmt.Errorf("assertion %d", index+1))
		}
	}
	if err = tx.Transition(state.Committing); err != nil {
		return rollbackFailure(tx, result, options, TransactionFailed, "cannot enter committing state", err)
	}
	if _, err = tx.Journal.Append(journal.TXCommit, journal.Payload{TransactionID: tx.Meta.ID}); err != nil {
		return Result{TransactionID: tx.Meta.ID, Status: state.RecoveryRequired}, &recovery.Error{Code: recovery.Required, Message: "commit record could not be persisted", TransactionID: tx.Meta.ID, Cause: err}
	}
	if err = tx.Transition(state.Committed); err != nil {
		return Result{TransactionID: tx.Meta.ID, Status: state.RecoveryRequired}, &recovery.Error{Code: recovery.Required, Message: "committed status could not be persisted", TransactionID: tx.Meta.ID, Cause: err}
	}
	if err = tx.CleanupBackups(); err != nil {
		return Result{TransactionID: tx.Meta.ID, Status: state.RecoveryRequired}, &recovery.Error{Code: recovery.Required, Message: "committed backup cleanup failed", TransactionID: tx.Meta.ID, Cause: err}
	}
	if err = tx.Release(); err != nil {
		return Result{TransactionID: tx.Meta.ID, Status: state.RecoveryRequired}, &recovery.Error{Code: recovery.Required, Message: "committed lock cleanup failed", TransactionID: tx.Meta.ID, Cause: err}
	}
	return Result{TransactionID: tx.Meta.ID, Status: state.Committed}, nil
}

func rollbackFailure(tx *state.Transaction, result Result, options Options, code, message string, cause error) (Result, error) {
	id := tx.Meta.ID
	_ = tx.Close()
	recovered, recoverErr := recovery.RecoverRoot(tx.Meta.Root, recovery.Options{Checkpoint: options.Checkpoint})
	if recoverErr != nil {
		return Result{TransactionID: id, Status: state.RecoveryFailed}, &recovery.Error{Code: recovery.Failed, Message: message + "; automatic rollback failed", TransactionID: id, Cause: errors.Join(cause, recoverErr)}
	}
	result.TransactionID, result.Status = id, recovered.Status
	return result, &Error{Code: code, Message: message, TransactionID: id, Cause: cause, RolledBack: true}
}

func exactPlan(transaction validate.Transaction, capabilities *pathcap.Set, options Options) (plan.Plan, error) {
	programPlan, err := plan.Build(validate.Program{Transactions: []validate.Transaction{transaction}}, capabilities, plan.Options{ScriptPath: options.ScriptPath, ScriptSHA256: options.ScriptSHA256})
	if err != nil {
		return plan.Plan{}, err
	}
	if len(programPlan.Transactions) != 1 || programPlan.Transactions[0].Plan == nil {
		return plan.Plan{}, errors.New("exact transaction plan missing")
	}
	return *programPlan.Transactions[0].Plan, nil
}

func allowedRoots(capabilities *pathcap.Set) []string {
	var roots []string
	for _, root := range capabilities.Roots() {
		if !root.Primary {
			roots = append(roots, root.Path)
		}
	}
	return roots
}

func checkpoint(options Options, name string) {
	if options.Checkpoint != nil {
		options.Checkpoint(name)
	}
}

func joinReasons(reasons []string) string {
	if len(reasons) == 0 {
		return "transaction is not safe to execute"
	}
	result := reasons[0]
	for _, reason := range reasons[1:] {
		result += "; " + reason
	}
	return result
}
