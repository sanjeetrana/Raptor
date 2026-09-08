package tests

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// The tests package is intentionally black-box: it builds the public binary
// once and drives it through its documented CLI instead of reaching into
// internal packages. Package-level tests still provide fast unit coverage;
// these tests prove the assembled product and its filesystem contract.
var (
	e2eBinary string
	e2eTemp   string
)

func TestMain(m *testing.M) {
	repo, err := findRepositoryRoot()
	if err != nil {
		fmt.Fprintf(os.Stderr, "find repository root: %v\n", err)
		os.Exit(1)
	}
	e2eTemp, err = os.MkdirTemp("", "undolang-e2e-")
	if err != nil {
		fmt.Fprintf(os.Stderr, "create e2e temp directory: %v\n", err)
		os.Exit(1)
	}
	e2eBinary = filepath.Join(e2eTemp, "undo")
	if filepath.Separator == '\\' {
		e2eBinary += ".exe"
	}
	build := exec.Command("go", "build", "-trimpath", "-buildvcs=false", "-o", e2eBinary, "./cmd/undo")
	build.Dir = repo
	build.Env = replaceEnv(os.Environ(), map[string]string{
		"CGO_ENABLED": "0",
		"GOPROXY":     "off",
		"GOTOOLCHAIN": "go1.27.0",
	})
	if output, buildErr := build.CombinedOutput(); buildErr != nil {
		fmt.Fprintf(os.Stderr, "build e2e binary: %v\n%s", buildErr, output)
		_ = os.RemoveAll(e2eTemp)
		os.Exit(1)
	}
	code := m.Run()
	_ = os.RemoveAll(e2eTemp)
	os.Exit(code)
}

func findRepositoryRoot() (string, error) {
	directory, err := os.Getwd()
	if err != nil {
		return "", err
	}
	for {
		if _, err := os.Stat(filepath.Join(directory, "go.mod")); err == nil {
			return directory, nil
		}
		parent := filepath.Dir(directory)
		if parent == directory {
			return "", errors.New("go.mod not found")
		}
		directory = parent
	}
}

func replaceEnv(environment []string, values map[string]string) []string {
	result := make([]string, 0, len(environment)+len(values))
	for _, entry := range environment {
		key, _, ok := strings.Cut(entry, "=")
		if !ok {
			result = append(result, entry)
			continue
		}
		if _, replace := values[key]; !replace {
			result = append(result, entry)
		}
	}
	for key, value := range values {
		result = append(result, key+"="+value)
	}
	return result
}

type cliResult struct {
	Code   int
	Stdout string
	Stderr string
}

func runUndo(t *testing.T, arguments ...string) cliResult {
	t.Helper()
	command := exec.Command(e2eBinary, arguments...)
	var stdout, stderr bytes.Buffer
	command.Stdout = &stdout
	command.Stderr = &stderr
	err := command.Run()
	code := 0
	if err != nil {
		var exitError *exec.ExitError
		if !errors.As(err, &exitError) {
			t.Fatalf("run %v: %v", arguments, err)
		}
		code = exitError.ExitCode()
	}
	return cliResult{Code: code, Stdout: stdout.String(), Stderr: stderr.String()}
}

type envelope struct {
	APIVersion string          `json:"api_version"`
	OK         bool            `json:"ok"`
	Result     json.RawMessage `json:"result"`
	Error      *struct {
		Code    string `json:"code"`
		Message string `json:"message"`
		Line    int    `json:"line"`
		Column  int    `json:"column"`
	} `json:"error"`
}

func decodeEnvelope(t *testing.T, output string) envelope {
	t.Helper()
	var result envelope
	if err := json.Unmarshal([]byte(output), &result); err != nil {
		t.Fatalf("invalid JSON output %q: %v", output, err)
	}
	if result.APIVersion != "undo-cli/1" {
		t.Fatalf("api version=%q, want undo-cli/1", result.APIVersion)
	}
	return result
}

func writeScript(t *testing.T, source string) string {
	t.Helper()
	directory := t.TempDir()
	path := filepath.Join(directory, "program.undo")
	if err := os.WriteFile(path, []byte(source), 0o600); err != nil {
		t.Fatal(err)
	}
	return path
}

func assertAbsent(t *testing.T, path string) {
	t.Helper()
	if _, err := os.Lstat(path); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("%s exists or could not be checked: %v", path, err)
	}
}

func TestE2ECheckPlanRunAndInspectWholeProgram(t *testing.T) {
	root := t.TempDir()
	script := writeScript(t, `transaction "prepare" {
  mkdir "data"
  write "data/version" = "1"
  assert contains "data/version" "1"
}

transaction "upgrade" {
  require exists "data/version"
  replace "data/version" "1" -> "2"
  assert contains "data/version" "2"
}`)

	checked := runUndo(t, "check", script, "--root", root, "--json")
	if checked.Code != 0 || checked.Stderr != "" {
		t.Fatalf("check code=%d stderr=%q stdout=%s", checked.Code, checked.Stderr, checked.Stdout)
	}
	checkEnvelope := decodeEnvelope(t, checked.Stdout)
	if !checkEnvelope.OK {
		t.Fatalf("check failed: %s", checked.Stdout)
	}
	var checkResult struct {
		Transactions []string `json:"transactions"`
	}
	if err := json.Unmarshal(checkEnvelope.Result, &checkResult); err != nil {
		t.Fatal(err)
	}
	if got, want := strings.Join(checkResult.Transactions, ","), "prepare,upgrade"; got != want {
		t.Fatalf("transaction order=%q, want %q", got, want)
	}
	assertAbsent(t, filepath.Join(root, ".undo"))
	assertAbsent(t, filepath.Join(root, "data"))

	planned := runUndo(t, "plan", "--json", script, "--root", root)
	if planned.Code != 0 || planned.Stderr != "" {
		t.Fatalf("plan code=%d stderr=%q stdout=%s", planned.Code, planned.Stderr, planned.Stdout)
	}
	planEnvelope := decodeEnvelope(t, planned.Stdout)
	if !planEnvelope.OK {
		t.Fatalf("plan failed: %s", planned.Stdout)
	}
	var planResult struct {
		SafeToStart  bool `json:"safe_to_start"`
		Transactions []struct {
			Name      string `json:"name"`
			Readiness string `json:"readiness"`
		} `json:"transactions"`
	}
	if err := json.Unmarshal(planEnvelope.Result, &planResult); err != nil {
		t.Fatal(err)
	}
	if !planResult.SafeToStart || len(planResult.Transactions) != 2 || planResult.Transactions[1].Readiness != "deferred" {
		t.Fatalf("unexpected program plan=%+v", planResult)
	}
	assertAbsent(t, filepath.Join(root, ".undo"))

	run := runUndo(t, "run", script, "--root", root, "--yes", "--json")
	if run.Code != 0 || run.Stderr != "" {
		t.Fatalf("run code=%d stderr=%q stdout=%s", run.Code, run.Stderr, run.Stdout)
	}
	runEnvelope := decodeEnvelope(t, run.Stdout)
	if !runEnvelope.OK {
		t.Fatalf("run failed: %s", run.Stdout)
	}
	var runResult struct {
		Transactions []struct {
			Name   string `json:"name"`
			ID     string `json:"transaction_id"`
			Status string `json:"status"`
		} `json:"transactions"`
	}
	if err := json.Unmarshal(runEnvelope.Result, &runResult); err != nil {
		t.Fatal(err)
	}
	if len(runResult.Transactions) != 2 {
		t.Fatalf("run transactions=%+v", runResult.Transactions)
	}
	for _, transaction := range runResult.Transactions {
		if transaction.Status != "committed" || transaction.ID == "" {
			t.Fatalf("unexpected transaction result=%+v", transaction)
		}
	}
	version, err := os.ReadFile(filepath.Join(root, "data", "version"))
	if err != nil || string(version) != "2" {
		t.Fatalf("version=%q err=%v", version, err)
	}

	history := runUndo(t, "history", "--root", root, "--json")
	if history.Code != 0 || history.Stderr != "" {
		t.Fatalf("history code=%d stderr=%q stdout=%s", history.Code, history.Stderr, history.Stdout)
	}
	historyEnvelope := decodeEnvelope(t, history.Stdout)
	var historyEntries []struct {
		ID     string `json:"id"`
		Name   string `json:"name"`
		Status string `json:"status"`
	}
	if err := json.Unmarshal(historyEnvelope.Result, &historyEntries); err != nil {
		t.Fatal(err)
	}
	if len(historyEntries) != 2 || historyEntries[0].Status != "COMMITTED" {
		t.Fatalf("history=%+v", historyEntries)
	}
	inspection := runUndo(t, "inspect", runResult.Transactions[0].ID, "--root", root, "--json")
	if inspection.Code != 0 || inspection.Stderr != "" {
		t.Fatalf("inspect code=%d stderr=%q stdout=%s", inspection.Code, inspection.Stderr, inspection.Stdout)
	}
	inspectionEnvelope := decodeEnvelope(t, inspection.Stdout)
	var inspectionResult struct {
		JournalRecords  int  `json:"journal_records"`
		BackupsRetained bool `json:"backups_retained"`
	}
	if err := json.Unmarshal(inspectionEnvelope.Result, &inspectionResult); err != nil {
		t.Fatal(err)
	}
	if inspectionResult.JournalRecords == 0 || inspectionResult.BackupsRetained {
		t.Fatalf("inspection=%+v", inspectionResult)
	}
}

func TestE2ESelectedTransactionDoesNotRunSiblings(t *testing.T) {
	root := t.TempDir()
	script := writeScript(t, `transaction "first" {
  write "first.txt" = "first"
}
transaction "selected" {
  write "selected.txt" = "selected"
}`)
	run := runUndo(t, "run", script, "--transaction", "selected", "--root", root, "--yes", "--json")
	if run.Code != 0 || run.Stderr != "" {
		t.Fatalf("run code=%d stderr=%q stdout=%s", run.Code, run.Stderr, run.Stdout)
	}
	result := decodeEnvelope(t, run.Stdout)
	var runResult struct {
		Mode         string `json:"mode"`
		SelectedName string `json:"selected_name"`
		Transactions []struct {
			Name   string `json:"name"`
			Status string `json:"status"`
		} `json:"transactions"`
	}
	if err := json.Unmarshal(result.Result, &runResult); err != nil {
		t.Fatal(err)
	}
	if runResult.Mode != "selected" || runResult.SelectedName != "selected" || len(runResult.Transactions) != 1 || runResult.Transactions[0].Name != "selected" || runResult.Transactions[0].Status != "committed" {
		t.Fatalf("selected result=%+v", runResult)
	}
	assertAbsent(t, filepath.Join(root, "first.txt"))
	content, err := os.ReadFile(filepath.Join(root, "selected.txt"))
	if err != nil || string(content) != "selected" {
		t.Fatalf("selected content=%q err=%v", content, err)
	}
}

func TestE2EWholeProgramFailureRollsBackOnlyCurrentAndSkipsLater(t *testing.T) {
	root := t.TempDir()
	script := writeScript(t, `transaction "first" {
  write "committed.txt" = "yes"
}
transaction "broken" {
  write "temporary.txt" = "remove me"
  assert contains "committed.txt" "this text is absent"
}
transaction "third" {
  write "skipped.txt" = "must not run"
}`)
	run := runUndo(t, "run", script, "--root", root, "--yes", "--json")
	if run.Code != 4 || run.Stderr != "" {
		t.Fatalf("run code=%d stderr=%q stdout=%s", run.Code, run.Stderr, run.Stdout)
	}
	result := decodeEnvelope(t, run.Stdout)
	if result.OK {
		t.Fatalf("failed run marked ok: %s", run.Stdout)
	}
	var runResult struct {
		Transactions []struct {
			Name   string `json:"name"`
			Status string `json:"status"`
			Error  *struct {
				Code string `json:"code"`
			} `json:"error"`
		} `json:"transactions"`
	}
	if err := json.Unmarshal(result.Result, &runResult); err != nil {
		t.Fatal(err)
	}
	if len(runResult.Transactions) != 3 {
		t.Fatalf("transaction results=%+v", runResult.Transactions)
	}
	wantStatuses := []string{"committed", "rolled_back", "skipped"}
	for index, want := range wantStatuses {
		if runResult.Transactions[index].Status != want {
			t.Fatalf("statuses=%+v, want %v", runResult.Transactions, wantStatuses)
		}
	}
	if runResult.Transactions[1].Error == nil || runResult.Transactions[1].Error.Code != "E_POSTCONDITION_FAILED" {
		t.Fatalf("broken transaction error=%+v", runResult.Transactions[1].Error)
	}
	content, err := os.ReadFile(filepath.Join(root, "committed.txt"))
	if err != nil || string(content) != "yes" {
		t.Fatalf("earlier commit=%q err=%v", content, err)
	}
	assertAbsent(t, filepath.Join(root, "temporary.txt"))
	assertAbsent(t, filepath.Join(root, "skipped.txt"))
}

func TestE2EApprovalPathPolicyAndWholeSourceValidation(t *testing.T) {
	root := t.TempDir()
	valid := writeScript(t, `transaction "write" { write "created.txt" = "value" }`)
	denied := runUndo(t, "run", valid, "--root", root, "--json")
	if denied.Code != 1 || denied.Stderr != "" {
		t.Fatalf("approval code=%d stderr=%q stdout=%s", denied.Code, denied.Stderr, denied.Stdout)
	}
	deniedEnvelope := decodeEnvelope(t, denied.Stdout)
	if deniedEnvelope.OK || deniedEnvelope.Error == nil || deniedEnvelope.Error.Code != "E_APPROVAL_REQUIRED" {
		t.Fatalf("approval response=%s", denied.Stdout)
	}
	assertAbsent(t, filepath.Join(root, "created.txt"))
	assertAbsent(t, filepath.Join(root, ".undo"))

	escape := writeScript(t, `transaction "escape" { write "../outside.txt" = "no" }`)
	escapeResult := runUndo(t, "check", escape, "--root", root, "--json")
	if escapeResult.Code != 3 || escapeResult.Stderr != "" {
		t.Fatalf("escape code=%d stderr=%q stdout=%s", escapeResult.Code, escapeResult.Stderr, escapeResult.Stdout)
	}
	escapeEnvelope := decodeEnvelope(t, escapeResult.Stdout)
	if escapeEnvelope.OK || escapeEnvelope.Error == nil || escapeEnvelope.Error.Code != "E_PATH_ESCAPE" {
		t.Fatalf("escape response=%s", escapeResult.Stdout)
	}
	assertAbsent(t, filepath.Join(filepath.Dir(root), "outside.txt"))

	malformed := writeScript(t, "transaction \"selected\" { write \"selected.txt\" = \"yes\" }\ntransaction \"broken\" { write \"unterminated\"")
	malformedResult := runUndo(t, "run", malformed, "--transaction", "selected", "--root", root, "--yes", "--json")
	if malformedResult.Code != 1 || malformedResult.Stderr != "" {
		t.Fatalf("malformed code=%d stderr=%q stdout=%s", malformedResult.Code, malformedResult.Stderr, malformedResult.Stdout)
	}
	malformedEnvelope := decodeEnvelope(t, malformedResult.Stdout)
	if malformedEnvelope.OK || malformedEnvelope.Error == nil || malformedEnvelope.Error.Code == "" || malformedEnvelope.Error.Line < 1 || malformedEnvelope.Error.Column < 1 {
		t.Fatalf("malformed response=%s", malformedResult.Stdout)
	}
	assertAbsent(t, filepath.Join(root, "selected.txt"))

	duplicate := writeScript(t, `transaction "same" { write "one.txt" = "one" }
transaction "same" { write "two.txt" = "two" }`)
	duplicateResult := runUndo(t, "check", duplicate, "--root", root, "--json")
	if duplicateResult.Code != 1 || duplicateResult.Stderr != "" {
		t.Fatalf("duplicate code=%d stderr=%q stdout=%s", duplicateResult.Code, duplicateResult.Stderr, duplicateResult.Stdout)
	}
	duplicateEnvelope := decodeEnvelope(t, duplicateResult.Stdout)
	if duplicateEnvelope.OK || duplicateEnvelope.Error == nil || duplicateEnvelope.Error.Code != "E_SEMANTIC" {
		t.Fatalf("duplicate response=%s", duplicateResult.Stdout)
	}
	assertAbsent(t, filepath.Join(root, "one.txt"))
	assertAbsent(t, filepath.Join(root, "two.txt"))
}
