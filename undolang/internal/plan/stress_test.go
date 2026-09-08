package plan

import (
	"fmt"
	"os"
	"path/filepath"
	"testing"
)

func TestStressPlan100KEntryTree(t *testing.T) {
	if os.Getenv("UNDOLANG_LARGE_TREE") != "1" {
		t.Skip("set UNDOLANG_LARGE_TREE=1 to run the 100k-entry planner stress test")
	}
	root := t.TempDir()
	tree := filepath.Join(root, "tree")
	if err := os.Mkdir(tree, 0o700); err != nil {
		t.Fatal(err)
	}
	for index := range 100_000 {
		path := filepath.Join(tree, fmt.Sprintf("entry-%06d", index))
		file, err := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600)
		if err != nil {
			t.Fatal(err)
		}
		if err = file.Close(); err != nil {
			t.Fatal(err)
		}
	}
	result, err := buildSource(t, root, `transaction "large" { copy "tree" -> "copy" }`, "")
	if err != nil {
		t.Fatal(err)
	}
	op := result.Transactions[0].Plan.Operations[0]
	if op.EntryCount != 100_001 || op.Bytes != 0 {
		t.Fatalf("entry_count=%d bytes=%d", op.EntryCount, op.Bytes)
	}
}
