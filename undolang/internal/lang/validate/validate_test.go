package validate

import (
	"strings"
	"testing"

	"github.com/daniel-oluwadunsin/undolang/internal/lang/diag"
	"github.com/daniel-oluwadunsin/undolang/internal/lang/lexer"
	"github.com/daniel-oluwadunsin/undolang/internal/lang/parser"
)

func validateSource(t *testing.T, src string) (Program, *diag.Error) {
	t.Helper()
	tokens, lexErr := lexer.Lex([]byte(src))
	if lexErr != nil {
		t.Fatal(lexErr)
	}
	program, parseErr := parser.Parse(tokens)
	if parseErr != nil {
		t.Fatal(parseErr)
	}
	return Validate(program)
}

func TestValidateProgram(t *testing.T) {
	src := `transaction "a" { require exists "x" write "x" = "y" assert contains "x" "y" } transaction "b" {}`
	program, err := validateSource(t, src)
	if err != nil {
		t.Fatal(err)
	}
	if got := strings.Join(Names(program), ","); got != "a,b" {
		t.Fatalf("names = %q", got)
	}
	if len(program.Transactions[0].Requires) != 1 || len(program.Transactions[0].Operations) != 1 || len(program.Transactions[0].Assertions) != 1 {
		t.Fatalf("phases = %#v", program.Transactions[0])
	}
}

func TestValidateErrors(t *testing.T) {
	digest := "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
	tests := []struct{ name, src, code string }{
		{"duplicate", `transaction "x" {} transaction "x" {}`, diag.Semantic},
		{"empty name", `transaction " " {}`, diag.Semantic},
		{"require after mutation", `transaction "x" { mkdir "a" require exists "a" }`, diag.PhaseOrder},
		{"mutation after assert", `transaction "x" { assert exists "a" mkdir "a" }`, diag.PhaseOrder},
		{"empty path", `transaction "x" { mkdir "" }`, diag.Semantic},
		{"empty replace", `transaction "x" { replace "a" "" -> "b" }`, diag.Semantic},
		{"empty contains", `transaction "x" { require contains "a" "" }`, diag.Semantic},
		{"short hash", `transaction "x" { require sha256 "a" = "abc" }`, diag.Semantic},
		{"bad hash", `transaction "x" { require sha256 "a" = "` + strings.Repeat("z", 64) + `" }`, diag.Semantic},
		{"valid hash", `transaction "x" { require sha256 "a" = "` + strings.ToUpper(digest) + `" }`, ""},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			_, err := validateSource(t, tt.src)
			if tt.code == "" {
				if err != nil {
					t.Fatal(err)
				}
				return
			}
			if err == nil || err.Code != tt.code {
				t.Fatalf("error = %#v", err)
			}
		})
	}
}
