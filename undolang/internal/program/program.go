package program

import (
	"errors"
	"fmt"
	"os"

	"github.com/daniel-oluwadunsin/undolang/internal/lang/validate"
	"github.com/daniel-oluwadunsin/undolang/internal/pathcap"
	"github.com/daniel-oluwadunsin/undolang/internal/plan"
	"github.com/daniel-oluwadunsin/undolang/internal/recovery"
	"github.com/daniel-oluwadunsin/undolang/internal/state"
	"github.com/daniel-oluwadunsin/undolang/internal/txn"
)

type Status string

const (
	Committed        Status = "committed"
	RolledBack       Status = "rolled_back"
	FailedPreflight  Status = "failed_preflight"
	RecoveryRequired Status = "recovery_required"
	RecoveryFailed   Status = "recovery_failed"
	Skipped          Status = "skipped"
)

type TransactionResult struct {
	Name          string       `json:"name"`
	TransactionID string       `json:"transaction_id,omitempty"`
	Status        Status       `json:"status"`
	Error         *ResultError `json:"error,omitempty"`
}

type ResultError struct {
	Code    string `json:"code"`
	Message string `json:"message"`
}

type Result struct {
	ScriptPath   string              `json:"script_path"`
	Mode         string              `json:"mode"`
	SelectedName string              `json:"selected_name,omitempty"`
	Transactions []TransactionResult `json:"transactions"`
}

type Error struct {
	Code, Message string
	Cause         error
}

func (e *Error) Error() string { return e.Code + ": " + e.Message }
func (e *Error) Unwrap() error { return e.Cause }

type Options struct {
	ScriptPath, ScriptSHA256, SelectedName string
	Checkpoint                             func(string)
}

func Run(program validate.Program, capabilities *pathcap.Set, options Options) (Result, error) {
	result := Result{ScriptPath: options.ScriptPath, Mode: "all", SelectedName: options.SelectedName}
	transactions := program.Transactions
	if options.SelectedName != "" {
		result.Mode = "selected"
		found := false
		for _, transaction := range transactions {
			if transaction.Name == options.SelectedName {
				transactions = []validate.Transaction{transaction}
				found = true
				break
			}
		}
		if !found {
			return result, &Error{Code: "E_CONFLICT", Message: "unknown transaction " + options.SelectedName}
		}
	}
	for index, transaction := range transactions {
		exact, err := plan.Build(validate.Program{Transactions: []validate.Transaction{transaction}}, capabilities, plan.Options{ScriptPath: options.ScriptPath, ScriptSHA256: options.ScriptSHA256})
		if err != nil {
			failed := TransactionResult{Name: transaction.Name, Status: FailedPreflight, Error: &ResultError{Code: errorCode(err), Message: err.Error()}}
			result.Transactions = append(result.Transactions, failed)
			appendSkipped(&result, transactions[index+1:])
			return result, &Error{Code: failed.Error.Code, Message: "transaction planning failed", Cause: err}
		}
		transactionPlan := exact.Transactions[0].Plan
		if transactionPlan == nil || !transactionPlan.SafeToExecute {
			failed := TransactionResult{Name: transaction.Name, Status: FailedPreflight, Error: &ResultError{Code: txn.PreconditionFailed, Message: "transaction precondition failed"}}
			result.Transactions = append(result.Transactions, failed)
			appendSkipped(&result, transactions[index+1:])
			return result, &Error{Code: txn.PreconditionFailed, Message: failed.Error.Message}
		}
		txResult, err := txn.Execute(transaction, capabilities, txn.Options{ScriptPath: options.ScriptPath, ScriptSHA256: options.ScriptSHA256, Checkpoint: options.Checkpoint})
		entry := TransactionResult{Name: transaction.Name, TransactionID: txResult.TransactionID}
		if err == nil {
			entry.Status = Committed
			result.Transactions = append(result.Transactions, entry)
			continue
		}
		entry.Error = &ResultError{Code: errorCode(err), Message: err.Error()}
		if txResult.TransactionID == "" {
			entry.Status = FailedPreflight
		} else {
			switch txResult.Status {
			case state.RolledBack:
				entry.Status = RolledBack
			case state.RecoveryFailed:
				entry.Status = RecoveryFailed
			default:
				entry.Status = RecoveryRequired
			}
		}
		result.Transactions = append(result.Transactions, entry)
		appendSkipped(&result, transactions[index+1:])
		return result, &Error{Code: entry.Error.Code, Message: "transaction did not commit", Cause: err}
	}
	return result, nil
}

func appendSkipped(result *Result, transactions []validate.Transaction) {
	for _, transaction := range transactions {
		result.Transactions = append(result.Transactions, TransactionResult{Name: transaction.Name, Status: Skipped, Error: &ResultError{Code: "E_SKIPPED", Message: "not started after prior transaction failure"}})
	}
}

func errorCode(err error) string {
	var transactionError *txn.Error
	var recoveryError *recovery.Error
	var planError *plan.Error
	switch {
	case errors.As(err, &transactionError):
		return transactionError.Code
	case errors.As(err, &recoveryError):
		return recoveryError.Code
	case errors.As(err, &planError):
		return planError.Code
	case errors.Is(err, os.ErrPermission):
		return "E_PERMISSION"
	default:
		return "E_IO"
	}
}

func (r Result) Summary() string {
	return fmt.Sprintf("%d transaction result(s)", len(r.Transactions))
}
