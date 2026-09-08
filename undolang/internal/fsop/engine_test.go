package fsop

import (
	json "encoding/json/v2"
	"errors"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"

	"github.com/daniel-oluwadunsin/undolang/internal/lang/ast"
	"github.com/daniel-oluwadunsin/undolang/internal/pathcap"
)

type fixture struct {
	t      *testing.T
	root   string
	other  string
	caps   *pathcap.Set
	engine *Engine
}

func newFixture(t *testing.T) *fixture {
	t.Helper()
	base := t.TempDir()
	root := filepath.Join(base, "root")
	other := filepath.Join(base, "other")
	backup := filepath.Join(base, "backup")
	for _, dir := range []string{root, other} {
		if err := os.Mkdir(dir, 0o755); err != nil {
			t.Fatal(err)
		}
	}
	caps, err := pathcap.Open(root, []string{other})
	if err != nil {
		t.Fatal(err)
	}
	engine, err := Open(caps, backup)
	if err != nil {
		caps.Close()
		t.Fatal(err)
	}
	f := &fixture{t: t, root: root, other: other, caps: caps, engine: engine}
	t.Cleanup(func() {
		if err := errors.Join(engine.Close(), caps.Close()); err != nil {
			t.Errorf("close: %v", err)
		}
	})
	return f
}

func (f *fixture) write(rel, value string, mode os.FileMode) {
	f.t.Helper()
	path := filepath.Join(f.root, rel)
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		f.t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(value), mode); err != nil {
		f.t.Fatal(err)
	}
}

func mustContent(t *testing.T, path, want string) {
	t.Helper()
	got, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != want {
		t.Fatalf("content %q, want %q", got, want)
	}
}

func execute(t *testing.T, e *Engine, id string, op ast.Statement) Prepared {
	t.Helper()
	p, err := e.Prepare(id, op)
	if err != nil {
		t.Fatalf("prepare: %v", err)
	}
	if err = e.Apply(&p, op); err != nil {
		t.Fatalf("apply: %v", err)
	}
	if err = e.Verify(&p, op); err != nil {
		t.Fatalf("verify: %v", err)
	}
	return p
}

func TestMkdirApplyVerifyUndo(t *testing.T) {
	f := newFixture(t)
	op := ast.Statement{Kind: ast.Mkdir, Path: "a/b/c"}
	p := execute(t, f.engine, "mkdir", op)
	if len(p.Created) != 3 {
		t.Fatalf("created %d directories, want 3", len(p.Created))
	}
	if err := f.engine.Undo(&p); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(f.root, "a")); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("mkdir rollback left path: %v", err)
	}
}

func TestCopyFileAndOverwriteRollback(t *testing.T) {
	f := newFixture(t)
	f.write("source.txt", "new data", 0o640)
	f.write("target.txt", "old data", 0o600)
	op := ast.Statement{Kind: ast.Copy, Source: "source.txt", Target: "target.txt", Overwrite: true}
	p := execute(t, f.engine, "copy", op)
	mustContent(t, filepath.Join(f.root, "target.txt"), "new data")
	if err := f.engine.Undo(&p); err != nil {
		t.Fatal(err)
	}
	mustContent(t, filepath.Join(f.root, "target.txt"), "old data")
	if got, err := os.Stat(filepath.Join(f.root, "target.txt")); err != nil || got.Mode().Perm() != 0o600 {
		t.Fatalf("restored mode = %v, err %v", got, err)
	}
}

func TestCopyDirectoryTreeAndUndo(t *testing.T) {
	f := newFixture(t)
	if err := os.MkdirAll(filepath.Join(f.root, "tree", "empty"), 0o750); err != nil {
		t.Fatal(err)
	}
	f.write("tree/nested/file", strings.Repeat("x", 256<<10), 0o640)
	op := ast.Statement{Kind: ast.Copy, Source: "tree", Target: "clone"}
	p := execute(t, f.engine, "copy-tree", op)
	mustContent(t, filepath.Join(f.root, "clone", "nested", "file"), strings.Repeat("x", 256<<10))
	if info, err := os.Stat(filepath.Join(f.root, "clone", "empty")); err != nil || !info.IsDir() {
		t.Fatalf("empty directory was not copied: %v", err)
	}
	if err := f.engine.Undo(&p); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(f.root, "clone")); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("copy rollback left target: %v", err)
	}
}

func TestOverwriteReplacesCompleteEntryAndRestoresIt(t *testing.T) {
	f := newFixture(t)
	f.write("source", "file", 0o640)
	f.write("target/nested/old", "tree", 0o600)
	op := ast.Statement{Kind: ast.Copy, Source: "source", Target: "target", Overwrite: true}
	p := execute(t, f.engine, "replace-entry", op)
	mustContent(t, filepath.Join(f.root, "target"), "file")
	if err := f.engine.Undo(&p); err != nil {
		t.Fatal(err)
	}
	mustContent(t, filepath.Join(f.root, "target", "nested", "old"), "tree")
}

func TestCopyRejectsSymlinkAndDescendant(t *testing.T) {
	f := newFixture(t)
	f.write("real", "data", 0o644)
	if err := os.Symlink("real", filepath.Join(f.root, "link")); err != nil {
		t.Skipf("symlinks unavailable: %v", err)
	}
	_, err := f.engine.Prepare("symlink-copy", ast.Statement{Kind: ast.Copy, Source: "link", Target: "copy"})
	var opErr *Error
	if !errors.As(err, &opErr) || opErr.Code != UnsupportedSymlinkCopy {
		t.Fatalf("symlink copy error = %v", err)
	}
	if err := os.Mkdir(filepath.Join(f.root, "dir"), 0o755); err != nil {
		t.Fatal(err)
	}
	_, err = f.engine.Prepare("descendant", ast.Statement{Kind: ast.Copy, Source: "dir", Target: "dir/child"})
	if !errors.As(err, &opErr) || opErr.Code != Conflict {
		t.Fatalf("descendant copy error = %v", err)
	}
}

func TestWriteCreateOverwriteAndUndo(t *testing.T) {
	f := newFixture(t)
	create := ast.Statement{Kind: ast.Write, Path: "created", Content: "hello"}
	p := execute(t, f.engine, "write-create", create)
	mustContent(t, filepath.Join(f.root, "created"), "hello")
	if err := f.engine.Undo(&p); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(f.root, "created")); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("write rollback left target: %v", err)
	}

	f.write("existing", "before", 0o600)
	overwrite := ast.Statement{Kind: ast.Write, Path: "existing", Content: "after"}
	p = execute(t, f.engine, "write-overwrite", overwrite)
	if err := f.engine.Undo(&p); err != nil {
		t.Fatal(err)
	}
	mustContent(t, filepath.Join(f.root, "existing"), "before")
}

func TestStreamingReplaceBoundariesNoopAndUndo(t *testing.T) {
	f := newFixture(t)
	original := strings.Repeat("a", 64<<10-2) + "needle" + strings.Repeat("b", 64<<10) + "needle"
	f.write("replace", original, 0o640)
	op := ast.Statement{Kind: ast.Replace, Path: "replace", Old: "needle", New: "replacement"}
	p := execute(t, f.engine, "replace", op)
	if p.MatchCount != 2 {
		t.Fatalf("match count %d, want 2", p.MatchCount)
	}
	if err := f.engine.Undo(&p); err != nil {
		t.Fatal(err)
	}
	mustContent(t, filepath.Join(f.root, "replace"), original)

	noop := ast.Statement{Kind: ast.Replace, Path: "replace", Old: "needle", New: "needle"}
	fixedTime := time.Unix(1_700_000_000, 0)
	if err := os.Chtimes(filepath.Join(f.root, "replace"), fixedTime, fixedTime); err != nil {
		t.Fatal(err)
	}
	p = execute(t, f.engine, "replace-noop", noop)
	if p.MatchCount != 2 {
		t.Fatalf("no-op match count %d, want 2", p.MatchCount)
	}
	if info, err := os.Stat(filepath.Join(f.root, "replace")); err != nil || !info.ModTime().Equal(fixedTime) {
		t.Fatalf("no-op replace mutated file timestamp: %v, %v", info, err)
	}
	if err := f.engine.Undo(&p); err != nil {
		t.Fatal(err)
	}

	missing := ast.Statement{Kind: ast.Replace, Path: "replace", Old: "absent", New: "x"}
	_, err := f.engine.Prepare("replace-missing", missing)
	var opErr *Error
	if !errors.As(err, &opErr) || opErr.Code != ReplacePatternNotFound {
		t.Fatalf("missing-pattern error = %v", err)
	}
	mustContent(t, filepath.Join(f.root, "replace"), original)
}

func TestDeleteFileDirectoryAndSymlinkRollback(t *testing.T) {
	tests := []struct {
		name string
		make func(*fixture)
		path string
	}{
		{"file", func(f *fixture) { f.write("victim", "data", 0o600) }, "victim"},
		{"directory", func(f *fixture) { f.write("victim/child", "data", 0o640) }, "victim"},
		{"symlink", func(f *fixture) {
			f.write("real", "data", 0o644)
			if err := os.Symlink("real", filepath.Join(f.root, "victim")); err != nil {
				f.t.Skipf("symlinks unavailable: %v", err)
			}
		}, "victim"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			f := newFixture(t)
			tt.make(f)
			op := ast.Statement{Kind: ast.Delete, Path: tt.path}
			p := execute(t, f.engine, "delete", op)
			if err := f.engine.Undo(&p); err != nil {
				t.Fatal(err)
			}
			info, err := os.Lstat(filepath.Join(f.root, tt.path))
			if err != nil {
				t.Fatal(err)
			}
			if tt.name == "symlink" && info.Mode()&os.ModeSymlink == 0 {
				t.Fatal("symlink identity was not restored")
			}
		})
	}
}

func TestAbsoluteDeleteRemovesSymlinkEntryNotItsTarget(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("symlink creation commonly requires privileges on Windows")
	}
	f := newFixture(t)
	external := filepath.Join(f.other, "external")
	if err := os.WriteFile(external, []byte("safe"), 0o600); err != nil {
		t.Fatal(err)
	}
	link := filepath.Join(f.root, "absolute-link")
	if err := os.Symlink(external, link); err != nil {
		t.Fatal(err)
	}
	op := ast.Statement{Kind: ast.Delete, Path: link}
	prepared := execute(t, f.engine, "absolute-symlink", op)
	mustContent(t, external, "safe")
	if _, err := os.Lstat(link); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("symlink entry remains: %v", err)
	}
	if err := f.engine.Undo(&prepared); err != nil {
		t.Fatal(err)
	}
	if info, err := os.Lstat(link); err != nil || info.Mode()&os.ModeSymlink == 0 {
		t.Fatalf("symlink entry was not restored: %v", err)
	}
}

func TestDeleteSymlinkToReservedStateDoesNotTouchState(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("symlink creation commonly requires privileges on Windows")
	}
	f := newFixture(t)
	stateDir := filepath.Join(f.root, ".undo")
	if err := os.Mkdir(stateDir, 0o700); err != nil {
		t.Fatal(err)
	}
	secret := filepath.Join(stateDir, "secret")
	if err := os.WriteFile(secret, []byte("protected"), 0o600); err != nil {
		t.Fatal(err)
	}
	link := filepath.Join(f.root, "state-link")
	if err := os.Symlink(filepath.Join(".undo", "secret"), link); err != nil {
		t.Fatal(err)
	}
	op := ast.Statement{Kind: ast.Delete, Path: "state-link"}
	prepared := execute(t, f.engine, "state-symlink", op)
	mustContent(t, secret, "protected")
	if err := f.engine.Undo(&prepared); err != nil {
		t.Fatal(err)
	}
	mustContent(t, secret, "protected")
}

func TestMoveRenameOverwriteAndRollback(t *testing.T) {
	f := newFixture(t)
	f.write("source", "source data", 0o640)
	f.write("target", "target data", 0o600)
	op := ast.Statement{Kind: ast.Move, Source: "source", Target: "target", Overwrite: true}
	p := execute(t, f.engine, "move", op)
	mustContent(t, filepath.Join(f.root, "target"), "source data")
	if _, err := os.Stat(filepath.Join(f.root, "source")); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("move left source: %v", err)
	}
	if err := f.engine.Undo(&p); err != nil {
		t.Fatal(err)
	}
	mustContent(t, filepath.Join(f.root, "source"), "source data")
	mustContent(t, filepath.Join(f.root, "target"), "target data")
}

func TestMoveSymlinkEntryAndRollback(t *testing.T) {
	f := newFixture(t)
	f.write("real", "data", 0o644)
	if err := os.Symlink("real", filepath.Join(f.root, "source-link")); err != nil {
		t.Skipf("symlinks unavailable: %v", err)
	}
	op := ast.Statement{Kind: ast.Move, Source: "source-link", Target: "target-link"}
	p := execute(t, f.engine, "move-link", op)
	if info, err := os.Lstat(filepath.Join(f.root, "target-link")); err != nil || info.Mode()&os.ModeSymlink == 0 {
		t.Fatalf("move did not preserve symlink entry: %v", err)
	}
	if err := f.engine.Undo(&p); err != nil {
		t.Fatal(err)
	}
	if info, err := os.Lstat(filepath.Join(f.root, "source-link")); err != nil || info.Mode()&os.ModeSymlink == 0 {
		t.Fatalf("rollback did not restore symlink entry: %v", err)
	}
}

func TestCrossCapabilityMoveAndRollback(t *testing.T) {
	f := newFixture(t)
	f.write("source", strings.Repeat("cross", 10000), 0o640)
	target := filepath.Join(f.other, "target")
	op := ast.Statement{Kind: ast.Move, Source: "source", Target: target}
	p := execute(t, f.engine, "cross-move", op)
	mustContent(t, target, strings.Repeat("cross", 10000))
	if err := f.engine.Undo(&p); err != nil {
		t.Fatal(err)
	}
	mustContent(t, filepath.Join(f.root, "source"), strings.Repeat("cross", 10000))
	if _, err := os.Stat(target); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("cross-move rollback left target: %v", err)
	}
}

func TestMutationRejectsSymlinkParent(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("symlink creation commonly requires privileges on Windows")
	}
	f := newFixture(t)
	if err := os.Mkdir(filepath.Join(f.root, "real"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink("real", filepath.Join(f.root, "alias")); err != nil {
		t.Skipf("symlinks unavailable: %v", err)
	}
	_, err := f.engine.Prepare("symlink-parent", ast.Statement{Kind: ast.Write, Path: "alias/file", Content: "x"})
	if err == nil {
		t.Fatal("expected symlink-parent rejection")
	}
}

func TestParentSymlinkSwapAfterPrepareCannotEscapeRoot(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("symlink creation commonly requires privileges on Windows")
	}
	f := newFixture(t)
	parent := filepath.Join(f.root, "parent")
	if err := os.Mkdir(parent, 0o755); err != nil {
		t.Fatal(err)
	}
	op := ast.Statement{Kind: ast.Write, Path: "parent/file", Content: "unsafe"}
	prepared, err := f.engine.Prepare("parent-swap", op)
	if err != nil {
		t.Fatal(err)
	}
	if err = os.Remove(parent); err != nil {
		t.Fatal(err)
	}
	if err = os.Symlink(f.other, parent); err != nil {
		t.Fatal(err)
	}
	if err = f.engine.Apply(&prepared, op); err == nil {
		t.Fatal("mutation followed a swapped symlink parent")
	}
	if _, err = os.Stat(filepath.Join(f.other, "file")); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("mutation escaped the root: %v", err)
	}
}

func TestHardLinkContentsRestoreButIdentityIsOutsideGuarantee(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("hard-link behavior is documented from the tested Unix host")
	}
	f := newFixture(t)
	f.write("original", "before", 0o600)
	if err := os.Link(filepath.Join(f.root, "original"), filepath.Join(f.root, "linked")); err != nil {
		t.Skipf("hard links unavailable: %v", err)
	}
	op := ast.Statement{Kind: ast.Write, Path: "linked", Content: "after"}
	prepared := execute(t, f.engine, "hard-link", op)
	if err := f.engine.Undo(&prepared); err != nil {
		t.Fatal(err)
	}
	mustContent(t, filepath.Join(f.root, "original"), "before")
	mustContent(t, filepath.Join(f.root, "linked"), "before")
	original, _ := os.Stat(filepath.Join(f.root, "original"))
	linked, _ := os.Stat(filepath.Join(f.root, "linked"))
	if os.SameFile(original, linked) {
		t.Fatal("test expected the documented hard-link topology limitation")
	}
}

func TestRollbackFailsClosedOnExternalChange(t *testing.T) {
	f := newFixture(t)
	op := ast.Statement{Kind: ast.Write, Path: "file", Content: "applied"}
	p := execute(t, f.engine, "external-change", op)
	if err := os.WriteFile(filepath.Join(f.root, "file"), []byte("external"), 0o644); err != nil {
		t.Fatal(err)
	}
	var opErr *Error
	if err := f.engine.Undo(&p); !errors.As(err, &opErr) || opErr.Code != VerificationFailed {
		t.Fatalf("undo error = %v", err)
	}
	mustContent(t, filepath.Join(f.root, "file"), "external")
}

func TestPreparedMetadataCannotApplyDifferentOperation(t *testing.T) {
	f := newFixture(t)
	op := ast.Statement{Kind: ast.Write, Path: "file", Content: "approved"}
	p, err := f.engine.Prepare("bound", op)
	if err != nil {
		t.Fatal(err)
	}
	err = f.engine.Apply(&p, ast.Statement{Kind: ast.Write, Path: "file", Content: "different"})
	var opErr *Error
	if !errors.As(err, &opErr) || opErr.Code != Conflict {
		t.Fatalf("mismatched operation error = %v", err)
	}
	if _, err := os.Stat(filepath.Join(f.root, "file")); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("mismatched operation mutated target: %v", err)
	}
}

func TestPreparedMetadataJSONRoundTrip(t *testing.T) {
	f := newFixture(t)
	f.write("file", "before", 0o600)
	op := ast.Statement{Kind: ast.Write, Path: "file", Content: "after"}
	p, err := f.engine.Prepare("serializable", op)
	if err != nil {
		t.Fatal(err)
	}
	data, err := json.Marshal(p)
	if err != nil {
		t.Fatal(err)
	}
	var decoded Prepared
	if err = json.Unmarshal(data, &decoded); err != nil {
		t.Fatal(err)
	}
	if decoded.OperationHash != p.OperationHash || decoded.PriorTarget.Digest != p.PriorTarget.Digest {
		t.Fatalf("prepared metadata did not survive JSON round trip: %#v", decoded)
	}
}
