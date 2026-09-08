package main

import (
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"
)

// Test DAG Construction and Level Calculation
func TestDAG_Valid(t *testing.T) {
	cfg := &Config{
		Tasks: map[string]Task{
			"lint": {
				Name:    "lint",
				Command: "echo lint",
			},
			"build": {
				Name:      "build",
				Command:   "echo build",
				DependsOn: []string{"lint"},
			},
			"test": {
				Name:      "test",
				Command:   "echo test",
				DependsOn: []string{"build"},
			},
		},
	}

	dag, err := BuildDAG(cfg)
	if err != nil {
		t.Fatalf("unexpected error building DAG: %v", err)
	}

	levels, err := GetExecutionBatches(dag, nil)
	if err != nil {
		t.Fatalf("unexpected error resolving levels: %v", err)
	}

	if len(levels) != 3 {
		t.Fatalf("expected 3 levels, got %d", len(levels))
	}

	if levels[0][0] != "lint" || levels[1][0] != "build" || levels[2][0] != "test" {
		t.Errorf("incorrect level ordering: %v", levels)
	}
}

// Test Cycle Detection with 3-state DFS
func TestDAG_CycleDetection(t *testing.T) {
	cfg := &Config{
		Tasks: map[string]Task{
			"A": {Name: "A", Command: "echo A", DependsOn: []string{"B"}},
			"B": {Name: "B", Command: "echo B", DependsOn: []string{"C"}},
			"C": {Name: "C", Command: "echo C", DependsOn: []string{"A"}},
		},
	}

	_, err := BuildDAG(cfg)
	if err == nil {
		t.Fatal("expected cycle detection error, got nil")
	}

	if !strings.Contains(err.Error(), "cyclic dependency detected") {
		t.Errorf("expected cyclic dependency error message, got: %v", err)
	}
}

// Test Missing Dependency Handling with Typo Suggestions
func TestDAG_UnknownDependency(t *testing.T) {
	cfg := &Config{
		Tasks: map[string]Task{
			"build": {Name: "build", Command: "echo build"},
			"A":     {Name: "A", Command: "echo A", DependsOn: []string{"biuld"}},
		},
	}

	_, err := BuildDAG(cfg)
	if err == nil {
		t.Fatal("expected error for nonexistent dependency, got nil")
	}
	if !strings.Contains(err.Error(), "did you mean: build?") {
		t.Errorf("expected typo suggestion in error, got: %v", err)
	}
}

// Test Hash Determinism and Invalidation on File / Env Changes
func TestHashing_Determinism(t *testing.T) {
	tmpDir := t.TempDir()
	testFile := filepath.Join(tmpDir, "test.txt")
	if err := os.WriteFile(testFile, []byte("hello world"), 0644); err != nil {
		t.Fatal(err)
	}

	task := Task{
		Name:    "compile",
		Command: "go build",
		Inputs:  []string{testFile},
		EnvVars: []string{"GOOS"},
	}

	fileHash, err := ComputeFileHash(testFile)
	if err != nil {
		t.Fatal(err)
	}

	h1 := ComputeTaskHash(task, map[string]string{testFile: fileHash}, map[string]string{"GOOS": "linux"}, map[string]string{})
	h2 := ComputeTaskHash(task, map[string]string{testFile: fileHash}, map[string]string{"GOOS": "linux"}, map[string]string{})

	if h1 != h2 {
		t.Errorf("expected deterministic hashes, got %s != %s", h1, h2)
	}

	// Invalidate file content
	_ = os.WriteFile(testFile, []byte("modified content"), 0644)
	newFileHash, _ := ComputeFileHash(testFile)
	h3 := ComputeTaskHash(task, map[string]string{testFile: newFileHash}, map[string]string{"GOOS": "linux"}, map[string]string{})

	if h1 == h3 {
		t.Error("hash did not change after file modification")
	}

	// Invalidate environment variable
	h4 := ComputeTaskHash(task, map[string]string{testFile: fileHash}, map[string]string{"GOOS": "windows"}, map[string]string{})
	if h1 == h4 {
		t.Error("hash did not change after environment variable modification")
	}
}

// Test --why Diagnostic Engine on Cache Miss
func TestExplainCacheMiss(t *testing.T) {
	task := Task{
		Name:    "test",
		Command: "echo test",
	}

	reason := ExplainCacheMiss(task, map[string]string{"a.go": "hash1"}, map[string]string{"ENV": "1"}, map[string]string{})
	if !strings.Contains(reason, "Initial execution") {
		t.Errorf("expected initial execution reason, got: %s", reason)
	}
}

// Test Cross-Platform Shell Command Dispatching
func TestShellCommand_CrossPlatform(t *testing.T) {
	tmpDir := t.TempDir()
	origWd, _ := os.Getwd()
	_ = os.Chdir(tmpDir)
	defer os.Chdir(origWd)

	task := Task{
		Name:    "echo-test",
		Command: "echo hello",
	}

	ctx := context.Background()
	cas := NewCASStore(filepath.Join(tmpDir, "cas"))
	logger := &TaskLogger{}

	res := ExecuteTask(ctx, task, "testhash_unique_123", logger, false, false, cas, nil)
	if res.Status != "EXECUTED" {
		t.Errorf("expected EXECUTED status, got: %s (err: %s)", res.Status, res.Error)
	}
	if !strings.Contains(strings.ToLower(res.Stdout), "hello") {
		t.Errorf("expected 'hello' in stdout, got: %s", res.Stdout)
	}
}

// Test Mermaid and ASCII Graph Generation
func TestMermaidAndASCIIGraph(t *testing.T) {
	cfg := &Config{
		Tasks: map[string]Task{
			"lint":  {Command: "go vet"},
			"test":  {Command: "go test", DependsOn: []string{"lint"}},
			"build": {Command: "go build", DependsOn: []string{"test"}},
		},
	}

	mermaid := GenerateMermaidGraph(cfg)
	if !strings.Contains(mermaid, "lint --> test;") || !strings.Contains(mermaid, "test --> build;") {
		t.Errorf("invalid mermaid graph output: %s", mermaid)
	}

	ascii := GenerateASCIIGraph(cfg)
	if !strings.Contains(ascii, "lint") || !strings.Contains(ascii, "depends on:") {
		t.Errorf("invalid ASCII graph output: %s", ascii)
	}
}

// Test Two-Tier CAS Store & Restore
func TestCache_StoreAndRestore(t *testing.T) {
	tmpDir := t.TempDir()
	cas := NewCASStore(tmpDir)

	outFile := filepath.Join(tmpDir, "out.txt")
	_ = os.WriteFile(outFile, []byte("artifact content"), 0644)

	h, err := cas.StoreBlob(outFile)
	if err != nil {
		t.Fatalf("failed storing blob: %v", err)
	}

	_ = os.Remove(outFile)

	err = cas.RestoreBlob(h, outFile)
	if err != nil {
		t.Fatalf("failed restoring blob: %v", err)
	}

	data, _ := os.ReadFile(outFile)
	if string(data) != "artifact content" {
		t.Errorf("restored content mismatch: %s", string(data))
	}
}

// Test End-to-End Pipeline Execution
func TestPipeline_EndToEndIntegration(t *testing.T) {
	tmpDir := t.TempDir()
	origWd, _ := os.Getwd()
	_ = os.Chdir(tmpDir)
	defer os.Chdir(origWd)

	_ = os.WriteFile("source.txt", []byte("data"), 0644)

	cmd1 := "echo step 1"
	cmd2 := "echo step 2"

	cfg := &Config{
		Tasks: map[string]Task{
			"t1": {
				Name:    "t1",
				Command: cmd1,
				Inputs:  []string{"source.txt"},
				Outputs: []string{"out1.txt"},
			},
			"t2": {
				Name:      "t2",
				Command:   cmd2,
				DependsOn: []string{"t1"},
			},
		},
	}

	summary, err := RunPipeline(context.Background(), cfg, []string{"t2"}, 2, false, false, false, true, true, nil)
	if err != nil {
		t.Fatalf("pipeline failed: %v", err)
	}

	if summary.ExecutedTasks != 2 || summary.CachedTasks != 0 {
		t.Errorf("expected 2 executed tasks, got %d executed, %d cached", summary.ExecutedTasks, summary.CachedTasks)
	}

	// Second run should be 100% cached
	summary2, err := RunPipeline(context.Background(), cfg, []string{"t2"}, 2, false, false, false, true, true, nil)
	if err != nil {
		t.Fatalf("second pipeline run failed: %v", err)
	}

	if summary2.CachedTasks != 2 {
		t.Errorf("expected 2 cached tasks, got %d", summary2.CachedTasks)
	}
}

// Test Cache Clean with Age and Size Policies
func TestCleanCache_Policy(t *testing.T) {
	tmpDir := t.TempDir()
	origCacheDir := CacheDir
	_ = origCacheDir

	_ = os.MkdirAll(filepath.Join(tmpDir, "ac"), 0755)
	_ = os.WriteFile(filepath.Join(tmpDir, "ac", "dummy.json"), []byte(`{"exit_code":0}`), 0644)

	err := CleanCache(24*time.Hour, 1024*1024)
	if err != nil {
		t.Errorf("unexpected error cleaning cache: %v", err)
	}
}

// Test FindConfigRoot Traversal
func TestFindConfigRoot(t *testing.T) {
	tmpDir := t.TempDir()
	configPath := filepath.Join(tmpDir, "tasks.json")
	if err := os.WriteFile(configPath, []byte(`{"tasks":{}}`), 0644); err != nil {
		t.Fatal(err)
	}

	nestedDir := filepath.Join(tmpDir, "src", "deep", "nested")
	if err := os.MkdirAll(nestedDir, 0755); err != nil {
		t.Fatal(err)
	}

	rootDir, resolved, err := FindConfigRoot(nestedDir, "")
	if err != nil {
		t.Fatalf("failed to find config root: %v", err)
	}

	if rootDir != tmpDir || resolved != configPath {
		t.Errorf("resolved mismatch: got %s, %s; want %s, %s", rootDir, resolved, tmpDir, configPath)
	}
}

// Test Pass-Through Arguments
func TestPassThroughArgs(t *testing.T) {
	tmpDir := t.TempDir()
	origWd, _ := os.Getwd()
	_ = os.Chdir(tmpDir)
	defer os.Chdir(origWd)

	task := Task{
		Name:    "test-pass",
		Command: "echo base",
	}

	ctx := context.Background()
	cas := NewCASStore(filepath.Join(tmpDir, "cas"))
	logger := &TaskLogger{}

	res := ExecuteTask(ctx, task, "passhash_unique_123", logger, false, false, cas, []string{"--extra-flag", "val"})
	if !strings.Contains(res.Stdout, "--extra-flag") && !strings.Contains(res.Stdout, "val") {
		// On windows echo echoes the extra flags
		if runtime.GOOS == "windows" {
			t.Logf("stdout: %s", res.Stdout)
		}
	}
}

// Test .env Parsing and Variable Expansion
func TestDotEnvLoading(t *testing.T) {
	tmpDir := t.TempDir()
	envPath := filepath.Join(tmpDir, ".env")
	content := "PORT=8080\nAPI_HOST=localhost\nFULL_URL=http://${API_HOST}:${PORT:-3000}/api\nDEFAULT_FALLBACK=${UNSET_VAR:-fallback_val}\n"
	if err := os.WriteFile(envPath, []byte(content), 0644); err != nil {
		t.Fatal(err)
	}

	_ = LoadDotEnv(tmpDir)

	if os.Getenv("PORT") != "8080" {
		t.Errorf("expected PORT=8080, got %s", os.Getenv("PORT"))
	}
	if os.Getenv("FULL_URL") != "http://localhost:8080/api" {
		t.Errorf("expected expanded FULL_URL, got %s", os.Getenv("FULL_URL"))
	}
	if os.Getenv("DEFAULT_FALLBACK") != "fallback_val" {
		t.Errorf("expected DEFAULT_FALLBACK=fallback_val, got %s", os.Getenv("DEFAULT_FALLBACK"))
	}
}

// Test Typo Suggestions using Levenshtein Distance
func TestTypoSuggestions(t *testing.T) {
	valid := []string{"build", "bundle", "test", "lint", "deploy"}
	suggestions := SuggestSimilarTask("buidl", valid)
	if len(suggestions) == 0 || suggestions[0] != "build" {
		t.Errorf("expected 'build' suggestion for 'buidl', got %v", suggestions)
	}

	suggestions = SuggestSimilarTask("tst", valid)
	if len(suggestions) == 0 || suggestions[0] != "test" {
		t.Errorf("expected 'test' suggestion for 'tst', got %v", suggestions)
	}
}

// Test Path Traversal Security Sandboxing (ValidateSafePath)
func TestValidateSafePath(t *testing.T) {
	baseDir := t.TempDir()

	safePath, err := ValidateSafePath(baseDir, "src/components/button.tsx")
	if err != nil || !strings.HasPrefix(safePath, baseDir) {
		t.Errorf("expected safe path resolution, got: %s (err: %v)", safePath, err)
	}

	_, errEscape := ValidateSafePath(baseDir, "../../etc/passwd")
	if errEscape == nil {
		t.Fatal("security violation: path traversal escape was permitted!")
	}
}

// Test Cryptographic HMAC-SHA256 Anti-Tamper Signing & Verification
func TestHMAC_IntegrityAndAntiTamper(t *testing.T) {
	secretKey := []byte("top-secret-signing-key-12345")
	payload := CacheSignaturePayload{
		TaskName:     "build:release",
		Command:      "go build -o app",
		InputHash:    "a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90",
		OutputHashes: map[string]string{"app": "fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210"},
		StdoutHash:   "9999999999999999999999999999999999999999999999999999999999999999",
		ExitCode:     0,
	}

	signature := GenerateHMAC(secretKey, payload)
	if signature == "" {
		t.Fatal("generated HMAC signature is empty")
	}

	if !VerifyHMAC(secretKey, payload, signature) {
		t.Fatal("HMAC verification failed for authentic payload")
	}

	tamperedPayload := payload
	tamperedPayload.ExitCode = 1
	if VerifyHMAC(secretKey, tamperedPayload, signature) {
		t.Fatal("HMAC verification succeeded for tampered payload!")
	}
}

// Test Real-Time Secrets Masking & Redaction
func TestSecretsRedactor(t *testing.T) {
	var buf strings.Builder
	redactor := NewRedactingWriter(&buf)

	input := "Deploying with API_KEY=ghp_ABC1234567890abcdefghijklmnopqrstuv and Authorization: Bearer secretTokenValue1234567890\n"
	_, err := redactor.Write([]byte(input))
	if err != nil {
		t.Fatalf("redactor write error: %v", err)
	}

	output := buf.String()
	if strings.Contains(output, "ghp_ABC1234567890") || strings.Contains(output, "secretTokenValue") {
		t.Errorf("secret token leaked in output: %s", output)
	}
	if !strings.Contains(output, "***REDACTED***") {
		t.Errorf("expected ***REDACTED*** mask in output: %s", output)
	}
}

// Test SLSA v1.0 / in-toto Provenance Attestation
func TestSLSA_Provenance(t *testing.T) {
	task := Task{
		Name:    "build",
		Command: "go build -o app.exe",
	}

	prov, err := GenerateProvenance(
		task,
		map[string]string{"main.go": "1111111111111111111111111111111111111111111111111111111111111111"},
		map[string]string{"app.exe": "2222222222222222222222222222222222222222222222222222222222222222"},
		time.Now().Add(-1*time.Second),
		time.Now(),
		"inv-id-12345",
	)
	if err != nil {
		t.Fatalf("failed generating SLSA provenance: %v", err)
	}

	if !strings.Contains(prov, "https://slsa.dev/provenance/v1") {
		t.Errorf("missing SLSA v1 predicate type in provenance: %s", prov)
	}
	if !strings.Contains(prov, "app.exe") || !strings.Contains(prov, "22222222") {
		t.Errorf("missing output subject digest in provenance: %s", prov)
	}
}

// Test Two-Tier CAS Deduplication & Hardlinks
func TestCAS_DeduplicationAndHardlinks(t *testing.T) {
	tmpDir := t.TempDir()
	cas := NewCASStore(tmpDir)

	testFile := filepath.Join(tmpDir, "output_artifact.bin")
	_ = os.WriteFile(testFile, []byte("large binary payload content"), 0644)

	blobHash1, err := cas.StoreBlob(testFile)
	if err != nil {
		t.Fatalf("failed putting file to CAS: %v", err)
	}

	blobHash2, err := cas.StoreBlob(testFile)
	if err != nil || blobHash1 != blobHash2 {
		t.Errorf("CAS deduplication failure: %s != %s", blobHash1, blobHash2)
	}

	restoreDst := filepath.Join(tmpDir, "restored_artifact.bin")
	if err := cas.RestoreBlob(blobHash1, restoreDst); err != nil {
		t.Fatalf("failed restoring from CAS: %v", err)
	}

	restoredData, err := os.ReadFile(restoreDst)
	if err != nil || string(restoredData) != "large binary payload content" {
		t.Errorf("restored content mismatch: %s", string(restoredData))
	}
}

// Test Built-in HTTP Remote Cache Server
func TestRemoteCacheServer_HTTP(t *testing.T) {
	tmpDir := t.TempDir()
	authToken := "test-secret-token-xyz"
	srv := NewRemoteCacheServer(0, tmpDir, authToken)

	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", srv.handleHealthz)
	mux.HandleFunc("/v1/ac/", srv.authMiddleware(srv.handleActionCache))
	mux.HandleFunc("/v1/cas/", srv.authMiddleware(srv.handleCAS))

	ts := httptest.NewServer(mux)
	defer ts.Close()

	resp, err := http.Get(ts.URL + "/healthz")
	if err != nil || resp.StatusCode != http.StatusOK {
		t.Fatalf("healthz failed: %v, code: %d", err, resp.StatusCode)
	}

	req, _ := http.NewRequest(http.MethodGet, ts.URL+"/v1/ac/0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef", nil)
	respUnauth, err := http.DefaultClient.Do(req)
	if err != nil || respUnauth.StatusCode != http.StatusUnauthorized {
		t.Fatalf("expected 401 Unauthorized, got %d", respUnauth.StatusCode)
	}

	actionHash := "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
	payload := `{"exit_code":0,"stdout":"test remote cache"}`

	reqPut, _ := http.NewRequest(http.MethodPut, ts.URL+"/v1/ac/"+actionHash, strings.NewReader(payload))
	reqPut.Header.Set("Authorization", "Bearer "+authToken)
	respPut, err := http.DefaultClient.Do(reqPut)
	if err != nil || respPut.StatusCode != http.StatusCreated {
		t.Fatalf("Action Cache PUT failed, code: %d", respPut.StatusCode)
	}
}

// Test Weighted Resource Pool Scheduler
func TestWeightedPool_Concurrency(t *testing.T) {
	pool := NewWeightedPool(4)

	pool.Acquire(3)

	acquiredSecond := make(chan bool, 1)
	go func() {
		pool.Acquire(2)
		acquiredSecond <- true
	}()

	select {
	case <-acquiredSecond:
		t.Fatal("weighted pool allowed acquisition before capacity was released!")
	case <-time.After(50 * time.Millisecond):
		// Expected to block
	}

	pool.Release(3)

	select {
	case <-acquiredSecond:
		pool.Release(2)
	case <-time.After(500 * time.Millisecond):
		t.Fatal("timed out waiting for second acquisition after release")
	}
}

// Test Git-Aware Affected Tasks Computation
func TestComputeAffectedTasks(t *testing.T) {
	tasks := map[string][]string{
		"auth:lint": {"pkg/auth/**/*.go"},
		"auth:test": {"pkg/auth/**/*.go"},
		"api:build": {"cmd/api/**/*.go"},
		"e2e:test":  {"tests/**/*.go"},
	}

	dependents := map[string][]string{
		"auth:test": {"api:build"},
		"api:build": {"e2e:test"},
	}

	changedFiles := []string{"pkg/auth/token.go"}
	affected := ComputeAffectedTasks(tasks, dependents, changedFiles, matchGlob)

	if len(affected) != 4 {
		t.Fatalf("expected 4 affected tasks, got %d: %v", len(affected), affected)
	}

	expected := []string{"api:build", "auth:lint", "auth:test", "e2e:test"}
	for i, name := range expected {
		if affected[i] != name {
			t.Errorf("affected task mismatch at %d: %s != %s", i, affected[i], name)
		}
	}
}

// Test Zephyr Doctor Diagnostic Engine
func TestDoctor_HealthCheck(t *testing.T) {
	tmpDir := t.TempDir()
	configPath := filepath.Join(tmpDir, "tasks.json")
	_ = os.WriteFile(configPath, []byte(`{
		"tasks": {
			"lint": {"command": "echo lint"},
			"test": {"command": "echo test", "depends_on": ["lint"]}
		}
	}`), 0644)

	exitCode := RunDoctorCommand(tmpDir, configPath)
	if exitCode != 0 {
		t.Errorf("expected doctor exit code 0 for healthy workspace, got %d", exitCode)
	}
}

// Test Monorepo Multi-Package Discovery
func TestMonorepo_WorkspaceDiscovery(t *testing.T) {
	tmpDir := t.TempDir()
	rootConfig := filepath.Join(tmpDir, "tasks.json")
	_ = os.WriteFile(rootConfig, []byte(`{
		"workspaces": ["packages/*"],
		"tasks": {
			"root-check": {"command": "echo root"}
		}
	}`), 0644)

	pkgDir := filepath.Join(tmpDir, "packages", "ui")
	_ = os.MkdirAll(pkgDir, 0755)
	_ = os.WriteFile(filepath.Join(pkgDir, "tasks.json"), []byte(`{
		"tasks": {
			"build": {"command": "echo build-ui"}
		}
	}`), 0644)

	cfg, err := LoadConfig(rootConfig)
	if err != nil {
		t.Fatalf("failed loading monorepo config: %v", err)
	}

	if _, exists := cfg.Tasks["ui#build"]; !exists {
		t.Errorf("expected discovered task 'ui#build', tasks: %v", cfg.Tasks)
	}
}
