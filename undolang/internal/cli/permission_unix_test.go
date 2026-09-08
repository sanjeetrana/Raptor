//go:build unix

package cli

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func TestReadOnlyRootReturnsPermissionClassWithoutTargetMutation(t *testing.T) {
	root := t.TempDir()
	script := filepath.Join(t.TempDir(), "permission.undo")
	if err := os.WriteFile(script, []byte(`transaction "permission" { write "created" = "value" }`), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(root, 0o500); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.Chmod(root, 0o700) })
	code, output, stderr := invoke("run", script, "--root", root, "--yes", "--json")
	if code == 0 {
		t.Skip("host privileges bypass directory write permission checks")
	}
	if stderr != "" {
		t.Fatalf("JSON stderr=%q", stderr)
	}
	var envelope struct {
		Error struct {
			Code string `json:"code"`
		} `json:"error"`
	}
	if err := json.Unmarshal([]byte(output), &envelope); err != nil {
		t.Fatal(err)
	}
	if envelope.Error.Code != "E_PERMISSION" {
		t.Fatalf("code=%d output=%s", code, output)
	}
	if _, err := os.Stat(filepath.Join(root, "created")); !os.IsNotExist(err) {
		t.Fatalf("permission failure mutated target: %v", err)
	}
}
