package cli

import (
	"bytes"
	json "encoding/json"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"testing"
	"time"
)

func TestCrashHelperProcess(t *testing.T) {
	if os.Getenv("UNDOLANG_CRASH_HELPER") != "1" {
		return
	}
	point := os.Getenv("UNDOLANG_CRASH_POINT")
	wantOccurrence, _ := strconv.Atoi(os.Getenv("UNDOLANG_CRASH_OCCURRENCE"))
	if wantOccurrence < 1 {
		wantOccurrence = 1
	}
	seen := 0
	checkpoint := func(current string) {
		if current != point {
			return
		}
		seen++
		if seen != wantOccurrence {
			return
		}
		if err := os.WriteFile(os.Getenv("UNDOLANG_CRASH_SENTINEL"), []byte(current), 0o600); err != nil {
			os.Exit(90)
		}
		select {}
	}
	code := (App{Stdin: bytes.NewReader(nil), Stdout: os.Stdout, Stderr: os.Stderr, Checkpoint: checkpoint}).Run([]string{"run", os.Getenv("UNDOLANG_CRASH_SCRIPT"), "--root", os.Getenv("UNDOLANG_CRASH_ROOT"), "--yes", "--json"})
	os.Exit(code)
}

func TestRealProcessCrashRecoveryMatrix(t *testing.T) {
	if testing.Short() {
		t.Skip("real process crash matrix is skipped in short mode")
	}
	binary := filepath.Join(t.TempDir(), "undo")
	if os.PathSeparator == '\\' {
		binary += ".exe"
	}
	build := exec.Command("go", "build", "-trimpath", "-buildvcs=false", "-o", binary, "./cmd/undo")
	build.Dir = filepath.Clean(filepath.Join("..", ".."))
	build.Env = append(os.Environ(), "GOPROXY=off")
	if output, err := build.CombinedOutput(); err != nil {
		t.Fatalf("build helper binary: %v\n%s", err, output)
	}
	tests := []struct {
		name, point string
		occurrence  int
	}{
		{"after tx begin", "tx_begin", 1},
		{"after backup before prepared", "backup_prepared", 1},
		{"after prepared", "op_prepared", 1},
		{"after mutation before applied", "mutation_applied", 1},
		{"after applied", "op_applied", 1},
		{"during later operation", "op_applied", 2},
		{"during verifying", "verifying", 1},
		{"during rollback after inverse", "rollback_inverse_applied", 1},
		{"after rollback record before cleanup", "rollback_complete_recorded", 1},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			base := t.TempDir()
			root := filepath.Join(base, "root")
			if err := os.Mkdir(root, 0o755); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(filepath.Join(root, "existing"), []byte("before"), 0o600); err != nil {
				t.Fatal(err)
			}
			script := filepath.Join(base, "crash.undo")
			source := `transaction "crash" {
write "existing" = "after"
write "created" = "temporary"
mkdir "created-dir"
assert contains "existing" "never-present"
}`
			if err := os.WriteFile(script, []byte(source), 0o600); err != nil {
				t.Fatal(err)
			}
			sentinel := filepath.Join(base, "checkpoint")
			command := exec.Command(os.Args[0], "-test.run=^TestCrashHelperProcess$")
			command.Env = append(os.Environ(),
				"UNDOLANG_CRASH_HELPER=1",
				"UNDOLANG_CRASH_POINT="+test.point,
				"UNDOLANG_CRASH_OCCURRENCE="+strconv.Itoa(test.occurrence),
				"UNDOLANG_CRASH_SENTINEL="+sentinel,
				"UNDOLANG_CRASH_SCRIPT="+script,
				"UNDOLANG_CRASH_ROOT="+root,
			)
			var helperOutput bytes.Buffer
			command.Stdout, command.Stderr = &helperOutput, &helperOutput
			if err := command.Start(); err != nil {
				t.Fatal(err)
			}
			deadline := time.Now().Add(15 * time.Second)
			for {
				if _, err := os.Stat(sentinel); err == nil {
					break
				}
				if time.Now().After(deadline) {
					_ = command.Process.Kill()
					_ = command.Wait()
					t.Fatalf("checkpoint %s not reached\n%s", test.point, helperOutput.String())
				}
				time.Sleep(10 * time.Millisecond)
			}
			if err := command.Process.Kill(); err != nil {
				t.Fatal(err)
			}
			_ = command.Wait()

			recoverCommand := exec.Command(binary, "recover", "--root", root, "--yes", "--json")
			output, err := recoverCommand.CombinedOutput()
			if err != nil {
				t.Fatalf("recover: %v\n%s", err, output)
			}
			var envelope struct {
				OK bool `json:"ok"`
			}
			if err = json.Unmarshal(output, &envelope); err != nil || !envelope.OK {
				t.Fatalf("recovery output=%s err=%v", output, err)
			}
			content, err := os.ReadFile(filepath.Join(root, "existing"))
			if err != nil || string(content) != "before" {
				t.Fatalf("existing=%q err=%v", content, err)
			}
			for _, path := range []string{"created", "created-dir", filepath.Join(".undo", "active.lock")} {
				if _, err := os.Lstat(filepath.Join(root, path)); !errors.Is(err, os.ErrNotExist) {
					t.Fatalf("%s remains after recovery: %v", path, err)
				}
			}
		})
	}
}

func TestCompiledBinaryContracts(t *testing.T) {
	binary := filepath.Join(t.TempDir(), "undo")
	if os.PathSeparator == '\\' {
		binary += ".exe"
	}
	build := exec.Command("go", "build", "-trimpath", "-buildvcs=false", "-o", binary, "./cmd/undo")
	build.Dir = filepath.Clean(filepath.Join("..", ".."))
	build.Env = append(os.Environ(), "GOPROXY=off")
	if output, err := build.CombinedOutput(); err != nil {
		t.Fatalf("build: %v\n%s", err, output)
	}
	for _, args := range [][]string{{"--help"}, {"version", "--json"}, {"capabilities", "--json"}, {"schema", "--json"}, {"run", "--help"}, {"recover", "--help"}, {"history", "--help"}, {"inspect", "--help"}} {
		command := exec.Command(binary, args...)
		stdout, err := command.Output()
		if err != nil {
			t.Fatalf("%v: %v", args, err)
		}
		if len(stdout) == 0 {
			t.Fatalf("%v produced no stdout", args)
		}
		if args[len(args)-1] == "--json" {
			var envelope map[string]any
			if err := json.Unmarshal(stdout, &envelope); err != nil || envelope["api_version"] != "undo-cli/1" {
				t.Fatalf("%v output=%s err=%v", args, stdout, err)
			}
		}
	}
}
