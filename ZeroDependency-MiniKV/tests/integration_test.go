// Package tests contains black-box integration tests that build and drive
// the actual `minikv` binary as a subprocess, the way a real user (or a
// hackathon judge) would. Unit-level behavior is covered far more
// thoroughly in internal/engine; this file exists to prove the CLI wiring
// itself â€” argument parsing, exit codes, stdout/stderr â€” is correct end
// to end.
package tests

import (
	"bytes"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

// buildBinary compiles cmd/minikv once per test run and returns its path.
func buildBinary(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	binName := "minikv"
	if runtime.GOOS == "windows" {
		binName += ".exe"
	}
	binPath := filepath.Join(dir, binName)
	cmd := exec.Command("go", "build", "-o", binPath, "./../cmd/minikv")
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("build failed: %v\n%s", err, out)
	}
	return binPath
}

type result struct {
	stdout   string
	stderr   string
	exitCode int
}

func run(t *testing.T, bin, dbPath string, args ...string) result {
	t.Helper()
	full := append([]string{"--db", dbPath}, args...)
	cmd := exec.Command(bin, full...)
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	err := cmd.Run()
	code := 0
	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			code = exitErr.ExitCode()
		} else {
			t.Fatalf("failed to run %v: %v", args, err)
		}
	}
	return result{stdout: stdout.String(), stderr: stderr.String(), exitCode: code}
}

func TestCLIEndToEnd(t *testing.T) {
	bin := buildBinary(t)
	dbPath := filepath.Join(t.TempDir(), "minikv.db")

	if r := run(t, bin, dbPath, "set", "name", "Shraddha"); r.exitCode != 0 || strings.TrimSpace(r.stdout) != "OK" {
		t.Fatalf("set: %+v", r)
	}
	if r := run(t, bin, dbPath, "get", "name"); r.exitCode != 0 || strings.TrimSpace(r.stdout) != "Shraddha" {
		t.Fatalf("get: %+v", r)
	}
	if r := run(t, bin, dbPath, "exists", "name"); r.exitCode != 0 || strings.TrimSpace(r.stdout) != "true" {
		t.Fatalf("exists: %+v", r)
	}
	if r := run(t, bin, dbPath, "get", "missing"); r.exitCode != 3 {
		t.Fatalf("get missing: expected exit 3, got %+v", r)
	}
	if r := run(t, bin, dbPath, "delete", "name"); r.exitCode != 0 {
		t.Fatalf("delete: %+v", r)
	}
	if r := run(t, bin, dbPath, "delete", "name"); r.exitCode != 3 {
		t.Fatalf("delete missing: expected exit 3, got %+v", r)
	}
}

func TestCLIPersistenceAcrossProcesses(t *testing.T) {
	bin := buildBinary(t)
	dbPath := filepath.Join(t.TempDir(), "minikv.db")

	run(t, bin, dbPath, "set", "a", "1")
	run(t, bin, dbPath, "set", "b", "2")

	r := run(t, bin, dbPath, "list")
	got := strings.Fields(strings.TrimSpace(r.stdout))
	if len(got) != 2 || got[0] != "a" || got[1] != "b" {
		t.Fatalf("list after two separate processes: got %v", got)
	}
}

func TestCLIBackupRestore(t *testing.T) {
	bin := buildBinary(t)
	dir := t.TempDir()
	dbPath := filepath.Join(dir, "minikv.db")
	backupPath := filepath.Join(dir, "minikv.bak")

	run(t, bin, dbPath, "set", "x", "1")
	if r := run(t, bin, dbPath, "backup", backupPath); r.exitCode != 0 {
		t.Fatalf("backup: %+v", r)
	}
	if _, err := os.Stat(backupPath); err != nil {
		t.Fatalf("backup file missing: %v", err)
	}

	if err := os.Remove(dbPath); err != nil {
		t.Fatalf("remove: %v", err)
	}
	if r := run(t, bin, dbPath, "restore", backupPath); r.exitCode != 0 {
		t.Fatalf("restore: %+v", r)
	}
	if r := run(t, bin, dbPath, "get", "x"); r.exitCode != 0 || strings.TrimSpace(r.stdout) != "1" {
		t.Fatalf("get after restore: %+v", r)
	}
}
