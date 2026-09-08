package lexer

import (
	"testing"

	"github.com/daniel-oluwadunsin/undolang/internal/lang/diag"
	"github.com/daniel-oluwadunsin/undolang/internal/lang/token"
)

func TestLexLanguageSurface(t *testing.T) {
	src := []byte("# comment\r\ntransaction \"t\\u0065st\" { require sha256 `C:\\data\\a` = \"0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\" copy \"a\" -> \"b\" overwrite assert contains \"b\" \"x#y\" }")
	tokens, err := Lex(src)
	if err != nil {
		t.Fatal(err)
	}
	want := []token.Kind{token.Transaction, token.String, token.LBrace, token.Require, token.SHA256, token.String, token.Equal, token.String, token.Copy, token.String, token.Arrow, token.String, token.Overwrite, token.Assert, token.Contains, token.String, token.String, token.RBrace, token.EOF}
	if len(tokens) != len(want) {
		t.Fatalf("got %d tokens, want %d", len(tokens), len(want))
	}
	for i := range want {
		if tokens[i].Kind != want[i] {
			t.Fatalf("token %d: got %s want %s", i, tokens[i].Kind, want[i])
		}
	}
	if tokens[1].Value != "test" {
		t.Fatalf("decoded value %q", tokens[1].Value)
	}
	if tokens[5].Value != `C:\data\a` {
		t.Fatalf("raw path %q", tokens[5].Value)
	}
	if tokens[0].Span.Start.Line != 2 || tokens[0].Span.Start.Column != 1 {
		t.Fatalf("CRLF position: %+v", tokens[0].Span.Start)
	}
}

func TestLexEscapes(t *testing.T) {
	tokens, err := Lex([]byte(`"\\\"\n\r\t\u263A"`))
	if err != nil {
		t.Fatal(err)
	}
	if got, want := tokens[0].Value, "\\\"\n\r\t☺"; got != want {
		t.Fatalf("got %q want %q", got, want)
	}
}

func TestLexErrors(t *testing.T) {
	tests := []struct {
		name string
		src  []byte
		code string
	}{
		{"utf8", []byte{0xff}, diag.UTF8},
		{"unknown escape", []byte(`"\q"`), diag.Lex},
		{"surrogate", []byte(`"\uD800"`), diag.Lex},
		{"unterminated quote", []byte(`"x`), diag.Lex},
		{"unterminated raw", []byte("`x"), diag.Lex},
		{"bad arrow", []byte("- x"), diag.Lex},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			_, err := Lex(tt.src)
			if err == nil || err.Code != tt.code {
				t.Fatalf("error = %#v", err)
			}
		})
	}
}

func FuzzLexNeverPanics(f *testing.F) {
	for _, seed := range [][]byte{nil, []byte(`transaction "x" {}`), {0xff}, []byte("`raw`")} {
		f.Add(seed)
	}
	f.Fuzz(func(t *testing.T, src []byte) { _, _ = Lex(src) })
}
