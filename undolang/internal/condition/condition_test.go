package condition

import (
	"crypto/sha256"
	"encoding/hex"
	"os"
	"path/filepath"
	"runtime"
	"testing"

	"github.com/daniel-oluwadunsin/undolang/internal/lang/ast"
	"github.com/daniel-oluwadunsin/undolang/internal/pathcap"
)

func TestConditions(t *testing.T) {
	root := t.TempDir()
	data := []byte("prefix needle suffix")
	if err := os.WriteFile(filepath.Join(root, "file"), data, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(filepath.Join(root, "dir"), 0o700); err != nil {
		t.Fatal(err)
	}
	set, err := pathcap.Open(root, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer set.Close()
	sum := sha256.Sum256(data)
	tests := []struct {
		cond ast.Condition
		want bool
	}{
		{ast.Condition{Kind: ast.Exists, Path: "file"}, true},
		{ast.Condition{Kind: ast.NotExists, Path: "missing"}, true},
		{ast.Condition{Kind: ast.IsFile, Path: "file"}, true},
		{ast.Condition{Kind: ast.IsDir, Path: "dir"}, true},
		{ast.Condition{Kind: ast.Contains, Path: "file", Value: "needle"}, true},
		{ast.Condition{Kind: ast.Contains, Path: "file", Value: "absent"}, false},
		{ast.Condition{Kind: ast.SHA256, Path: "file", Value: hex.EncodeToString(sum[:])}, true},
	}
	for _, tt := range tests {
		result, err := Evaluate(tt.cond, set)
		if err != nil || result.Value != tt.want {
			t.Fatalf("%s: result=%#v err=%v", tt.cond.Kind, result, err)
		}
	}
}

func TestBrokenSymlinkExistsButIsNotFile(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("symlink privileges")
	}
	root := t.TempDir()
	if err := os.Symlink("missing", filepath.Join(root, "link")); err != nil {
		t.Fatal(err)
	}
	set, err := pathcap.Open(root, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer set.Close()
	exists, err := Evaluate(ast.Condition{Kind: ast.Exists, Path: "link"}, set)
	if err != nil || !exists.Value {
		t.Fatalf("exists=%#v err=%v", exists, err)
	}
	isFile, err := Evaluate(ast.Condition{Kind: ast.IsFile, Path: "link"}, set)
	if err != nil || isFile.Value {
		t.Fatalf("is_file=%#v err=%v", isFile, err)
	}
}

func TestContentConditionsRefuseSymlinkTargets(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("symlink privileges")
	}
	root := t.TempDir()
	if err := os.WriteFile(filepath.Join(root, "target"), []byte("private"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink("target", filepath.Join(root, "link")); err != nil {
		t.Fatal(err)
	}
	set, err := pathcap.Open(root, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer set.Close()
	for _, kind := range []ast.ConditionKind{ast.Contains, ast.SHA256} {
		if _, err = Evaluate(ast.Condition{Kind: kind, Path: "link", Value: "private"}, set); err == nil {
			t.Fatalf("%s followed a symlink target", kind)
		}
	}
}
