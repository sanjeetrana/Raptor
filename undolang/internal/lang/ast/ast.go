package ast

import "github.com/daniel-oluwadunsin/undolang/internal/lang/token"

type Program struct {
	Transactions []Transaction
	Span         token.Span
}

type Transaction struct {
	Name       string
	Statements []Statement
	Span       token.Span
}

type StatementKind string

const (
	Require StatementKind = "require"
	Assert  StatementKind = "assert"
	Mkdir   StatementKind = "mkdir"
	Copy    StatementKind = "copy"
	Move    StatementKind = "move"
	Write   StatementKind = "write"
	Replace StatementKind = "replace"
	Delete  StatementKind = "delete"
)

type ConditionKind string

const (
	Exists    ConditionKind = "exists"
	NotExists ConditionKind = "not_exists"
	IsFile    ConditionKind = "is_file"
	IsDir     ConditionKind = "is_dir"
	Contains  ConditionKind = "contains"
	SHA256    ConditionKind = "sha256"
)

type Condition struct {
	Kind  ConditionKind
	Path  string
	Value string
	Span  token.Span
}

type Statement struct {
	Kind      StatementKind
	Path      string
	Source    string
	Target    string
	Old       string
	New       string
	Content   string
	Overwrite bool
	Condition *Condition
	Span      token.Span
}
