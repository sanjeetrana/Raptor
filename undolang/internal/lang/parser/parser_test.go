package parser

import (
	"testing"

	"github.com/daniel-oluwadunsin/undolang/internal/lang/ast"
	"github.com/daniel-oluwadunsin/undolang/internal/lang/diag"
	"github.com/daniel-oluwadunsin/undolang/internal/lang/lexer"
)

func parseSource(t *testing.T, src string) (ast.Program, *diag.Error) {
	t.Helper()
	tokens, lexErr := lexer.Lex([]byte(src))
	if lexErr != nil {
		t.Fatal(lexErr)
	}
	return Parse(tokens)
}

func TestParseAllStatementsAndTransactionOrder(t *testing.T) {
	src := `transaction "a" {
require exists "a"
require not_exists "b"
require is_file "a"
require is_dir "d"
require contains "a" "x"
require sha256 "a" = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
mkdir "d" copy "a" -> "b" overwrite move "b" -> "c" write "w" = "x" replace "w" "x" -> "y" delete "c"
assert exists "w"
}
transaction "b" {}`
	program, err := parseSource(t, src)
	if err != nil {
		t.Fatal(err)
	}
	if len(program.Transactions) != 2 || program.Transactions[0].Name != "a" || program.Transactions[1].Name != "b" {
		t.Fatalf("transactions: %#v", program.Transactions)
	}
	if got := len(program.Transactions[0].Statements); got != 13 {
		t.Fatalf("statements = %d", got)
	}
	copyStmt := program.Transactions[0].Statements[7]
	if copyStmt.Kind != ast.Copy || !copyStmt.Overwrite {
		t.Fatalf("copy = %#v", copyStmt)
	}
}

func TestParseDiagnostics(t *testing.T) {
	tests := []struct{ name, src, code, suggestion string }{
		{"missing name", `transaction {}`, diag.Syntax, ""},
		{"missing brace", `transaction "x" { mkdir "a"`, diag.Syntax, ""},
		{"unknown", `transaction "x" { mve "a" -> "b" }`, diag.UnknownInstruction, "move"},
		{"trailing", `transaction "x" {} garbage`, diag.UnknownInstruction, ""},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			_, err := parseSource(t, tt.src)
			if err == nil || err.Code != tt.code || err.Suggestion != tt.suggestion {
				t.Fatalf("error = %#v", err)
			}
		})
	}
}

func FuzzParseNeverPanics(f *testing.F) {
	for _, seed := range []string{"", `transaction "x" {}`, `transaction "x" { copy "a" -> "b" }`} {
		f.Add(seed)
	}
	f.Fuzz(func(t *testing.T, src string) {
		tokens, err := lexer.Lex([]byte(src))
		if err == nil {
			_, _ = Parse(tokens)
		}
	})
}
