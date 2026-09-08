package cli

import (
	"bytes"
	json "encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func invoke(args ...string) (int, string, string) {
	var stdout, stderr bytes.Buffer
	code := (App{Stdout: &stdout, Stderr: &stderr}).Run(args)
	return code, stdout.String(), stderr.String()
}

func TestCheckJSONAndInterspersedFlags(t *testing.T) {
	root := t.TempDir()
	scriptDir := t.TempDir()
	script := filepath.Join(scriptDir, "test.undo")
	if err := os.WriteFile(script, []byte(`transaction "a" { mkdir "new" } transaction "b" {}`), 0o600); err != nil {
		t.Fatal(err)
	}
	code, stdout, stderr := invoke("check", script, "--root", root, "--json")
	if code != 0 || stderr != "" {
		t.Fatalf("code=%d stdout=%s stderr=%s", code, stdout, stderr)
	}
	var envelope struct {
		APIVersion string `json:"api_version"`
		OK         bool   `json:"ok"`
		Result     struct {
			Transactions []string `json:"transactions"`
		} `json:"result"`
	}
	if err := json.Unmarshal([]byte(stdout), &envelope); err != nil {
		t.Fatal(err)
	}
	if !envelope.OK || envelope.APIVersion != "undo-cli/1" || len(envelope.Result.Transactions) != 2 {
		t.Fatalf("envelope=%#v", envelope)
	}
	entries, err := os.ReadDir(root)
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 0 {
		t.Fatalf("check mutated root: %v", entries)
	}
}

func TestPlanJSONNoMutation(t *testing.T) {
	root := t.TempDir()
	script := filepath.Join(t.TempDir(), "test.undo")
	if err := os.WriteFile(filepath.Join(root, "source"), []byte("data"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(script, []byte(`transaction "x" { copy "source" -> "target" }`), 0o600); err != nil {
		t.Fatal(err)
	}
	code, stdout, stderr := invoke("plan", "--json", script, "--root", root)
	if code != 0 || stderr != "" {
		t.Fatalf("code=%d stdout=%s stderr=%s", code, stdout, stderr)
	}
	var envelope map[string]any
	if err := json.Unmarshal([]byte(stdout), &envelope); err != nil {
		t.Fatal(err)
	}
	if envelope["ok"] != true {
		t.Fatalf("output=%v", envelope)
	}
	if _, err := os.Stat(filepath.Join(root, "target")); !os.IsNotExist(err) {
		t.Fatal("plan mutated target")
	}
}

func TestAgentContracts(t *testing.T) {
	for _, command := range []string{"capabilities", "schema", "version"} {
		code, stdout, stderr := invoke(command, "--json")
		if code != 0 || stderr != "" {
			t.Fatalf("%s code=%d stderr=%s", command, code, stderr)
		}
		var envelope map[string]any
		if err := json.Unmarshal([]byte(stdout), &envelope); err != nil {
			t.Fatalf("%s: %v", command, err)
		}
		if envelope["api_version"] != "undo-cli/1" || envelope["ok"] != true {
			t.Fatalf("%s: %v", command, envelope)
		}
	}
}

func TestSchemaDescribesApprovalRecoveryAndExitContracts(t *testing.T) {
	code, output, stderr := invoke("schema", "--json")
	if code != 0 || stderr != "" {
		t.Fatalf("code=%d stderr=%s", code, stderr)
	}
	var envelope struct {
		Result map[string]any `json:"result"`
	}
	if err := json.Unmarshal([]byte(output), &envelope); err != nil {
		t.Fatal(err)
	}
	for _, key := range []string{"workflow", "approval", "result_statuses", "exit_codes", "operations", "conditions"} {
		if _, ok := envelope.Result[key]; !ok {
			t.Errorf("schema omits %q", key)
		}
	}
}

func TestJSONErrorDoesNotPolluteStdout(t *testing.T) {
	code, stdout, stderr := invoke("check", "missing.undo", "--json")
	if code == 0 || stderr != "" {
		t.Fatalf("code=%d stdout=%s stderr=%s", code, stdout, stderr)
	}
	var envelope map[string]any
	if err := json.Unmarshal([]byte(stdout), &envelope); err != nil {
		t.Fatal(err)
	}
	if envelope["ok"] != false {
		t.Fatalf("%v", envelope)
	}
}

func TestExplicitFalseJSONFlagKeepsHumanErrorOnStderr(t *testing.T) {
	code, stdout, stderr := invoke("check", "--json=false")
	if code == 0 || stdout != "" || stderr == "" {
		t.Fatalf("code=%d stdout=%q stderr=%q", code, stdout, stderr)
	}
}

func TestRunRequiresApprovalAndCommitsWithYes(t *testing.T) {
	root := t.TempDir()
	script := filepath.Join(t.TempDir(), "run.undo")
	if err := os.WriteFile(script, []byte(`transaction "run" { write "created" = "value" }`), 0o600); err != nil {
		t.Fatal(err)
	}
	code, stdout, stderr := invoke("run", script, "--root", root, "--json")
	if code != 1 || stderr != "" {
		t.Fatalf("approval code=%d stdout=%s stderr=%s", code, stdout, stderr)
	}
	var denied map[string]any
	if err := json.Unmarshal([]byte(stdout), &denied); err != nil {
		t.Fatal(err)
	}
	if denied["ok"] != false {
		t.Fatalf("denied=%v", denied)
	}
	if _, err := os.Stat(filepath.Join(root, "created")); !os.IsNotExist(err) {
		t.Fatal("unapproved run mutated root")
	}

	code, stdout, stderr = invoke("run", script, "--root", root, "--yes", "--json")
	if code != 0 || stderr != "" {
		t.Fatalf("run code=%d stdout=%s stderr=%s", code, stdout, stderr)
	}
	var committed struct {
		OK     bool `json:"ok"`
		Result struct {
			Transactions []struct {
				Status string `json:"status"`
			} `json:"transactions"`
		} `json:"result"`
	}
	if err := json.Unmarshal([]byte(stdout), &committed); err != nil || !committed.OK || committed.Result.Transactions[0].Status != "committed" {
		t.Fatalf("committed=%#v err=%v", committed, err)
	}
}

func TestInteractiveConfirmation(t *testing.T) {
	root := t.TempDir()
	script := filepath.Join(t.TempDir(), "run.undo")
	if err := os.WriteFile(script, []byte(`transaction "run" { write "created" = "value" }`), 0o600); err != nil {
		t.Fatal(err)
	}
	var stdout, stderr bytes.Buffer
	app := App{Stdin: bytes.NewBufferString("yes\n"), Stdout: &stdout, Stderr: &stderr, IsTerminal: func() bool { return true }}
	if code := app.Run([]string{"run", script, "--root", root}); code != 0 {
		t.Fatalf("code=%d stdout=%s stderr=%s", code, stdout.String(), stderr.String())
	}
	if _, err := os.Stat(filepath.Join(root, "created")); err != nil {
		t.Fatal(err)
	}
	for _, required := range []string{"capability (primary):", "rollback estimate:", "write created (create)"} {
		if !strings.Contains(stdout.String(), required) {
			t.Errorf("interactive summary omits %q: %s", required, stdout.String())
		}
	}
}

func TestJSONEscapesNamesAndDoesNotLeakTargetContents(t *testing.T) {
	root := t.TempDir()
	secret := "prefix-PRIVATE-CONTENT-MUST-NOT-LEAK"
	if err := os.WriteFile(filepath.Join(root, "secret"), []byte(secret), 0o600); err != nil {
		t.Fatal(err)
	}
	script := filepath.Join(t.TempDir(), "odd.undo")
	if err := os.WriteFile(script, []byte("transaction \"odd\\n\\\"name\" { require contains \"secret\" \"prefix\" }"), 0o600); err != nil {
		t.Fatal(err)
	}
	code, output, stderr := invoke("plan", script, "--root", root, "--json")
	if code != 0 || stderr != "" {
		t.Fatalf("code=%d output=%s stderr=%s", code, output, stderr)
	}
	if strings.Contains(output, secret) {
		t.Fatal("plan JSON disclosed target file contents")
	}
	var envelope struct {
		Result struct {
			Transactions []struct {
				Name string `json:"name"`
			} `json:"transactions"`
		} `json:"result"`
	}
	if err := json.Unmarshal([]byte(output), &envelope); err != nil {
		t.Fatal(err)
	}
	if got := envelope.Result.Transactions[0].Name; got != "odd\n\"name" {
		t.Fatalf("transaction name=%q", got)
	}
}

func TestHistoryAndInspectJSON(t *testing.T) {
	root := t.TempDir()
	script := filepath.Join(t.TempDir(), "run.undo")
	if err := os.WriteFile(script, []byte(`transaction "run" { write "created" = "value" }`), 0o600); err != nil {
		t.Fatal(err)
	}
	code, output, _ := invoke("run", script, "--root", root, "--yes", "--json")
	if code != 0 {
		t.Fatal(output)
	}
	var run struct {
		Result struct {
			Transactions []struct {
				ID string `json:"transaction_id"`
			} `json:"transactions"`
		} `json:"result"`
	}
	if err := json.Unmarshal([]byte(output), &run); err != nil {
		t.Fatal(err)
	}
	code, output, _ = invoke("history", "--root", root, "--json")
	if code != 0 {
		t.Fatal(output)
	}
	var history map[string]any
	if err := json.Unmarshal([]byte(output), &history); err != nil {
		t.Fatal(err)
	}
	code, output, _ = invoke("inspect", run.Result.Transactions[0].ID, "--root", root, "--json")
	if code != 0 {
		t.Fatal(output)
	}
	var inspection map[string]any
	if err := json.Unmarshal([]byte(output), &inspection); err != nil || inspection["ok"] != true {
		t.Fatalf("inspection=%v err=%v", inspection, err)
	}
}
