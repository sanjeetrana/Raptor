package fsop

import (
	"io"
	"os"
	"path/filepath"
	"testing"

	"github.com/daniel-oluwadunsin/undolang/internal/lang/ast"
)

func TestStressCopy256MiB(t *testing.T) {
	if os.Getenv("UNDOLANG_STRESS") != "1" {
		t.Skip("set UNDOLANG_STRESS=1 to run the 256 MiB filesystem stress test")
	}
	f := newFixture(t)
	file, err := os.Create(filepath.Join(f.root, "large"))
	if err != nil {
		t.Fatal(err)
	}
	if _, err = io.CopyN(file, zeroReader{}, 256<<20); err != nil {
		t.Fatal(err)
	}
	if err = file.Close(); err != nil {
		t.Fatal(err)
	}
	op := ast.Statement{Kind: ast.Copy, Source: "large", Target: "large-copy"}
	p := execute(t, f.engine, "stress-copy", op)
	if err := f.engine.Undo(&p); err != nil {
		t.Fatal(err)
	}
}

type zeroReader struct{}

func (zeroReader) Read(p []byte) (int, error) {
	clear(p)
	return len(p), nil
}
