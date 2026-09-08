package cli

import (
	"fmt"
	"io"
)

// Exit codes are part of MiniKV's documented CLI contract (see README.md).
const (
	ExitOK       = 0
	ExitError    = 1
	ExitUsage    = 2
	ExitNotFound = 3
)

func printf(w io.Writer, format string, args ...any) {
	fmt.Fprintf(w, format, args...)
}

func println(w io.Writer, args ...any) {
	fmt.Fprintln(w, args...)
}
