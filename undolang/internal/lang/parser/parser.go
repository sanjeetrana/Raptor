package parser

import (
	"fmt"

	"github.com/daniel-oluwadunsin/undolang/internal/lang/ast"
	"github.com/daniel-oluwadunsin/undolang/internal/lang/diag"
	"github.com/daniel-oluwadunsin/undolang/internal/lang/token"
)

type parser struct {
	tokens []token.Token
	pos    int
}

func Parse(tokens []token.Token) (ast.Program, *diag.Error) {
	p := parser{tokens: tokens}
	if len(tokens) == 0 {
		return ast.Program{}, diag.New(diag.Syntax, "empty token stream", token.Span{})
	}
	start := p.current().Span.Start
	var txs []ast.Transaction
	for p.current().Kind != token.EOF {
		if p.current().Kind != token.Transaction {
			return ast.Program{}, p.unexpectedInstruction("expected transaction declaration")
		}
		tx, err := p.transaction()
		if err != nil {
			return ast.Program{}, err
		}
		txs = append(txs, tx)
	}
	if len(txs) == 0 {
		return ast.Program{}, diag.New(diag.Syntax, "program must contain at least one transaction", p.current().Span)
	}
	return ast.Program{Transactions: txs, Span: token.Span{Start: start, End: p.current().Span.End}}, nil
}

func (p *parser) transaction() (ast.Transaction, *diag.Error) {
	start := p.take().Span.Start
	name, err := p.expect(token.String, "expected transaction name string")
	if err != nil {
		return ast.Transaction{}, err
	}
	if _, err = p.expect(token.LBrace, "expected '{' after transaction name"); err != nil {
		return ast.Transaction{}, err
	}
	var body []ast.Statement
	for p.current().Kind != token.RBrace {
		if p.current().Kind == token.EOF {
			return ast.Transaction{}, diag.New(diag.Syntax, "unterminated transaction body", p.current().Span)
		}
		stmt, e := p.statement()
		if e != nil {
			return ast.Transaction{}, e
		}
		body = append(body, stmt)
	}
	end := p.take().Span.End
	return ast.Transaction{Name: name.Value, Statements: body, Span: token.Span{Start: start, End: end}}, nil
}

func (p *parser) statement() (ast.Statement, *diag.Error) {
	start := p.current().Span.Start
	switch p.current().Kind {
	case token.Require, token.Assert:
		kind := ast.Require
		if p.take().Kind == token.Assert {
			kind = ast.Assert
		}
		cond, err := p.condition()
		if err != nil {
			return ast.Statement{}, err
		}
		return ast.Statement{Kind: kind, Condition: &cond, Span: token.Span{Start: start, End: cond.Span.End}}, nil
	case token.Mkdir, token.Delete:
		kind := ast.Mkdir
		if p.take().Kind == token.Delete {
			kind = ast.Delete
		}
		path, err := p.expect(token.String, "expected path string")
		if err != nil {
			return ast.Statement{}, err
		}
		return ast.Statement{Kind: kind, Path: path.Value, Span: token.Span{Start: start, End: path.Span.End}}, nil
	case token.Copy, token.Move:
		kind := ast.Copy
		if p.take().Kind == token.Move {
			kind = ast.Move
		}
		source, err := p.expect(token.String, "expected source path")
		if err != nil {
			return ast.Statement{}, err
		}
		if _, err = p.expect(token.Arrow, "expected '->'"); err != nil {
			return ast.Statement{}, err
		}
		target, err := p.expect(token.String, "expected destination path")
		if err != nil {
			return ast.Statement{}, err
		}
		overwrite := false
		end := target.Span.End
		if p.current().Kind == token.Overwrite {
			end = p.take().Span.End
			overwrite = true
		}
		return ast.Statement{Kind: kind, Source: source.Value, Target: target.Value, Overwrite: overwrite, Span: token.Span{Start: start, End: end}}, nil
	case token.Write:
		p.take()
		path, err := p.expect(token.String, "expected path string")
		if err != nil {
			return ast.Statement{}, err
		}
		if _, err = p.expect(token.Equal, "expected '='"); err != nil {
			return ast.Statement{}, err
		}
		content, err := p.expect(token.String, "expected content string")
		if err != nil {
			return ast.Statement{}, err
		}
		return ast.Statement{Kind: ast.Write, Path: path.Value, Content: content.Value, Span: token.Span{Start: start, End: content.Span.End}}, nil
	case token.Replace:
		p.take()
		path, err := p.expect(token.String, "expected path string")
		if err != nil {
			return ast.Statement{}, err
		}
		old, err := p.expect(token.String, "expected old literal")
		if err != nil {
			return ast.Statement{}, err
		}
		if _, err = p.expect(token.Arrow, "expected '->'"); err != nil {
			return ast.Statement{}, err
		}
		newValue, err := p.expect(token.String, "expected replacement literal")
		if err != nil {
			return ast.Statement{}, err
		}
		return ast.Statement{Kind: ast.Replace, Path: path.Value, Old: old.Value, New: newValue.Value, Span: token.Span{Start: start, End: newValue.Span.End}}, nil
	default:
		return ast.Statement{}, p.unexpectedInstruction("unknown instruction")
	}
}

func (p *parser) condition() (ast.Condition, *diag.Error) {
	start := p.current().Span.Start
	var kind ast.ConditionKind
	switch p.take().Kind {
	case token.Exists:
		kind = ast.Exists
	case token.NotExists:
		kind = ast.NotExists
	case token.IsFile:
		kind = ast.IsFile
	case token.IsDir:
		kind = ast.IsDir
	case token.Contains:
		kind = ast.Contains
	case token.SHA256:
		kind = ast.SHA256
	default:
		p.pos--
		return ast.Condition{}, p.unexpectedInstruction("unknown condition")
	}
	path, err := p.expect(token.String, "expected condition path")
	if err != nil {
		return ast.Condition{}, err
	}
	cond := ast.Condition{Kind: kind, Path: path.Value, Span: token.Span{Start: start, End: path.Span.End}}
	if kind == ast.Contains {
		value, e := p.expect(token.String, "expected contains literal")
		if e != nil {
			return ast.Condition{}, e
		}
		cond.Value, cond.Span.End = value.Value, value.Span.End
	}
	if kind == ast.SHA256 {
		if _, e := p.expect(token.Equal, "expected '=' after sha256 path"); e != nil {
			return ast.Condition{}, e
		}
		value, e := p.expect(token.String, "expected SHA-256 digest string")
		if e != nil {
			return ast.Condition{}, e
		}
		cond.Value, cond.Span.End = value.Value, value.Span.End
	}
	return cond, nil
}

func (p *parser) current() token.Token {
	if p.pos >= len(p.tokens) {
		return token.Token{Kind: token.EOF}
	}
	return p.tokens[p.pos]
}

func (p *parser) take() token.Token { t := p.current(); p.pos++; return t }

func (p *parser) expect(kind token.Kind, message string) (token.Token, *diag.Error) {
	if p.current().Kind != kind {
		return token.Token{}, diag.New(diag.Syntax, fmt.Sprintf("%s; found %s", message, p.current().Kind), p.current().Span)
	}
	return p.take(), nil
}

var instructions = []string{"require", "assert", "mkdir", "copy", "move", "write", "replace", "delete", "exists", "not_exists", "is_file", "is_dir", "contains", "sha256"}

func (p *parser) unexpectedInstruction(message string) *diag.Error {
	t := p.current()
	e := diag.New(diag.UnknownInstruction, fmt.Sprintf("%s %q", message, t.Lexeme), t.Span)
	if t.Kind == token.Identifier {
		e.Suggestion = suggestion(t.Lexeme)
	}
	return e
}

func suggestion(word string) string {
	best, bestDistance, ties := "", 3, 0
	for _, candidate := range instructions {
		d := distance(word, candidate)
		if d < bestDistance {
			best, bestDistance, ties = candidate, d, 1
		} else if d == bestDistance {
			ties++
		}
	}
	if bestDistance <= 2 && ties == 1 {
		return best
	}
	return ""
}

func distance(a, b string) int {
	prev := make([]int, len(b)+1)
	for j := range prev {
		prev[j] = j
	}
	for i := 1; i <= len(a); i++ {
		cur := make([]int, len(b)+1)
		cur[0] = i
		for j := 1; j <= len(b); j++ {
			cost := 0
			if a[i-1] != b[j-1] {
				cost = 1
			}
			cur[j] = min(cur[j-1]+1, prev[j]+1, prev[j-1]+cost)
		}
		prev = cur
	}
	return prev[len(b)]
}
