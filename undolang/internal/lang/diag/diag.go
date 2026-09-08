package diag

import (
	"fmt"

	"github.com/daniel-oluwadunsin/undolang/internal/lang/token"
)

const (
	UTF8               = "E_UTF8"
	Lex                = "E_LEX"
	Syntax             = "E_SYNTAX"
	UnknownInstruction = "E_UNKNOWN_INSTRUCTION"
	Semantic           = "E_SEMANTIC"
	PhaseOrder         = "E_PHASE_ORDER"
)

type Error struct {
	Code       string     `json:"code"`
	Message    string     `json:"message"`
	Span       token.Span `json:"span"`
	Suggestion string     `json:"suggestion,omitempty"`
}

func (e *Error) Error() string {
	if e.Suggestion != "" {
		return fmt.Sprintf("%s at %d:%d: %s; did you mean %q?", e.Code, e.Span.Start.Line, e.Span.Start.Column, e.Message, e.Suggestion)
	}
	return fmt.Sprintf("%s at %d:%d: %s", e.Code, e.Span.Start.Line, e.Span.Start.Column, e.Message)
}

func New(code, message string, span token.Span) *Error {
	return &Error{Code: code, Message: message, Span: span}
}
