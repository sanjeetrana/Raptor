//go:build unix

package fsop

import (
	"errors"
	"path/filepath"
	"syscall"
	"testing"

	"github.com/daniel-oluwadunsin/undolang/internal/lang/ast"
)

func TestRejectsFIFO(t *testing.T) {
	f := newFixture(t)
	if err := syscall.Mkfifo(filepath.Join(f.root, "fifo"), 0o600); err != nil {
		t.Skipf("mkfifo unavailable: %v", err)
	}
	_, err := f.engine.Prepare("fifo", ast.Statement{Kind: ast.Delete, Path: "fifo"})
	var opErr *Error
	if !errors.As(err, &opErr) || opErr.Code != UnsupportedType {
		t.Fatalf("FIFO error = %v", err)
	}
}
