package lexer

import (
	"fmt"
	"strconv"
	"strings"
	"unicode/utf8"

	"github.com/daniel-oluwadunsin/undolang/internal/lang/diag"
	"github.com/daniel-oluwadunsin/undolang/internal/lang/token"
)

type scanner struct {
	src          []byte
	offset       int
	line, column int
}

func Lex(src []byte) ([]token.Token, *diag.Error) {
	if !utf8.Valid(src) {
		pos := firstInvalid(src)
		p := positionAt(src, pos)
		return nil, diag.New(diag.UTF8, "source is not valid UTF-8", token.Span{Start: p, End: p})
	}
	s := scanner{src: src, line: 1, column: 1}
	var out []token.Token
	for {
		s.skipSpaceAndComments()
		start := s.position()
		if s.offset == len(s.src) {
			out = append(out, token.Token{Kind: token.EOF, Span: token.Span{Start: start, End: start}})
			return out, nil
		}
		b := s.src[s.offset]
		switch b {
		case '{', '}', '=':
			s.advance()
			kind := token.LBrace
			if b == '}' {
				kind = token.RBrace
			} else if b == '=' {
				kind = token.Equal
			}
			out = append(out, s.simple(kind, start))
		case '-':
			s.advance()
			if s.offset >= len(s.src) || s.src[s.offset] != '>' {
				return nil, diag.New(diag.Lex, "expected '>' after '-'", token.Span{Start: start, End: s.position()})
			}
			s.advance()
			out = append(out, s.simple(token.Arrow, start))
		case '"':
			t, err := s.quoted(start)
			if err != nil {
				return nil, err
			}
			out = append(out, t)
		case '`':
			t, err := s.raw(start)
			if err != nil {
				return nil, err
			}
			out = append(out, t)
		default:
			if isIdentStart(b) {
				out = append(out, s.identifier(start))
				continue
			}
			_, size := utf8.DecodeRune(s.src[s.offset:])
			s.advance()
			return nil, diag.New(diag.Lex, fmt.Sprintf("unexpected character %q", string(s.src[s.offset-size:s.offset])), token.Span{Start: start, End: s.position()})
		}
	}
}

func firstInvalid(src []byte) int {
	for i := 0; i < len(src); {
		_, n := utf8.DecodeRune(src[i:])
		if n == 1 && src[i] >= utf8.RuneSelf {
			return i
		}
		i += n
	}
	return len(src)
}

func positionAt(src []byte, end int) token.Position {
	line, col := 1, 1
	for i := 0; i < end; {
		if src[i] == '\r' && i+1 < end && src[i+1] == '\n' {
			i += 2
			line, col = line+1, 1
			continue
		}
		r, n := utf8.DecodeRune(src[i:])
		i += n
		if r == '\n' || r == '\r' {
			line, col = line+1, 1
		} else {
			col++
		}
	}
	return token.Position{Offset: end, Line: line, Column: col}
}

func (s *scanner) position() token.Position {
	return token.Position{Offset: s.offset, Line: s.line, Column: s.column}
}

func (s *scanner) advance() rune {
	if s.src[s.offset] == '\r' {
		s.offset++
		if s.offset < len(s.src) && s.src[s.offset] == '\n' {
			s.offset++
		}
		s.line++
		s.column = 1
		return '\n'
	}
	r, n := utf8.DecodeRune(s.src[s.offset:])
	s.offset += n
	if r == '\n' {
		s.line++
		s.column = 1
	} else {
		s.column++
	}
	return r
}

func (s *scanner) skipSpaceAndComments() {
	for s.offset < len(s.src) {
		switch s.src[s.offset] {
		case ' ', '\t', '\n', '\r':
			s.advance()
		case '#':
			for s.offset < len(s.src) && s.src[s.offset] != '\n' && s.src[s.offset] != '\r' {
				s.advance()
			}
		default:
			return
		}
	}
}

func (s *scanner) simple(kind token.Kind, start token.Position) token.Token {
	return token.Token{Kind: kind, Lexeme: string(s.src[start.Offset:s.offset]), Span: token.Span{Start: start, End: s.position()}}
}

func isIdentStart(b byte) bool { return b == '_' || b >= 'a' && b <= 'z' || b >= 'A' && b <= 'Z' }
func isIdent(b byte) bool      { return isIdentStart(b) || b >= '0' && b <= '9' }

func (s *scanner) identifier(start token.Position) token.Token {
	for s.offset < len(s.src) && isIdent(s.src[s.offset]) {
		s.advance()
	}
	lexeme := string(s.src[start.Offset:s.offset])
	kind := token.Keyword(lexeme)
	if kind == token.Illegal {
		kind = token.Identifier
	}
	return token.Token{Kind: kind, Lexeme: lexeme, Value: lexeme, Span: token.Span{Start: start, End: s.position()}}
}

func (s *scanner) quoted(start token.Position) (token.Token, *diag.Error) {
	s.advance()
	var value strings.Builder
	for s.offset < len(s.src) {
		if s.src[s.offset] == '"' {
			s.advance()
			return token.Token{Kind: token.String, Lexeme: string(s.src[start.Offset:s.offset]), Value: value.String(), Span: token.Span{Start: start, End: s.position()}}, nil
		}
		if s.src[s.offset] == '\n' || s.src[s.offset] == '\r' {
			return token.Token{}, diag.New(diag.Lex, "newline in quoted string; use an escape", token.Span{Start: start, End: s.position()})
		}
		if s.src[s.offset] != '\\' {
			value.WriteRune(s.advance())
			continue
		}
		escapeStart := s.position()
		s.advance()
		if s.offset == len(s.src) {
			break
		}
		esc := s.advance()
		switch esc {
		case '\\', '"':
			value.WriteRune(esc)
		case 'n':
			value.WriteByte('\n')
		case 'r':
			value.WriteByte('\r')
		case 't':
			value.WriteByte('\t')
		case 'u':
			if s.offset+4 > len(s.src) {
				return token.Token{}, diag.New(diag.Lex, "incomplete Unicode escape", token.Span{Start: escapeStart, End: s.position()})
			}
			hex := string(s.src[s.offset : s.offset+4])
			v, err := strconv.ParseUint(hex, 16, 16)
			if err != nil {
				return token.Token{}, diag.New(diag.Lex, "invalid Unicode escape", token.Span{Start: escapeStart, End: s.position()})
			}
			for range 4 {
				s.advance()
			}
			r := rune(v)
			if r >= 0xD800 && r <= 0xDFFF {
				return token.Token{}, diag.New(diag.Lex, "Unicode escape is a surrogate code point", token.Span{Start: escapeStart, End: s.position()})
			}
			value.WriteRune(r)
		default:
			return token.Token{}, diag.New(diag.Lex, fmt.Sprintf("unknown escape \\%c", esc), token.Span{Start: escapeStart, End: s.position()})
		}
	}
	return token.Token{}, diag.New(diag.Lex, "unterminated quoted string", token.Span{Start: start, End: s.position()})
}

func (s *scanner) raw(start token.Position) (token.Token, *diag.Error) {
	s.advance()
	contentStart := s.offset
	var value strings.Builder
	segmentStart := contentStart
	for s.offset < len(s.src) {
		if s.src[s.offset] == '`' {
			value.Write(s.src[segmentStart:s.offset])
			s.advance()
			return token.Token{Kind: token.String, Lexeme: string(s.src[start.Offset:s.offset]), Value: value.String(), Span: token.Span{Start: start, End: s.position()}}, nil
		}
		if s.src[s.offset] == '\r' {
			value.Write(s.src[segmentStart:s.offset])
			s.advance()
			value.WriteByte('\n')
			segmentStart = s.offset
			continue
		}
		s.advance()
	}
	return token.Token{}, diag.New(diag.Lex, "unterminated raw string", token.Span{Start: start, End: s.position()})
}
