package validate

import (
	"encoding/hex"
	"strings"

	"github.com/daniel-oluwadunsin/undolang/internal/lang/ast"
	"github.com/daniel-oluwadunsin/undolang/internal/lang/diag"
	"github.com/daniel-oluwadunsin/undolang/internal/lang/token"
)

type Program struct {
	Transactions []Transaction
}

type Transaction struct {
	Name       string
	Requires   []ast.Condition
	Operations []ast.Statement
	Assertions []ast.Condition
	Span       token.Span
}

func Validate(program ast.Program) (Program, *diag.Error) {
	seen := make(map[string]token.Span, len(program.Transactions))
	out := Program{Transactions: make([]Transaction, 0, len(program.Transactions))}
	for _, tx := range program.Transactions {
		if strings.TrimSpace(tx.Name) == "" {
			return Program{}, diag.New(diag.Semantic, "transaction name must not be empty", tx.Span)
		}
		if _, exists := seen[tx.Name]; exists {
			return Program{}, diag.New(diag.Semantic, "duplicate transaction name "+tx.Name, tx.Span)
		}
		seen[tx.Name] = tx.Span
		validated, err := transaction(tx)
		if err != nil {
			return Program{}, err
		}
		out.Transactions = append(out.Transactions, validated)
	}
	return out, nil
}

func transaction(tx ast.Transaction) (Transaction, *diag.Error) {
	out := Transaction{Name: tx.Name, Span: tx.Span}
	phase := 0
	for _, stmt := range tx.Statements {
		switch stmt.Kind {
		case ast.Require:
			if phase > 0 {
				return Transaction{}, diag.New(diag.PhaseOrder, "require statements must precede mutations and assertions", stmt.Span)
			}
			cond, err := condition(*stmt.Condition)
			if err != nil {
				return Transaction{}, err
			}
			out.Requires = append(out.Requires, cond)
		case ast.Assert:
			phase = 2
			cond, err := condition(*stmt.Condition)
			if err != nil {
				return Transaction{}, err
			}
			out.Assertions = append(out.Assertions, cond)
		default:
			if phase == 2 {
				return Transaction{}, diag.New(diag.PhaseOrder, "mutation statements must precede assertions", stmt.Span)
			}
			phase = 1
			if err := operation(stmt); err != nil {
				return Transaction{}, err
			}
			out.Operations = append(out.Operations, stmt)
		}
	}
	return out, nil
}

func condition(c ast.Condition) (ast.Condition, *diag.Error) {
	if strings.TrimSpace(c.Path) == "" {
		return c, diag.New(diag.Semantic, "condition path must not be empty", c.Span)
	}
	if c.Kind == ast.Contains && c.Value == "" {
		return c, diag.New(diag.Semantic, "contains literal must not be empty", c.Span)
	}
	if c.Kind == ast.SHA256 {
		if len(c.Value) != 64 {
			return c, diag.New(diag.Semantic, "SHA-256 digest must contain exactly 64 hexadecimal characters", c.Span)
		}
		if _, err := hex.DecodeString(c.Value); err != nil {
			return c, diag.New(diag.Semantic, "SHA-256 digest contains non-hexadecimal characters", c.Span)
		}
		c.Value = strings.ToLower(c.Value)
	}
	return c, nil
}

func operation(s ast.Statement) *diag.Error {
	paths := []string{s.Path}
	if s.Kind == ast.Copy || s.Kind == ast.Move {
		paths = []string{s.Source, s.Target}
	}
	for _, path := range paths {
		if strings.TrimSpace(path) == "" {
			return diag.New(diag.Semantic, "operation path must not be empty", s.Span)
		}
	}
	if s.Kind == ast.Replace && s.Old == "" {
		return diag.New(diag.Semantic, "replace old literal must not be empty", s.Span)
	}
	return nil
}

func Names(program Program) []string {
	names := make([]string, len(program.Transactions))
	for i := range program.Transactions {
		names[i] = program.Transactions[i].Name
	}
	return names
}
