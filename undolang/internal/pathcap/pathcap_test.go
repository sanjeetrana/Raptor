package pathcap

import (
	"errors"
	"os"
	"path/filepath"
	"runtime"
	"testing"
)

func TestResolveCapabilities(t *testing.T) {
	root := t.TempDir()
	allowed := t.TempDir()
	nested := filepath.Join(allowed, "nested")
	if err := os.Mkdir(nested, 0o700); err != nil {
		t.Fatal(err)
	}
	set, err := Open(root, []string{allowed, nested})
	if err != nil {
		t.Fatal(err)
	}
	defer set.Close()
	canonicalRoot, _ := filepath.EvalSymlinks(root)
	canonicalNested, _ := filepath.EvalSymlinks(nested)

	rel, err := set.Resolve("a/b")
	if err != nil || rel.Root != canonicalRoot || rel.Relative != filepath.Join("a", "b") {
		t.Fatalf("relative = %#v, %v", rel, err)
	}
	abs, err := set.Resolve(filepath.Join(nested, "file"))
	if err != nil || abs.Root != canonicalNested || abs.Relative != "file" {
		t.Fatalf("most specific = %#v, %v", abs, err)
	}
	for _, path := range []string{"../x", filepath.Join(root, ".undo"), filepath.Join(root, ".undo", "journal")} {
		if _, err := set.Resolve(path); err == nil {
			t.Fatalf("expected rejection for %q", path)
		}
	}
	outside := filepath.Join(filepath.Dir(root), "not-allowed")
	if _, err := set.Resolve(outside); err == nil {
		t.Fatalf("expected absolute denial")
	}
}

func TestRootPreventsSymlinkEscape(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("symlink creation normally requires additional privileges")
	}
	root, outside := t.TempDir(), t.TempDir()
	if err := os.WriteFile(filepath.Join(outside, "secret"), []byte("x"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(outside, filepath.Join(root, "escape")); err != nil {
		t.Fatal(err)
	}
	set, err := Open(root, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer set.Close()
	path, err := set.Resolve(filepath.Join("escape", "secret"))
	if err == nil {
		t.Fatalf("symlink escape resolved unexpectedly: %#v", path)
	}
	forged := ResolvedPath{RootID: 0, Root: set.Primary(), Relative: filepath.Join("escape", "secret"), Absolute: filepath.Join(set.Primary(), "escape", "secret"), Original: "escape/secret"}
	if _, err = set.Stat(forged); err == nil {
		t.Fatal("os.Root followed a symlink outside its root")
	}
}

func TestOpenRejectsNonDirectory(t *testing.T) {
	path := filepath.Join(t.TempDir(), "file")
	if err := os.WriteFile(path, nil, 0o600); err != nil {
		t.Fatal(err)
	}
	_, err := Open(path, nil)
	var pathErr *Error
	if !errors.As(err, &pathErr) || pathErr.Code != Invalid {
		t.Fatalf("error = %v", err)
	}
}

func TestCapabilityRootIsCanonicalizedBeforeUse(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("symlink creation normally requires additional privileges")
	}
	parent := t.TempDir()
	realRoot := filepath.Join(parent, "real")
	alias := filepath.Join(parent, "alias")
	if err := os.Mkdir(realRoot, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(realRoot, alias); err != nil {
		t.Fatal(err)
	}
	set, err := Open(alias, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer set.Close()
	canonicalRoot, _ := filepath.EvalSymlinks(realRoot)
	if set.Primary() != canonicalRoot {
		t.Fatalf("primary=%q want canonical %q", set.Primary(), canonicalRoot)
	}
	if err := os.Remove(alias); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(t.TempDir(), alias); err != nil {
		t.Fatal(err)
	}
	resolved, err := set.Resolve("file")
	if err != nil {
		t.Fatal(err)
	}
	if resolved.Root != canonicalRoot {
		t.Fatalf("root changed after symlink retarget: %#v", resolved)
	}
}
