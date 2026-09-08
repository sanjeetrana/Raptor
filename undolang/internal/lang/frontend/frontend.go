package frontend

import (
	"os"

	"github.com/daniel-oluwadunsin/undolang/internal/lang/diag"
	"github.com/daniel-oluwadunsin/undolang/internal/lang/lexer"
	"github.com/daniel-oluwadunsin/undolang/internal/lang/parser"
	"github.com/daniel-oluwadunsin/undolang/internal/lang/validate"
)

func Parse(src []byte) (validate.Program, *diag.Error) {
	tokens, err := lexer.Lex(src)
	if err != nil {
		return validate.Program{}, err
	}
	program, err := parser.Parse(tokens)
	if err != nil {
		return validate.Program{}, err
	}
	return validate.Validate(program)
}

func ParseFile(path string) (validate.Program, error) {
	src, err := os.ReadFile(path)
	if err != nil {
		return validate.Program{}, err
	}
	program, diagnostic := Parse(src)
	if diagnostic != nil {
		return validate.Program{}, diagnostic
	}
	return program, nil
}
