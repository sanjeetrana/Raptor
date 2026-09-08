package main

import (
	"bufio"
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"regexp"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"text/tabwriter"
	"time"
)

// ============================================================================
// CONSTANTS, ANSI COLORS & CYBERNETIC STARTUP BANNER
// ============================================================================

const (
	ProjectName    = "ZEPHYR"
	Tagline        = "Zero-Dependency Incremental Build System & Task Orchestrator"
	Author         = "Naman Swami"
	Version        = "2.0.0"
	DefaultConfig  = "tasks.json"
	CacheDir       = ".taskcache"
	CASDir         = ".taskcache/cas/objects"
	ActionCacheDir = ".taskcache/ac"
)

// ANSI Colors (configurable via NO_COLOR / TTY detection)
var (
	ColorReset   = "\033[0m"
	ColorRed     = "\033[31m"
	ColorGreen   = "\033[32m"
	ColorYellow  = "\033[33m"
	ColorBlue    = "\033[34m"
	ColorMagenta = "\033[35m"
	ColorCyan    = "\033[36m"
	ColorGray    = "\033[90m"
	ColorBold    = "\033[1m"
	ColorWhite   = "\033[97m"
)

func InitColors() {
	if os.Getenv("NO_COLOR") != "" || os.Getenv("TERM") == "dumb" {
		DisableColors()
		return
	}
}

func DisableColors() {
	ColorReset = ""
	ColorRed = ""
	ColorGreen = ""
	ColorYellow = ""
	ColorBlue = ""
	ColorMagenta = ""
	ColorCyan = ""
	ColorGray = ""
	ColorBold = ""
	ColorWhite = ""
}

func isTerminal() bool {
	if os.Getenv("NO_COLOR") != "" || os.Getenv("CI") != "" {
		return false
	}
	return true
}

func PrintStartupBanner(quiet bool) {
	if quiet || os.Getenv("NO_COLOR") != "" || os.Getenv("ZEPHYR_NO_BANNER") != "" {
		return
	}

	banner := `
  ███████╗███████╗██████╗ ██╗  ██╗██╗   ██╗██████╗ 
  ╚══███╔╝██╔════╝██╔══██╗██║  ██║╚██╗ ██╔╝██╔══██╗
    ███╔╝ █████╗  ██████╔╝███████║ ╚████╔╝ ██████╔╝
   ███╔╝  ██╔══╝  ██╔═══╝ ██╔══██║  ╚██╔╝  ██╔══██╗
  ███████╗███████╗██║     ██║  ██║   ██║   ██║  ██║
  ╚══════╝╚══════╝╚═╝     ╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝`

	fmt.Printf("%s%s%s\n", ColorCyan, banner, ColorReset)
	fmt.Printf("  %s%s⚡ %s%s — %s\n", ColorBold, ColorWhite, ProjectName, ColorReset, Tagline)
	fmt.Printf("  %sAuthor:%s %s%s%s | %sRuntime:%s 100%% Go Standard Library (Zero-Dep)\n", ColorGray, ColorReset, ColorCyan, Author, ColorReset, ColorGray, ColorReset)
	fmt.Printf("  %sPlatform:%s %s/%s | %sCores:%s %d | %sToolchain:%s %s\n",
		ColorGray, ColorReset, runtime.GOOS, runtime.GOARCH,
		ColorGray, ColorReset, runtime.NumCPU(),
		ColorGray, ColorReset, runtime.Version(),
	)
	fmt.Printf("  %s%s%s\n\n", ColorGray, strings.Repeat("─", 68), ColorReset)
}

// ============================================================================
// SECTION 1: DATA STRUCTURES & CONFIGURATION
// ============================================================================

type Config struct {
	DefaultTask string          `json:"default,omitempty"`
	Workspaces  []string        `json:"workspaces,omitempty"`
	Tasks       map[string]Task `json:"tasks"`
}

type Task struct {
	Name        string   `json:"-"`
	Package     string   `json:"-"`
	Command     string   `json:"command"`
	Inputs      []string `json:"inputs"`
	Outputs     []string `json:"outputs"`
	DependsOn   []string `json:"depends_on"`
	EnvVars     []string `json:"env_vars"`
	Cwd         string   `json:"cwd,omitempty"`
	Timeout     string   `json:"timeout,omitempty"`
	Retries     int      `json:"retries,omitempty"`
	Weight      int      `json:"weight,omitempty"` // For weighted resource pool (default 1)
	Shell       string   `json:"shell,omitempty"`  // "powershell", "cmd", "bash", "sh"
	SecretKey   string   `json:"secret_key,omitempty"`
	CleanOutput bool     `json:"clean_output,omitempty"` // Clean outputs before rerun
}

type TaskManifest struct {
	TaskName     string            `json:"task_name"`
	Command      string            `json:"command"`
	Hash         string            `json:"hash"`
	FileHashes   map[string]string `json:"file_hashes"`
	EnvVars      map[string]string `json:"env_vars"`
	DepHashes    map[string]string `json:"dep_hashes"`
	OutputHashes map[string]string `json:"output_hashes"`
	HMAC         string            `json:"hmac,omitempty"`
	Timestamp    time.Time         `json:"timestamp"`
}

type CacheEntry struct {
	Stdout             string            `json:"stdout"`
	Stderr             string            `json:"stderr"`
	ExitCode           int               `json:"exit_code"`
	OutputHashes       map[string]string `json:"output_hashes"`
	Timestamp          time.Time         `json:"timestamp"`
	OriginalDurationMs int64             `json:"original_duration_ms"`
	LastUsed           time.Time         `json:"last_used"`
	HMAC               string            `json:"hmac,omitempty"`
}

type TaskResult struct {
	TaskName         string        `json:"task_name"`
	Status           string        `json:"status"` // "CACHED", "EXECUTED", "FAILED", "SKIPPED"
	Duration         time.Duration `json:"duration"`
	OriginalDuration time.Duration `json:"original_duration"`
	Hash             string        `json:"hash"`
	ExitCode         int           `json:"exit_code"`
	Why              string        `json:"why,omitempty"`
	Error            string        `json:"error,omitempty"`
	Stdout           string        `json:"stdout,omitempty"`
	Stderr           string        `json:"stderr,omitempty"`
	ProvenanceJSON   string        `json:"provenance,omitempty"`
}

type PipelineSummary struct {
	TotalTasks       int           `json:"total_tasks"`
	CachedTasks      int           `json:"cached_tasks"`
	ExecutedTasks    int           `json:"executed_tasks"`
	FailedTasks      int           `json:"failed_tasks"`
	TotalDuration    time.Duration `json:"total_duration"`
	SavedComputeTime time.Duration `json:"saved_compute_time"`
	TimeSavedPercent float64       `json:"time_saved_percent"`
	Results          []TaskResult  `json:"results"`
}

// ============================================================================
// SECTION 2: CONFIG DISCOVERY & WORKSPACE ROOT TRAVERSAL
// ============================================================================

func FindConfigRoot(startDir, explicitConfig string) (string, string, error) {
	targetFilename := DefaultConfig
	if explicitConfig != "" {
		if filepath.IsAbs(explicitConfig) {
			if _, err := os.Stat(explicitConfig); err == nil {
				return filepath.Dir(explicitConfig), explicitConfig, nil
			}
			return "", "", fmt.Errorf("config file '%s' not found", explicitConfig)
		}
		targetFilename = filepath.Base(explicitConfig)
	}

	curr := startDir
	for {
		candidate := filepath.Join(curr, targetFilename)
		if _, err := os.Stat(candidate); err == nil {
			return curr, candidate, nil
		}

		parent := filepath.Dir(curr)
		if parent == curr {
			break
		}
		curr = parent
	}

	if explicitConfig != "" && explicitConfig != DefaultConfig {
		return "", "", fmt.Errorf("config file '%s' not found", explicitConfig)
	}

	return startDir, filepath.Join(startDir, DefaultConfig), nil
}

func LoadConfig(path string) (*Config, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("failed to read config file '%s': %w", path, err)
	}

	var cfg Config
	if err := json.Unmarshal(data, &cfg); err != nil {
		return nil, fmt.Errorf("failed to parse JSON in '%s': %w", path, err)
	}

	if cfg.Tasks == nil {
		cfg.Tasks = make(map[string]Task)
	}

	// Multi-package Monorepo Discovery
	if len(cfg.Workspaces) > 0 {
		rootDir := filepath.Dir(path)
		for _, wsPattern := range cfg.Workspaces {
			matches, _ := filepath.Glob(filepath.Join(rootDir, wsPattern))
			for _, match := range matches {
				info, err := os.Stat(match)
				if err == nil && info.IsDir() {
					childConfig := filepath.Join(match, DefaultConfig)
					if _, err := os.Stat(childConfig); err == nil {
						childData, err := os.ReadFile(childConfig)
						if err == nil {
							var subCfg Config
							if json.Unmarshal(childData, &subCfg) == nil {
								pkgName := filepath.Base(match)
								for taskName, t := range subCfg.Tasks {
									scopedName := fmt.Sprintf("%s#%s", pkgName, taskName)
									t.Package = pkgName
									if t.Cwd == "" {
										rel, _ := filepath.Rel(rootDir, match)
										t.Cwd = rel
									}
									var scopedDeps []string
									for _, d := range t.DependsOn {
										if strings.Contains(d, "#") {
											scopedDeps = append(scopedDeps, d)
										} else {
											scopedDeps = append(scopedDeps, fmt.Sprintf("%s#%s", pkgName, d))
										}
									}
									t.DependsOn = scopedDeps
									cfg.Tasks[scopedName] = t
								}
							}
						}
					}
				}
			}
		}
	}

	for name, task := range cfg.Tasks {
		task.Name = name
		if task.Weight <= 0 {
			task.Weight = 1
		}
		cfg.Tasks[name] = task
	}

	return &cfg, nil
}

// ============================================================================
// SECTION 3: SECURITY & SANITIZATION JAIL
// ============================================================================

func ValidateSafePath(baseDir, targetPath string) (string, error) {
	absBase, err := filepath.Abs(baseDir)
	if err != nil {
		return "", fmt.Errorf("invalid base directory: %w", err)
	}

	absTarget, err := filepath.Abs(filepath.Join(absBase, targetPath))
	if err != nil {
		return "", fmt.Errorf("invalid target path: %w", err)
	}

	rel, err := filepath.Rel(absBase, absTarget)
	if err != nil || strings.HasPrefix(rel, "..") || strings.HasPrefix(rel, "/..") || strings.HasPrefix(rel, "\\..") {
		return "", fmt.Errorf("security violation: path '%s' escapes workspace boundary '%s'", targetPath, absBase)
	}

	return absTarget, nil
}

// ============================================================================
// SECTION 4: REAL-TIME SECRETS REDACTION STREAM ENGINE
// ============================================================================

var secretPatterns = []*regexp.Regexp{
	regexp.MustCompile(`(?i)(?:bearer\s+[A-Za-z0-9_\-\.]{16,})`),
	regexp.MustCompile(`(?i)(?:ghp_[A-Za-z0-9]{36,})`),
	regexp.MustCompile(`(?i)(?:sk_live_[A-Za-z0-9]{24,})`),
	regexp.MustCompile(`(?i)(?:AKIA[0-9A-Z]{16})`),
	regexp.MustCompile(`(?i)(?:(?:key|token|secret|password|passwd|auth)[\s:=]+['"]?([A-Za-z0-9_\-/\+=]{8,})['"]?)`),
}

type RedactingWriter struct {
	underlying io.Writer
	mu         sync.Mutex
}

func NewRedactingWriter(w io.Writer) *RedactingWriter {
	return &RedactingWriter{underlying: w}
}

func (rw *RedactingWriter) Write(p []byte) (n int, err error) {
	rw.mu.Lock()
	defer rw.mu.Unlock()

	redacted := RedactSecrets(string(p))
	_, err = rw.underlying.Write([]byte(redacted))
	return len(p), err
}

func RedactSecrets(input string) string {
	result := input
	for _, pattern := range secretPatterns {
		result = pattern.ReplaceAllStringFunc(result, func(match string) string {
			if strings.Contains(match, ":") || strings.Contains(match, "=") {
				parts := regexp.MustCompile(`[:=]`).Split(match, 2)
				if len(parts) == 2 {
					return parts[0] + "=***REDACTED***"
				}
			}
			return "***REDACTED***"
		})
	}
	return result
}

// ============================================================================
// SECTION 5: CRYPTOGRAPHIC HMAC-SHA256 SIGNING & ANTI-TAMPER
// ============================================================================

type CacheSignaturePayload struct {
	TaskName     string            `json:"task_name"`
	Command      string            `json:"command"`
	InputHash    string            `json:"input_hash"`
	OutputHashes map[string]string `json:"output_hashes"`
	StdoutHash   string            `json:"stdout_hash"`
	ExitCode     int               `json:"exit_code"`
}

func GenerateHMAC(secretKey []byte, payload CacheSignaturePayload) string {
	mac := hmac.New(sha256.New, secretKey)
	data, _ := json.Marshal(payload)
	mac.Write(data)
	return hex.EncodeToString(mac.Sum(nil))
}

func VerifyHMAC(secretKey []byte, payload CacheSignaturePayload, expectedSig string) bool {
	if expectedSig == "" {
		return false
	}
	expectedBytes, err := hex.DecodeString(expectedSig)
	if err != nil {
		return false
	}
	mac := hmac.New(sha256.New, secretKey)
	data, _ := json.Marshal(payload)
	mac.Write(data)
	actualBytes := mac.Sum(nil)
	return hmac.Equal(actualBytes, expectedBytes)
}

// ============================================================================
// SECTION 6: SLSA v1.0 & IN-TOTO BUILD PROVENANCE GENERATOR
// ============================================================================

type SLSAStatement struct {
	Type          string          `json:"_type"`
	Subject       []SLSASubject   `json:"subject"`
	PredicateType string          `json:"predicateType"`
	Predicate     SLSAPredicateV1 `json:"predicate"`
}

type SLSASubject struct {
	Name   string            `json:"name"`
	Digest map[string]string `json:"digest"`
}

type SLSAPredicateV1 struct {
	BuildDefinition SLSABuildDefinition `json:"buildDefinition"`
	RunDetails      SLSARunDetails      `json:"runDetails"`
}

type SLSABuildDefinition struct {
	BuildType            string               `json:"buildType"`
	ExternalParameters   map[string]string    `json:"externalParameters"`
	InternalParameters   map[string]string    `json:"internalParameters"`
	ResolvedDependencies []SLSAResolvedDep    `json:"resolvedDependencies"`
}

type SLSAResolvedDep struct {
	Name   string            `json:"name"`
	Digest map[string]string `json:"digest"`
}

type SLSARunDetails struct {
	Builder  SLSABuilder   `json:"builder"`
	Metadata SLSAMetadata  `json:"metadata"`
}

type SLSABuilder struct {
	ID      string            `json:"id"`
	Version map[string]string `json:"version"`
}

type SLSAMetadata struct {
	InvocationID string    `json:"invocationId"`
	StartedOn    time.Time `json:"startedOn"`
	FinishedOn   time.Time `json:"finishedOn"`
}

func GenerateProvenance(
	task Task,
	inputHashes map[string]string,
	outputHashes map[string]string,
	startedOn, finishedOn time.Time,
	invocationID string,
) (string, error) {
	var subjects []SLSASubject
	for file, hash := range outputHashes {
		subjects = append(subjects, SLSASubject{
			Name: file,
			Digest: map[string]string{
				"sha256": hash,
			},
		})
	}

	var resolvedDeps []SLSAResolvedDep
	for file, hash := range inputHashes {
		resolvedDeps = append(resolvedDeps, SLSAResolvedDep{
			Name: file,
			Digest: map[string]string{
				"sha256": hash,
			},
		})
	}

	gitCommit := "unknown"
	if out, err := exec.Command("git", "rev-parse", "HEAD").Output(); err == nil {
		gitCommit = strings.TrimSpace(string(out))
	}

	stmt := SLSAStatement{
		Type:          "https://in-toto.io/Statement/v1",
		Subject:       subjects,
		PredicateType: "https://slsa.dev/provenance/v1",
		Predicate: SLSAPredicateV1{
			BuildDefinition: SLSABuildDefinition{
				BuildType: "https://github.com/hackathon-raptors/zero_depen/zephyr@v2",
				ExternalParameters: map[string]string{
					"task":       task.Name,
					"command":    task.Command,
					"git_commit": gitCommit,
				},
				InternalParameters: map[string]string{
					"go_os":   runtime.GOOS,
					"go_arch": runtime.GOARCH,
					"go_ver":  runtime.Version(),
				},
				ResolvedDependencies: resolvedDeps,
			},
			RunDetails: SLSARunDetails{
				Builder: SLSABuilder{
					ID: "https://github.com/hackathon-raptors/zero_depen/zephyr",
					Version: map[string]string{
						"zephyr": Version,
					},
				},
				Metadata: SLSAMetadata{
					InvocationID: invocationID,
					StartedOn:    startedOn.UTC(),
					FinishedOn:   finishedOn.UTC(),
				},
			},
		},
	}

	data, err := json.MarshalIndent(stmt, "", "  ")
	if err != nil {
		return "", err
	}
	return string(data), nil
}

// ============================================================================
// SECTION 7: DIRECTED ACYCLIC GRAPH (DAG) & 3-COLOR DFS CYCLE DETECTOR
// ============================================================================

type DAGNode struct {
	Task         Task
	Dependencies []*DAGNode
	Dependents   []*DAGNode
}

type DAG struct {
	Nodes map[string]*DAGNode
}

func BuildDAG(cfg *Config) (*DAG, error) {
	dag := &DAG{Nodes: make(map[string]*DAGNode)}

	for name, task := range cfg.Tasks {
		dag.Nodes[name] = &DAGNode{
			Task:         task,
			Dependencies: []*DAGNode{},
			Dependents:   []*DAGNode{},
		}
	}

	for name, node := range dag.Nodes {
		for _, depName := range node.Task.DependsOn {
			depNode, exists := dag.Nodes[depName]
			if !exists {
				suggestions := SuggestSimilarTask(depName, GetAllTaskNames(cfg))
				errMsg := fmt.Sprintf("task '%s' depends on unknown task '%s'", name, depName)
				if len(suggestions) > 0 {
					errMsg += fmt.Sprintf(" (did you mean: %s?)", strings.Join(suggestions, ", "))
				}
				return nil, errors.New(errMsg)
			}
			node.Dependencies = append(node.Dependencies, depNode)
			depNode.Dependents = append(depNode.Dependents, node)
		}
	}

	if err := DetectCycles(dag); err != nil {
		return nil, err
	}

	return dag, nil
}

func DetectCycles(dag *DAG) error {
	const (
		white = 0 // Unvisited
		gray  = 1 // Currently visiting
		black = 2 // Fully visited
	)

	visited := make(map[string]int)
	parent := make(map[string]string)

	var dfs func(nodeName string) error
	dfs = func(nodeName string) error {
		visited[nodeName] = gray

		for _, dep := range dag.Nodes[nodeName].Dependencies {
			depName := dep.Task.Name
			if visited[depName] == gray {
				cyclePath := []string{depName, nodeName}
				curr := nodeName
				for curr != depName && curr != "" {
					curr = parent[curr]
					if curr != "" {
						cyclePath = append([]string{curr}, cyclePath...)
					}
				}
				return fmt.Errorf("cyclic dependency detected: %s", strings.Join(cyclePath, " -> "))
			}
			if visited[depName] == white {
				parent[depName] = nodeName
				if err := dfs(depName); err != nil {
					return err
				}
			}
		}

		visited[nodeName] = black
		return nil
	}

	var nodeNames []string
	for name := range dag.Nodes {
		nodeNames = append(nodeNames, name)
	}
	sort.Strings(nodeNames)

	for _, name := range nodeNames {
		if visited[name] == white {
			if err := dfs(name); err != nil {
				return err
			}
		}
	}

	return nil
}

func GetExecutionBatches(dag *DAG, targetTasks []string) ([][]string, error) {
	needed := make(map[string]bool)

	if len(targetTasks) == 0 {
		for name := range dag.Nodes {
			needed[name] = true
		}
	} else {
		var collectDeps func(string)
		collectDeps = func(name string) {
			if needed[name] {
				return
			}
			needed[name] = true
			if node, ok := dag.Nodes[name]; ok {
				for _, dep := range node.Dependencies {
					collectDeps(dep.Task.Name)
				}
			}
		}
		for _, target := range targetTasks {
			if _, ok := dag.Nodes[target]; !ok {
				return nil, fmt.Errorf("target task '%s' not found", target)
			}
			collectDeps(target)
		}
	}

	inDegree := make(map[string]int)
	for name := range needed {
		count := 0
		for _, dep := range dag.Nodes[name].Dependencies {
			if needed[dep.Task.Name] {
				count++
			}
		}
		inDegree[name] = count
	}

	var levels [][]string
	for {
		var currentLevel []string
		for name, deg := range inDegree {
			if deg == 0 {
				currentLevel = append(currentLevel, name)
			}
		}

		if len(currentLevel) == 0 {
			break
		}

		sort.Strings(currentLevel)
		levels = append(levels, currentLevel)

		for _, name := range currentLevel {
			delete(inDegree, name)
			for _, dep := range dag.Nodes[name].Dependents {
				if needed[dep.Task.Name] {
					inDegree[dep.Task.Name]--
				}
			}
		}
	}

	if len(inDegree) > 0 {
		return nil, errors.New("unresolved cycle or dependency in DAG")
	}

	return levels, nil
}

// ============================================================================
// SECTION 8: STREAMING GLOBBING, SHA-256 HASHING & EARLY PRUNING
// ============================================================================

var ignoredDirs = map[string]bool{
	".git":         true,
	".taskcache":   true,
	"node_modules": true,
	"vendor":       true,
	"dist":         true,
	"build":        true,
	".cache":       true,
	".hg":          true,
	".svn":         true,
}

func MatchGlobPatterns(patterns []string) ([]string, error) {
	var matchedFiles []string
	seen := make(map[string]bool)
	visitedDirs := make(map[string]bool)

	for _, pattern := range patterns {
		pattern = filepath.ToSlash(filepath.Clean(pattern))

		if !strings.Contains(pattern, "*") && !strings.Contains(pattern, "?") {
			if info, err := os.Stat(pattern); err == nil && !info.IsDir() {
				if !seen[pattern] {
					seen[pattern] = true
					matchedFiles = append(matchedFiles, pattern)
				}
			}
			continue
		}

		// Streaming directory walk with early pruning
		err := filepath.WalkDir(".", func(path string, d os.DirEntry, err error) error {
			if err != nil {
				return nil
			}

			slashPath := filepath.ToSlash(path)
			baseName := d.Name()

			if d.IsDir() {
				if path != "." {
					if ignoredDirs[baseName] {
						return filepath.SkipDir
					}
					// Avoid cyclic symlink infinite loops
					absDir, _ := filepath.Abs(path)
					if visitedDirs[absDir] {
						return filepath.SkipDir
					}
					visitedDirs[absDir] = true
				}
				return nil
			}

			if matchGlob(pattern, slashPath) {
				if !seen[slashPath] {
					seen[slashPath] = true
					matchedFiles = append(matchedFiles, slashPath)
				}
			}

			return nil
		})

		if err != nil {
			return nil, err
		}
	}

	sort.Strings(matchedFiles)
	return matchedFiles, nil
}

func matchGlob(pattern, path string) bool {
	pattern = filepath.ToSlash(pattern)
	path = filepath.ToSlash(path)

	if pattern == path {
		return true
	}

	if strings.Contains(pattern, "**") {
		parts := strings.Split(pattern, "**")
		if len(parts) == 2 {
			prefix := strings.TrimSuffix(parts[0], "/")
			suffix := strings.TrimPrefix(parts[1], "/")

			if prefix != "" && !strings.HasPrefix(path, prefix) {
				return false
			}

			remaining := path
			if prefix != "" {
				remaining = strings.TrimPrefix(path, prefix)
				remaining = strings.TrimPrefix(remaining, "/")
			}

			if suffix == "" {
				return true
			}

			if strings.HasPrefix(suffix, "*") {
				ext := strings.TrimPrefix(suffix, "*")
				return strings.HasSuffix(remaining, ext)
			}

			if matched, _ := filepath.Match(suffix, remaining); matched {
				return true
			}
			if matched, _ := filepath.Match(suffix, filepath.Base(remaining)); matched {
				return true
			}
			return strings.HasSuffix(remaining, suffix)
		}
	}

	if matched, _ := filepath.Match(pattern, path); matched {
		return true
	}
	if matched, _ := filepath.Match(pattern, filepath.Base(path)); matched {
		return true
	}

	return false
}

func ComputeFileHash(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer f.Close()

	hasher := sha256.New()
	if _, err := io.Copy(hasher, f); err != nil {
		return "", err
	}

	return hex.EncodeToString(hasher.Sum(nil)), nil
}

func ComputeTaskHash(
	task Task,
	fileHashes map[string]string,
	envVars map[string]string,
	depHashes map[string]string,
) string {
	hasher := sha256.New()

	hasher.Write([]byte("task_name:" + task.Name + "\n"))
	hasher.Write([]byte("command:" + task.Command + "\n"))
	hasher.Write([]byte("cwd:" + task.Cwd + "\n"))
	hasher.Write([]byte("shell:" + task.Shell + "\n"))

	var fileKeys []string
	for k := range fileHashes {
		fileKeys = append(fileKeys, k)
	}
	sort.Strings(fileKeys)
	for _, k := range fileKeys {
		hasher.Write([]byte(fmt.Sprintf("file:%s:%s\n", k, fileHashes[k])))
	}

	var envKeys []string
	for k := range envVars {
		envKeys = append(envKeys, k)
	}
	sort.Strings(envKeys)
	for _, k := range envKeys {
		hasher.Write([]byte(fmt.Sprintf("env:%s:%s\n", k, envVars[k])))
	}

	var depKeys []string
	for k := range depHashes {
		depKeys = append(depKeys, k)
	}
	sort.Strings(depKeys)
	for _, k := range depKeys {
		hasher.Write([]byte(fmt.Sprintf("dep:%s:%s\n", k, depHashes[k])))
	}

	var outputPatterns []string
	outputPatterns = append(outputPatterns, task.Outputs...)
	sort.Strings(outputPatterns)
	for _, out := range outputPatterns {
		hasher.Write([]byte(fmt.Sprintf("output_pattern:%s\n", out)))
	}

	return hex.EncodeToString(hasher.Sum(nil))
}

// ============================================================================
// SECTION 9: TWO-TIER CONTENT-ADDRESSABLE STORAGE (CAS) WITH HARDLINKS
// ============================================================================

type CASStore struct {
	rootDir string
	mu      sync.RWMutex
}

func NewCASStore(rootDir string) *CASStore {
	return &CASStore{rootDir: rootDir}
}

func (cas *CASStore) StoreBlob(srcPath string) (string, error) {
	cas.mu.Lock()
	defer cas.mu.Unlock()

	hash, err := ComputeFileHash(srcPath)
	if err != nil {
		return "", err
	}

	targetPath := filepath.Join(cas.rootDir, hash)
	if _, err := os.Stat(targetPath); err == nil {
		return hash, nil
	}

	_ = os.MkdirAll(cas.rootDir, 0755)

	srcFile, err := os.Open(srcPath)
	if err != nil {
		return "", err
	}
	defer srcFile.Close()

	tmpPath := fmt.Sprintf("%s.tmp.%d", targetPath, time.Now().UnixNano())
	tmpFile, err := os.Create(tmpPath)
	if err != nil {
		return "", err
	}

	if _, err := io.Copy(tmpFile, srcFile); err != nil {
		tmpFile.Close()
		_ = os.Remove(tmpPath)
		return "", err
	}
	tmpFile.Close()

	if err := os.Rename(tmpPath, targetPath); err != nil {
		_ = os.Remove(tmpPath)
		return "", err
	}

	return hash, nil
}

func (cas *CASStore) RestoreBlob(hash, destPath string) error {
	cas.mu.RLock()
	defer cas.mu.RUnlock()

	blobPath := filepath.Join(cas.rootDir, hash)
	if _, err := os.Stat(blobPath); err != nil {
		return fmt.Errorf("CAS object '%s' not found: %w", hash, err)
	}

	_ = os.MkdirAll(filepath.Dir(destPath), 0755)
	_ = os.Remove(destPath)

	// Attempt zero-copy hardlink first
	if err := os.Link(blobPath, destPath); err == nil {
		return nil
	}

	// Fallback to streaming copy across filesystem partitions
	srcFile, err := os.Open(blobPath)
	if err != nil {
		return err
	}
	defer srcFile.Close()

	destFile, err := os.Create(destPath)
	if err != nil {
		return err
	}
	defer destFile.Close()

	_, err = io.Copy(destFile, srcFile)
	return err
}

func StoreOutputBlobs(cas *CASStore, outputHashes map[string]string) error {
	for file := range outputHashes {
		if _, err := cas.StoreBlob(file); err != nil {
			return err
		}
	}
	return nil
}

func RestoreOutputBlobs(cas *CASStore, outputHashes map[string]string) error {
	for file, hash := range outputHashes {
		if err := cas.RestoreBlob(hash, file); err != nil {
			return err
		}
	}
	return nil
}

func PurgeDeclaredOutputs(outputs []string) {
	matched, _ := MatchGlobPatterns(outputs)
	for _, f := range matched {
		_ = os.Remove(f)
	}
}

// ============================================================================
// SECTION 10: INTELLIGENT '--WHY' CACHE MISS DIAGNOSTIC ENGINE
// ============================================================================

func ExplainCacheMiss(
	task Task,
	currFileHashes map[string]string,
	currEnvVars map[string]string,
	currDepHashes map[string]string,
) string {
	manifestPath := filepath.Join(CacheDir, task.Name+".manifest.json")
	data, err := os.ReadFile(manifestPath)
	if err != nil {
		return "Initial execution (no previous cache manifest found)"
	}

	var prev TaskManifest
	if err := json.Unmarshal(data, &prev); err != nil {
		return "Previous cache manifest corrupted"
	}

	if prev.Command != task.Command {
		return fmt.Sprintf("Command changed: '%s' -> '%s'", prev.Command, task.Command)
	}

	for k, currHash := range currFileHashes {
		prevHash, exists := prev.FileHashes[k]
		if !exists {
			return fmt.Sprintf("New input file added: %s", k)
		}
		if prevHash != currHash {
			return fmt.Sprintf("Input file modified: %s (SHA256: %s -> %s)", k, truncateHash(prevHash), truncateHash(currHash))
		}
	}

	for k := range prev.FileHashes {
		if _, exists := currFileHashes[k]; !exists {
			return fmt.Sprintf("Input file deleted: %s", k)
		}
	}

	for k, currVal := range currEnvVars {
		prevVal, exists := prev.EnvVars[k]
		if !exists {
			return fmt.Sprintf("Environment variable added: %s", k)
		}
		if prevVal != currVal {
			return fmt.Sprintf("Environment variable changed: %s", k)
		}
	}

	for k, currDepHash := range currDepHashes {
		prevDepHash, exists := prev.DepHashes[k]
		if !exists {
			return fmt.Sprintf("Upstream dependency added: %s", k)
		}
		if prevDepHash != currDepHash {
			return fmt.Sprintf("Upstream dependency '%s' rebuilt (Hash: %s -> %s)", k, truncateHash(prevDepHash), truncateHash(currDepHash))
		}
	}

	return "Input state hash mismatch"
}

// ============================================================================
// SECTION 11: DYNAMIC WEIGHTED WORKER POOL (OOM PROTECTION)
// ============================================================================

type WeightedPool struct {
	capacity  int
	available int
	mu        sync.Mutex
	cond      *sync.Cond
}

func NewWeightedPool(capacity int) *WeightedPool {
	if capacity <= 0 {
		capacity = runtime.NumCPU()
	}
	wp := &WeightedPool{
		capacity:  capacity,
		available: capacity,
	}
	wp.cond = sync.NewCond(&wp.mu)
	return wp
}

func (wp *WeightedPool) Acquire(weight int) {
	if weight <= 0 {
		weight = 1
	}
	if weight > wp.capacity {
		weight = wp.capacity
	}

	wp.mu.Lock()
	defer wp.mu.Unlock()

	for wp.available < weight {
		wp.cond.Wait()
	}
	wp.available -= weight
}

func (wp *WeightedPool) Release(weight int) {
	if weight <= 0 {
		weight = 1
	}
	if weight > wp.capacity {
		weight = wp.capacity
	}

	wp.mu.Lock()
	defer wp.mu.Unlock()

	wp.available += weight
	wp.cond.Broadcast()
}

// ============================================================================
// SECTION 12: LIVE TUI MULTI-TASK CONCURRENT PROGRESS SPINNER DASHBOARD
// ============================================================================

var spinnerFrames = []string{"⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"}

type TaskLiveState struct {
	Name      string
	Command   string
	Status    string // "RUNNING", "CACHED", "DONE", "FAIL"
	StartTime time.Time
	Duration  time.Duration
	Hash      string
}

type LiveProgressTracker struct {
	mu           sync.Mutex
	activeTasks  []*TaskLiveState
	taskIndexMap map[string]*TaskLiveState
	frameIdx     int
	isTTY        bool
	done         chan struct{}
	stopped      bool
}

func NewLiveProgressTracker() *LiveProgressTracker {
	return &LiveProgressTracker{
		taskIndexMap: make(map[string]*TaskLiveState),
		isTTY:        isTerminal(),
		done:         make(chan struct{}),
	}
}

func (t *LiveProgressTracker) StartTask(name, command, hash string) {
	t.mu.Lock()
	defer t.mu.Unlock()

	state := &TaskLiveState{
		Name:      name,
		Command:   command,
		Status:    "RUNNING",
		StartTime: time.Now(),
		Hash:      hash,
	}
	t.activeTasks = append(t.activeTasks, state)
	t.taskIndexMap[name] = state
}

func (t *LiveProgressTracker) FinishTask(name, status string, dur time.Duration) {
	t.mu.Lock()
	defer t.mu.Unlock()

	if state, ok := t.taskIndexMap[name]; ok {
		state.Status = status
		state.Duration = dur
	}
}

// ============================================================================
// SECTION 13: PROCESS EXECUTION & RETRY CONTROLLER
// ============================================================================

type TaskLogger struct {
	mu sync.Mutex
}

func (l *TaskLogger) Log(msg string) {
	l.mu.Lock()
	defer l.mu.Unlock()
	fmt.Println(msg)
}

func (l *TaskLogger) LogPrefixed(taskName, color, msg string) {
	l.mu.Lock()
	defer l.mu.Unlock()
	fmt.Printf("%s[%s]%s %s\n", color, taskName, ColorReset, msg)
}

func ExecuteTask(
	ctx context.Context,
	task Task,
	taskHash string,
	logger *TaskLogger,
	why bool,
	stream bool,
	cas *CASStore,
	passThrough []string,
) TaskResult {
	actionCachePath := filepath.Join(ActionCacheDir, taskHash+".json")
	os.MkdirAll(ActionCacheDir, 0755)

	// Check Action Cache (Two-Tier CAS)
	if data, err := os.ReadFile(actionCachePath); err == nil {
		var entry CacheEntry
		if json.Unmarshal(data, &entry) == nil {
			verified := true
			if task.SecretKey != "" {
				verified = VerifyHMAC([]byte(task.SecretKey), CacheSignaturePayload{
					TaskName:     task.Name,
					Command:      task.Command,
					InputHash:    taskHash,
					OutputHashes: entry.OutputHashes,
					StdoutHash:   fmt.Sprintf("%x", sha256.Sum256([]byte(entry.Stdout))),
					ExitCode:     entry.ExitCode,
				}, entry.HMAC)
			}

			if verified {
				entry.LastUsed = time.Now()
				updatedData, _ := json.Marshal(entry)
				_ = os.WriteFile(actionCachePath, updatedData, 0644)

				_ = RestoreOutputBlobs(cas, entry.OutputHashes)

				logger.Log(fmt.Sprintf("%s[%s]%s %s[CACHED]%s (Hash: %s)", ColorCyan, task.Name, ColorReset, ColorCyan, ColorReset, truncateHash(taskHash)))
				if entry.Stdout != "" {
					fmt.Print(entry.Stdout)
				}
				if entry.Stderr != "" {
					fmt.Fprint(os.Stderr, entry.Stderr)
				}

				return TaskResult{
					TaskName:         task.Name,
					Status:           "CACHED",
					Duration:         time.Millisecond,
					OriginalDuration: time.Duration(entry.OriginalDurationMs) * time.Millisecond,
					Hash:             taskHash,
					ExitCode:         entry.ExitCode,
					Stdout:           entry.Stdout,
					Stderr:           entry.Stderr,
				}
			}
		}
	}

	whyReason := ""
	if why {
		fileHashes := make(map[string]string)
		matched, _ := MatchGlobPatterns(task.Inputs)
		for _, f := range matched {
			if h, err := ComputeFileHash(f); err == nil {
				fileHashes[f] = h
			}
		}
		envVars := make(map[string]string)
		for _, envKey := range task.EnvVars {
			envVars[envKey] = os.Getenv(envKey)
		}
		whyReason = ExplainCacheMiss(task, fileHashes, envVars, nil)
	}

	if task.CleanOutput {
		PurgeDeclaredOutputs(task.Outputs)
	}

	maxAttempts := task.Retries + 1
	var lastErr error
	var stdoutBuf, stderrBuf bytes.Buffer

	for attempt := 1; attempt <= maxAttempts; attempt++ {
		stdoutBuf.Reset()
		stderrBuf.Reset()

		if attempt > 1 {
			logger.Log(fmt.Sprintf("%s[%s]%s %s[RETRY %d/%d]%s Retrying after failure...", ColorYellow, task.Name, ColorReset, ColorYellow, attempt, maxAttempts, ColorReset))
			time.Sleep(time.Duration(attempt*100) * time.Millisecond)
		} else {
			whyMsg := ""
			if why && whyReason != "" {
				whyMsg = fmt.Sprintf(" %s[Why: %s]%s", ColorYellow, whyReason, ColorReset)
			}
			logger.Log(fmt.Sprintf("%s[%s]%s %s[RUNNING]%s \"%s\" (Hash: %s)%s", ColorGreen, task.Name, ColorReset, ColorGreen, ColorReset, task.Command, truncateHash(taskHash), whyMsg))
		}

		var cmdCtx context.Context
		var cancel context.CancelFunc
		if task.Timeout != "" {
			if dur, err := time.ParseDuration(task.Timeout); err == nil {
				cmdCtx, cancel = context.WithTimeout(ctx, dur)
			}
		}
		if cmdCtx == nil {
			cmdCtx, cancel = context.WithCancel(ctx)
		}

		var cmd *exec.Cmd
		fullCommand := task.Command
		if len(passThrough) > 0 {
			fullCommand = fullCommand + " " + strings.Join(passThrough, " ")
		}

		shellType := task.Shell
		if shellType == "" {
			if runtime.GOOS == "windows" {
				shellType = "cmd"
			} else {
				shellType = "sh"
			}
		}

		switch shellType {
		case "powershell":
			cmd = exec.CommandContext(cmdCtx, "powershell", "-NoProfile", "-Command", fullCommand)
		case "cmd":
			cmd = exec.CommandContext(cmdCtx, "cmd.exe", "/c", fullCommand)
		case "bash":
			cmd = exec.CommandContext(cmdCtx, "bash", "-c", fullCommand)
		default:
			if runtime.GOOS == "windows" {
				cmd = exec.CommandContext(cmdCtx, "cmd.exe", "/c", fullCommand)
			} else {
				cmd = exec.CommandContext(cmdCtx, "sh", "-c", fullCommand)
			}
		}

		if task.Cwd != "" {
			cmd.Dir = task.Cwd
		}

		redactedStdout := NewRedactingWriter(&stdoutBuf)
		redactedStderr := NewRedactingWriter(&stderrBuf)

		startTime := time.Now()

		if stream {
			stdoutPipe, _ := cmd.StdoutPipe()
			stderrPipe, _ := cmd.StderrPipe()

			if err := cmd.Start(); err != nil {
				if cancel != nil {
					cancel()
				}
				lastErr = err
				continue
			}

			var wg sync.WaitGroup
			wg.Add(2)
			go func() {
				defer wg.Done()
				scanner := bufio.NewScanner(io.TeeReader(stdoutPipe, redactedStdout))
				for scanner.Scan() {
					logger.LogPrefixed(task.Name, ColorCyan, scanner.Text())
				}
			}()
			go func() {
				defer wg.Done()
				scanner := bufio.NewScanner(io.TeeReader(stderrPipe, redactedStderr))
				for scanner.Scan() {
					logger.LogPrefixed(task.Name, ColorRed, scanner.Text())
				}
			}()

			cmdErr := cmd.Wait()
			wg.Wait()
			if cancel != nil {
				cancel()
			}
			lastErr = cmdErr
		} else {
			cmd.Stdout = redactedStdout
			cmd.Stderr = redactedStderr
			lastErr = cmd.Run()
			if cancel != nil {
				cancel()
			}
		}

		duration := time.Since(startTime)
		exitCode := 0
		var taskErr error
		status := "EXECUTED"

		if lastErr != nil {
			status = "FAILED"
			var exitErr *exec.ExitError
			if errors.As(lastErr, &exitErr) {
				exitCode = exitErr.ExitCode()
			} else {
				exitCode = 1
			}
			taskErr = fmt.Errorf("task '%s' failed with exit code %d", task.Name, exitCode)
		}

		outputHashes := make(map[string]string)
		if exitCode == 0 {
			matchedOutputs, _ := MatchGlobPatterns(task.Outputs)
			for _, file := range matchedOutputs {
				if h, err := ComputeFileHash(file); err == nil {
					outputHashes[file] = h
				}
			}
		}

		if exitCode == 0 && taskErr == nil {
			hmacSig := ""
			if task.SecretKey != "" {
				hmacSig = GenerateHMAC([]byte(task.SecretKey), CacheSignaturePayload{
					TaskName:     task.Name,
					Command:      task.Command,
					InputHash:    taskHash,
					OutputHashes: outputHashes,
					StdoutHash:   fmt.Sprintf("%x", sha256.Sum256([]byte(stdoutBuf.String()))),
					ExitCode:     exitCode,
				})
			}

			// Store in CAS & Action Cache
			_ = StoreOutputBlobs(cas, outputHashes)

			entry := CacheEntry{
				Stdout:             stdoutBuf.String(),
				Stderr:             stderrBuf.String(),
				ExitCode:           exitCode,
				OutputHashes:       outputHashes,
				Timestamp:          time.Now(),
				OriginalDurationMs: duration.Milliseconds(),
				LastUsed:           time.Now(),
				HMAC:               hmacSig,
			}

			entryData, _ := json.Marshal(entry)
			tmpCachePath := fmt.Sprintf("%s.tmp.%d", actionCachePath, time.Now().UnixNano())
			if err := os.WriteFile(tmpCachePath, entryData, 0644); err == nil {
				_ = os.Rename(tmpCachePath, actionCachePath)
			}

			// Generate SLSA v1.0 Provenance Attestation
			inputHashes := make(map[string]string)
			matchedInputs, _ := MatchGlobPatterns(task.Inputs)
			for _, f := range matchedInputs {
				if h, err := ComputeFileHash(f); err == nil {
					inputHashes[f] = h
				}
			}
			provJSON, _ := GenerateProvenance(task, inputHashes, outputHashes, startTime, time.Now(), taskHash)

			logger.Log(fmt.Sprintf("%s[%s]%s %s[DONE]%s in %v", ColorGreen, task.Name, ColorReset, ColorGreen, ColorReset, duration.Round(time.Millisecond)))

			return TaskResult{
				TaskName:         task.Name,
				Status:           status,
				Duration:         duration,
				OriginalDuration: duration,
				Hash:             taskHash,
				ExitCode:         exitCode,
				Why:              whyReason,
				Stdout:           stdoutBuf.String(),
				Stderr:           stderrBuf.String(),
				ProvenanceJSON:   provJSON,
			}
		}

		if attempt == maxAttempts {
			logger.Log(fmt.Sprintf("%s[%s]%s %s[FAILED]%s in %v: %v", ColorRed, task.Name, ColorReset, ColorRed, ColorReset, duration.Round(time.Millisecond), lastErr))
			return TaskResult{
				TaskName:         task.Name,
				Status:           status,
				Duration:         duration,
				OriginalDuration: duration,
				Hash:             taskHash,
				ExitCode:         exitCode,
				Why:              whyReason,
				Error:            lastErr.Error(),
				Stdout:           stdoutBuf.String(),
				Stderr:           stderrBuf.String(),
			}
		}
	}

	return TaskResult{
		TaskName: task.Name,
		Status:   "FAILED",
		Error:    "unexpected execution state",
	}
}

// ============================================================================
// SECTION 14: PIPELINE ORCHESTRATOR & SUMMARY TABLE
// ============================================================================

func RunPipeline(
	ctx context.Context,
	cfg *Config,
	targets []string,
	parallel int,
	why bool,
	dryRun bool,
	stream bool,
	jsonOut bool,
	failFast bool,
	passThrough []string,
) (*PipelineSummary, error) {
	pipelineStart := time.Now()
	dag, err := BuildDAG(cfg)
	if err != nil {
		return nil, err
	}

	levels, err := GetExecutionBatches(dag, targets)
	if err != nil {
		return nil, err
	}

	if dryRun {
		fmt.Printf("%sDry-Run Mode: Execution Plan (%d Batches)%s\n", ColorCyan, len(levels), ColorReset)
		for i, level := range levels {
			fmt.Printf("Batch %d: [%s]\n", i+1, strings.Join(level, ", "))
		}
		return &PipelineSummary{}, nil
	}

	os.MkdirAll(CacheDir, 0755)
	os.MkdirAll(CASDir, 0755)
	os.MkdirAll(ActionCacheDir, 0755)

	casStore := NewCASStore(CASDir)
	logger := &TaskLogger{}
	summary := &PipelineSummary{}
	resultsMu := sync.Mutex{}
	taskHashes := make(map[string]string)
	hashesMu := sync.RWMutex{}

	pool := NewWeightedPool(parallel)

	for lvlIdx, level := range levels {
		var wg sync.WaitGroup
		levelErrChan := make(chan error, len(level))

		for _, taskName := range level {
			task := cfg.Tasks[taskName]
			wg.Add(1)

			go func(t Task) {
				defer wg.Done()
				pool.Acquire(t.Weight)
				defer pool.Release(t.Weight)

				matchedInputs, _ := MatchGlobPatterns(t.Inputs)
				inputFileHashes := make(map[string]string)
				for _, file := range matchedInputs {
					if h, err := ComputeFileHash(file); err == nil {
						inputFileHashes[file] = h
					}
				}

				envVars := make(map[string]string)
				for _, envKey := range t.EnvVars {
					envVars[envKey] = os.Getenv(envKey)
				}

				depHashes := make(map[string]string)
				hashesMu.RLock()
				for _, dep := range t.DependsOn {
					depHashes[dep] = taskHashes[dep]
				}
				hashesMu.RUnlock()

				taskHash := ComputeTaskHash(t, inputFileHashes, envVars, depHashes)
				hashesMu.Lock()
				taskHashes[t.Name] = taskHash
				hashesMu.Unlock()

				result := ExecuteTask(ctx, t, taskHash, logger, why, stream, casStore, passThrough)

				resultsMu.Lock()
				summary.Results = append(summary.Results, result)
				if result.Status == "CACHED" {
					summary.CachedTasks++
					saved := result.OriginalDuration - result.Duration
					if saved > 0 {
						summary.SavedComputeTime += saved
					}
				} else if result.Status == "EXECUTED" {
					summary.ExecutedTasks++
				} else if result.Status == "FAILED" {
					summary.FailedTasks++
				}
				resultsMu.Unlock()

				if result.Status == "FAILED" {
					levelErrChan <- fmt.Errorf("task '%s' failed", t.Name)
				}
			}(task)
		}

		wg.Wait()

		if len(levelErrChan) > 0 && failFast {
			return summary, <-levelErrChan
		}
		_ = lvlIdx
	}

	summary.TotalTasks = len(summary.Results)
	summary.TotalDuration = time.Since(pipelineStart)
	totalPotentialTime := summary.TotalDuration + summary.SavedComputeTime
	if totalPotentialTime > 0 {
		summary.TimeSavedPercent = (float64(summary.SavedComputeTime) / float64(totalPotentialTime)) * 100.0
	}

	if !jsonOut {
		PrintSummaryTable(summary)
	}

	return summary, nil
}

func PrintSummaryTable(s *PipelineSummary) {
	fmt.Println()
	w := tabwriter.NewWriter(os.Stdout, 0, 8, 2, ' ', 0)
	fmt.Fprintln(w, "Task\tStatus\tDuration\tOriginal Time\tTime Saved\tCache Key")
	fmt.Fprintln(w, "----\t------\t--------\t-------------\t----------\t---------")

	for _, r := range s.Results {
		statusColor := ColorGreen
		if r.Status == "FAILED" {
			statusColor = ColorRed
		} else if r.Status == "CACHED" {
			statusColor = ColorCyan
		}

		timeSavedStr := "-"
		if r.Status == "CACHED" {
			saved := r.OriginalDuration - r.Duration
			if saved > 0 {
				timeSavedStr = "+" + saved.Round(time.Millisecond).String()
			}
		}

		durStr := r.Duration.Round(time.Millisecond).String()
		origStr := r.OriginalDuration.Round(time.Millisecond).String()

		fmt.Fprintf(
			w,
			"%s\t%s%s%s\t%s\t%s\t%s\tsha256:%s\n",
			r.TaskName,
			statusColor, r.Status, ColorReset,
			durStr,
			origStr,
			timeSavedStr,
			truncateHash(r.Hash),
		)
	}
	w.Flush()

	fmt.Println(strings.Repeat("-", 78))
	fmt.Printf(
		"Summary : %s%d cached%s, %s%d executed%s, %s%d failed%s\n",
		ColorCyan, s.CachedTasks, ColorReset,
		ColorGreen, s.ExecutedTasks, ColorReset,
		ColorRed, s.FailedTasks, ColorReset,
	)
	fmt.Printf(
		"Duration: %s (Compute saved: %s / %.1f%%)\n",
		s.TotalDuration.Round(time.Millisecond),
		s.SavedComputeTime.Round(time.Millisecond),
		s.TimeSavedPercent,
	)
	fmt.Println(strings.Repeat("-", 78))
}

// ============================================================================
// SECTION 15: ZERO-DEPENDENCY BUILT-IN HTTP REMOTE CACHE SERVER
// ============================================================================

type RemoteCacheServer struct {
	port       int
	storageDir string
	authToken  string
	server     *http.Server
}

func NewRemoteCacheServer(port int, storageDir, authToken string) *RemoteCacheServer {
	return &RemoteCacheServer{
		port:       port,
		storageDir: storageDir,
		authToken:  authToken,
	}
}

func (s *RemoteCacheServer) Start() error {
	_ = os.MkdirAll(filepath.Join(s.storageDir, "ac"), 0755)
	_ = os.MkdirAll(filepath.Join(s.storageDir, "cas"), 0755)

	mux := http.NewServeMux()
	mux.HandleFunc("/v1/ac/", s.authMiddleware(s.handleActionCache))
	mux.HandleFunc("/v1/cas/", s.authMiddleware(s.handleCAS))
	mux.HandleFunc("/healthz", s.handleHealthz)

	s.server = &http.Server{
		Addr:    fmt.Sprintf(":%d", s.port),
		Handler: mux,
	}

	return s.server.ListenAndServe()
}

func (s *RemoteCacheServer) authMiddleware(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if s.authToken != "" {
			authHeader := r.Header.Get("Authorization")
			expected := "Bearer " + s.authToken
			if authHeader != expected {
				http.Error(w, `{"error":"unauthorized"}`, http.StatusUnauthorized)
				return
			}
		}
		next(w, r)
	}
}

func (s *RemoteCacheServer) handleHealthz(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]string{"status": "ok", "time": time.Now().UTC().Format(time.RFC3339)})
}

func (s *RemoteCacheServer) handleActionCache(w http.ResponseWriter, r *http.Request) {
	actionHash := strings.TrimPrefix(r.URL.Path, "/v1/ac/")
	if len(actionHash) != 64 {
		http.Error(w, "invalid action hash", http.StatusBadRequest)
		return
	}
	targetPath := filepath.Join(s.storageDir, "ac", actionHash+".json")

	switch r.Method {
	case http.MethodGet:
		data, err := os.ReadFile(targetPath)
		if err != nil {
			http.Error(w, "cache miss", http.StatusNotFound)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write(data)

	case http.MethodPut:
		data, err := io.ReadAll(r.Body)
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		_ = os.MkdirAll(filepath.Dir(targetPath), 0755)
		_ = os.WriteFile(targetPath, data, 0644)
		w.WriteHeader(http.StatusCreated)

	default:
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
	}
}

func (s *RemoteCacheServer) handleCAS(w http.ResponseWriter, r *http.Request) {
	blobHash := strings.TrimPrefix(r.URL.Path, "/v1/cas/")
	if len(blobHash) != 64 {
		http.Error(w, "invalid blob hash", http.StatusBadRequest)
		return
	}
	targetPath := filepath.Join(s.storageDir, "cas", blobHash)

	switch r.Method {
	case http.MethodGet:
		f, err := os.Open(targetPath)
		if err != nil {
			http.Error(w, "blob not found", http.StatusNotFound)
			return
		}
		defer f.Close()
		w.Header().Set("Content-Type", "application/octet-stream")
		_, _ = io.Copy(w, f)

	case http.MethodPut:
		_ = os.MkdirAll(filepath.Dir(targetPath), 0755)
		hasher := sha256.New()
		tmpPath := fmt.Sprintf("%s.tmp.%d", targetPath, time.Now().UnixNano())
		f, err := os.Create(tmpPath)
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		mw := io.MultiWriter(f, hasher)
		_, err = io.Copy(mw, r.Body)
		f.Close()

		if err != nil {
			_ = os.Remove(tmpPath)
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}

		actualHash := hex.EncodeToString(hasher.Sum(nil))
		if actualHash != blobHash {
			_ = os.Remove(tmpPath)
			http.Error(w, "hash verification failed", http.StatusBadRequest)
			return
		}

		_ = os.Rename(tmpPath, targetPath)
		w.WriteHeader(http.StatusCreated)

	default:
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
	}
}

// ============================================================================
// SECTION 16: GIT-AWARE AFFECTED SUB-DAGS
// ============================================================================

func GetGitChangedFiles(baseRef string) ([]string, error) {
	if baseRef == "" {
		baseRef = "main"
	}

	cmd := exec.Command("git", "diff", "--name-only", baseRef+"...HEAD")
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	if err := cmd.Run(); err != nil {
		cmdFallback := exec.Command("git", "diff", "--name-only", baseRef)
		stdout.Reset()
		cmdFallback.Stdout = &stdout
		if errFallback := cmdFallback.Run(); errFallback != nil {
			return nil, fmt.Errorf("git diff failed: %s: %w", stderr.String(), err)
		}
	}

	lines := strings.Split(stdout.String(), "\n")
	var files []string
	for _, line := range lines {
		trimmed := filepath.ToSlash(strings.TrimSpace(line))
		if trimmed != "" {
			files = append(files, trimmed)
		}
	}
	return files, nil
}

func ComputeAffectedTasks(
	tasks map[string][]string,
	dependentsMap map[string][]string,
	changedFiles []string,
	matcher func(pattern, path string) bool,
) []string {
	directAffected := make(map[string]bool)

	for taskName, inputGlobs := range tasks {
		for _, glob := range inputGlobs {
			matched := false
			for _, file := range changedFiles {
				if matcher(glob, file) {
					directAffected[taskName] = true
					matched = true
					break
				}
			}
			if matched {
				break
			}
		}
	}

	allAffected := make(map[string]bool)
	var visit func(t string)
	visit = func(t string) {
		if allAffected[t] {
			return
		}
		allAffected[t] = true
		for _, dep := range dependentsMap[t] {
			visit(dep)
		}
	}

	for t := range directAffected {
		visit(t)
	}

	var result []string
	for t := range allAffected {
		result = append(result, t)
	}
	sort.Strings(result)
	return result
}

// ============================================================================
// SECTION 17: 'ZEPHYR DOCTOR' WORKSPACE & SYSTEM DIAGNOSTIC ENGINE
// ============================================================================

type DiagnosticResult struct {
	Category string
	Status   string // "OK", "WARN", "FAIL"
	Message  string
}

func RunDoctorCommand(rootDir string, explicitConfig string) int {
	fmt.Printf("%s[ZEPHYR DOCTOR]%s Auditing workspace health & system integrity...\n\n", ColorCyan, ColorReset)

	var diagnostics []DiagnosticResult

	// 1. Config Validation
	_, configPath, err := FindConfigRoot(rootDir, explicitConfig)
	if err != nil {
		diagnostics = append(diagnostics, DiagnosticResult{
			Category: "Configuration",
			Status:   "FAIL",
			Message:  fmt.Sprintf("Failed to locate tasks.json: %v", err),
		})
	} else {
		cfg, err := LoadConfig(configPath)
		if err != nil {
			diagnostics = append(diagnostics, DiagnosticResult{
				Category: "Configuration",
				Status:   "FAIL",
				Message:  fmt.Sprintf("tasks.json syntax error: %v", err),
			})
		} else {
			diagnostics = append(diagnostics, DiagnosticResult{
				Category: "Configuration",
				Status:   "OK",
				Message:  fmt.Sprintf("Loaded tasks.json with %d defined tasks", len(cfg.Tasks)),
			})

			// 2. DAG Cycle Detection
			if _, err := BuildDAG(cfg); err != nil {
				diagnostics = append(diagnostics, DiagnosticResult{
					Category: "Dependency Graph",
					Status:   "FAIL",
					Message:  fmt.Sprintf("Cycle or invalid dependency detected: %v", err),
				})
			} else {
				diagnostics = append(diagnostics, DiagnosticResult{
					Category: "Dependency Graph",
					Status:   "OK",
					Message:  "DAG is acyclic and topologically valid",
				})
			}
		}
	}

	// 3. Cache Storage Health
	if info, err := os.Stat(CacheDir); err == nil && info.IsDir() {
		var cacheCount int
		var cacheSize int64
		_ = filepath.WalkDir(CacheDir, func(p string, d os.DirEntry, err error) error {
			if err == nil && !d.IsDir() {
				cacheCount++
				if fi, err := d.Info(); err == nil {
					cacheSize += fi.Size()
				}
			}
			return nil
		})
		diagnostics = append(diagnostics, DiagnosticResult{
			Category: "Cache Storage",
			Status:   "OK",
			Message:  fmt.Sprintf(".taskcache active (%d entries, %s)", cacheCount, formatByteSize(cacheSize)),
		})
	} else {
		diagnostics = append(diagnostics, DiagnosticResult{
			Category: "Cache Storage",
			Status:   "OK",
			Message:  ".taskcache clean (will be initialized on first run)",
		})
	}

	// 4. Git Repository Hygiene
	if _, err := exec.LookPath("git"); err == nil {
		if _, err := os.Stat(".git"); err == nil {
			diagnostics = append(diagnostics, DiagnosticResult{
				Category: "Git Integration",
				Status:   "OK",
				Message:  "Git repository detected; 'affected' command available",
			})
		} else {
			diagnostics = append(diagnostics, DiagnosticResult{
				Category: "Git Integration",
				Status:   "WARN",
				Message:  "Not in a git repository; 'affected' command disabled",
			})
		}
	} else {
		diagnostics = append(diagnostics, DiagnosticResult{
			Category: "Git Integration",
			Status:   "WARN",
			Message:  "Git not found in PATH",
		})
	}

	// 5. System Resources
	var mem runtime.MemStats
	runtime.ReadMemStats(&mem)
	diagnostics = append(diagnostics, DiagnosticResult{
		Category: "System Resources",
		Status:   "OK",
		Message:  fmt.Sprintf("%d CPU Cores | Go %s | %s/%s", runtime.NumCPU(), runtime.Version(), runtime.GOOS, runtime.GOARCH),
	})

	// Print Results
	w := tabwriter.NewWriter(os.Stdout, 0, 8, 2, ' ', 0)
	fmt.Fprintln(w, "Category\tStatus\tDetails")
	fmt.Fprintln(w, "--------\t------\t-------")

	failCount := 0
	for _, d := range diagnostics {
		statusColor := ColorGreen
		if d.Status == "FAIL" {
			statusColor = ColorRed
			failCount++
		} else if d.Status == "WARN" {
			statusColor = ColorYellow
		}
		fmt.Fprintf(w, "%s\t%s[%s]%s\t%s\n", d.Category, statusColor, d.Status, ColorReset, d.Message)
	}
	w.Flush()
	fmt.Println()

	if failCount > 0 {
		fmt.Printf("%s[DOCTOR RESULT] %d issue(s) detected. Please resolve them before running pipeline.%s\n", ColorRed, failCount, ColorReset)
		return 1
	}

	fmt.Printf("%s[DOCTOR RESULT] All systems operational. Workspace is ready for high-velocity builds!%s\n", ColorGreen, ColorReset)
	return 0
}

// ============================================================================
// SECTION 18: DEVELOPER UTILITIES, DOTENV PARSER & LEVENSHTEIN TYPO MATCHER
// ============================================================================

func LoadDotEnv(rootDir string) error {
	files := []string{
		filepath.Join(rootDir, ".env"),
		filepath.Join(rootDir, ".env.local"),
	}

	for _, file := range files {
		f, err := os.Open(file)
		if err != nil {
			continue
		}
		scanner := bufio.NewScanner(f)
		for scanner.Scan() {
			line := strings.TrimSpace(scanner.Text())
			if line == "" || strings.HasPrefix(line, "#") {
				continue
			}

			parts := strings.SplitN(line, "=", 2)
			if len(parts) == 2 {
				key := strings.TrimSpace(parts[0])
				val := strings.TrimSpace(parts[1])

				val = strings.Trim(val, `"'`)
				val = ExpandEnvVariables(val)

				if os.Getenv(key) == "" {
					os.Setenv(key, val)
				}
			}
		}
		f.Close()
	}
	return nil
}

func ExpandEnvVariables(val string) string {
	re := regexp.MustCompile(`\$\{([A-Za-z0-9_]+)(?::-([^}]*))?\}`)
	return re.ReplaceAllStringFunc(val, func(m string) string {
		sub := re.FindStringSubmatch(m)
		if len(sub) >= 2 {
			varName := sub[1]
			defaultVal := ""
			if len(sub) >= 3 {
				defaultVal = sub[2]
			}
			if envVal := os.Getenv(varName); envVal != "" {
				return envVal
			}
			return defaultVal
		}
		return m
	})
}

func LevenshteinDistance(s1, s2 string) int {
	r1, r2 := []rune(s1), []rune(s2)
	n, m := len(r1), len(r2)
	if n == 0 {
		return m
	}
	if m == 0 {
		return n
	}

	matrix := make([][]int, n+1)
	for i := range matrix {
		matrix[i] = make([]int, m+1)
		matrix[i][0] = i
	}
	for j := 0; j <= m; j++ {
		matrix[0][j] = j
	}

	for i := 1; i <= n; i++ {
		for j := 1; j <= m; j++ {
			cost := 0
			if r1[i-1] != r2[j-1] {
				cost = 1
			}
			matrix[i][j] = min3(
				matrix[i-1][j]+1,
				matrix[i][j-1]+1,
				matrix[i-1][j-1]+cost,
			)
		}
	}
	return matrix[n][m]
}

func min3(a, b, c int) int {
	if a < b && a < c {
		return a
	}
	if b < c {
		return b
	}
	return c
}

func SuggestSimilarTask(target string, validNames []string) []string {
	var matches []string
	target = strings.ToLower(target)

	for _, name := range validNames {
		dist := LevenshteinDistance(target, strings.ToLower(name))
		if dist <= 2 || strings.Contains(strings.ToLower(name), target) {
			matches = append(matches, name)
		}
	}
	return matches
}

func GetAllTaskNames(cfg *Config) []string {
	var names []string
	for k := range cfg.Tasks {
		names = append(names, k)
	}
	sort.Strings(names)
	return names
}

func CleanCache(maxAge time.Duration, maxSize int64) error {
	if _, err := os.Stat(CacheDir); os.IsNotExist(err) {
		fmt.Println("Cache is already empty.")
		return nil
	}

	type fileInfo struct {
		path     string
		size     int64
		lastUsed time.Time
	}

	var files []fileInfo
	var totalSize int64

	_ = filepath.WalkDir(CacheDir, func(path string, d os.DirEntry, err error) error {
		if err != nil || d.IsDir() {
			return nil
		}
		info, err := d.Info()
		if err != nil {
			return nil
		}

		lastUsed := info.ModTime()
		if strings.HasSuffix(path, ".json") {
			if data, err := os.ReadFile(path); err == nil {
				var entry CacheEntry
				if json.Unmarshal(data, &entry) == nil && !entry.LastUsed.IsZero() {
					lastUsed = entry.LastUsed
				}
			}
		}

		files = append(files, fileInfo{
			path:     path,
			size:     info.Size(),
			lastUsed: lastUsed,
		})
		totalSize += info.Size()
		return nil
	})

	now := time.Now()
	purgedCount := 0

	if maxAge > 0 {
		for _, f := range files {
			if now.Sub(f.lastUsed) > maxAge {
				_ = os.Remove(f.path)
				purgedCount++
			}
		}
	}

	if maxSize > 0 && totalSize > maxSize {
		sort.Slice(files, func(i, j int) bool {
			return files[i].lastUsed.Before(files[j].lastUsed)
		})

		for _, f := range files {
			if totalSize <= maxSize {
				break
			}
			if err := os.Remove(f.path); err == nil {
				totalSize -= f.size
				purgedCount++
			}
		}
	}

	if maxAge == 0 && maxSize == 0 {
		_ = os.RemoveAll(CacheDir)
		fmt.Println("Cleaned entire task cache.")
		return nil
	}

	fmt.Printf("Cleaned %d cache entries matching policy.\n", purgedCount)
	return nil
}

func truncateHash(hash string) string {
	if len(hash) > 8 {
		return hash[:8]
	}
	return hash
}

func parseByteSize(s string) (int64, error) {
	s = strings.ToUpper(strings.TrimSpace(s))
	multipliers := map[string]int64{
		"KB": 1024,
		"MB": 1024 * 1024,
		"GB": 1024 * 1024 * 1024,
		"B":  1,
	}

	for suffix, mul := range multipliers {
		if strings.HasSuffix(s, suffix) {
			numStr := strings.TrimSpace(strings.TrimSuffix(s, suffix))
			val, err := strconv.ParseInt(numStr, 10, 64)
			if err != nil {
				return 0, err
			}
			return val * mul, nil
		}
	}

	return strconv.ParseInt(s, 10, 64)
}

func formatByteSize(bytes int64) string {
	const unit = 1024
	if bytes < unit {
		return fmt.Sprintf("%d B", bytes)
	}
	div, exp := int64(unit), 0
	for n := bytes / unit; n >= unit; n /= unit {
		div *= unit
		exp++
	}
	return fmt.Sprintf("%.1f %cB", float64(bytes)/float64(div), "KMGTPE"[exp])
}

func GenerateMermaidGraph(cfg *Config) string {
	var sb strings.Builder
	sb.WriteString("```mermaid\ngraph TD;\n")

	var names []string
	for k := range cfg.Tasks {
		names = append(names, k)
	}
	sort.Strings(names)

	for _, name := range names {
		t := cfg.Tasks[name]
		if len(t.DependsOn) == 0 {
			sb.WriteString(fmt.Sprintf("    %s;\n", name))
		} else {
			for _, dep := range t.DependsOn {
				sb.WriteString(fmt.Sprintf("    %s --> %s;\n", dep, name))
			}
		}
	}

	sb.WriteString("```\n")
	return sb.String()
}

func GenerateASCIIGraph(cfg *Config) string {
	var sb strings.Builder
	sb.WriteString("\nDependency Tree:\n")

	var names []string
	for k := range cfg.Tasks {
		names = append(names, k)
	}
	sort.Strings(names)

	for _, name := range names {
		t := cfg.Tasks[name]
		sb.WriteString(fmt.Sprintf("├── %s%s%s (%s)\n", ColorCyan, name, ColorReset, t.Command))
		for _, dep := range t.DependsOn {
			sb.WriteString(fmt.Sprintf("│   └── depends on: %s%s%s\n", ColorYellow, dep, ColorReset))
		}
	}
	return sb.String()
}

func printUsage() {
	fmt.Printf("%s%s - %s%s\n", ColorCyan, ProjectName, Tagline, ColorReset)
	fmt.Printf("%sCrafted with 100%% Go Standard Library by %s%s\n\n", ColorGray, Author, ColorReset)
	fmt.Println("Usage:")
	fmt.Println("  zephyr [command] [flags...] [targets...] [-- pass-through-args...]")
	fmt.Println("  taskrunner [command] [flags...] [targets...]")
	fmt.Println("\nCommands:")
	fmt.Println("  run [targets...]      Execute pipeline targets (default task if omitted)")
	fmt.Println("  doctor                Deep audit workspace health, DAG validity, and system integrity")
	fmt.Println("  affected              Execute only tasks modified by Git diff")
	fmt.Println("  server                Start built-in Zero-Dependency Remote Cache HTTP Server")
	fmt.Println("  list                  Display configured tasks in formatted table")
	fmt.Println("  graph                 Render dependency graph (ASCII or Mermaid)")
	fmt.Println("  clean                 Purge cache entries by age, size, or all")
	fmt.Println("  version               Display version and platform info")
	fmt.Println("  help                  Display this usage guide")
	fmt.Println("\nRun Flags:")
	fmt.Println("  --config <file>       Path to custom config file (default: tasks.json)")
	fmt.Println("  --parallel <N>        Max worker pool concurrency (default: runtime.NumCPU())")
	fmt.Println("  --why                 Print explicit reason for cache misses")
	fmt.Println("  --watch               Live file watch and auto-rerun on change")
	fmt.Println("  --provenance          Emit SLSA v1.0 / in-toto JSON-LD build provenance")
	fmt.Println("  --secret-key <key>    HMAC-SHA256 cache signing and anti-tamper key")
	fmt.Println("  --dry-run             Preview execution batches without running")
	fmt.Println("  --stream              Stream live stdout/stderr with task prefixes")
	fmt.Println("  --json                Emit machine-readable JSON pipeline summary")
	fmt.Println("  --no-fail-fast        Continue sibling tasks on failure")
	fmt.Println("  --quiet               Suppress startup banner")
}

// ============================================================================
// SECTION 19: CLI DISPATCHER & MAIN ENTRYPOINT
// ============================================================================

func main() {
	InitColors()

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, os.Interrupt, syscall.SIGTERM)
	go func() {
		<-sigChan
		fmt.Printf("\n%s[INTERRUPT]%s Gracefully shutting down pipeline...\n", ColorYellow, ColorReset)
		cancel()
	}()

	rawArgs := os.Args[1:]

	var passThrough []string
	for i, arg := range rawArgs {
		if arg == "--" {
			passThrough = rawArgs[i+1:]
			rawArgs = rawArgs[:i]
			break
		}
	}

	cmd := "run"
	args := rawArgs
	if len(rawArgs) > 0 && !strings.HasPrefix(rawArgs[0], "-") {
		cmd = rawArgs[0]
		args = rawArgs[1:]
	}

	switch cmd {
	case "doctor":
		PrintStartupBanner(false)
		fs := flag.NewFlagSet("doctor", flag.ExitOnError)
		configPath := fs.String("config", "", "Path to config file")
		fs.Parse(args)

		origWd, _ := os.Getwd()
		exitCode := RunDoctorCommand(origWd, *configPath)
		os.Exit(exitCode)

	case "run":
		fs := flag.NewFlagSet("run", flag.ExitOnError)
		configPath := fs.String("config", "", "Path to config file")
		parallel := fs.Int("parallel", runtime.NumCPU(), "Worker pool capacity")
		why := fs.Bool("why", false, "Explain cache miss reasons")
		watch := fs.Bool("watch", false, "Live file watch mode")
		dryRun := fs.Bool("dry-run", false, "Preview execution batches without running")
		stream := fs.Bool("stream", false, "Stream task outputs with task prefixes")
		jsonOut := fs.Bool("json", false, "Emit machine-readable JSON summary")
		noFailFast := fs.Bool("no-fail-fast", false, "Continue sibling tasks on error")
		secretKey := fs.String("secret-key", "", "HMAC-SHA256 signing secret key")
		provenance := fs.Bool("provenance", false, "Emit SLSA v1.0 build provenance metadata")
		quiet := fs.Bool("quiet", false, "Suppress startup banner")
		fs.Parse(args)

		if !*jsonOut {
			PrintStartupBanner(*quiet)
		}

		targetTasks := fs.Args()

		origWd, _ := os.Getwd()
		rootDir, resolvedConfig, err := FindConfigRoot(origWd, *configPath)
		if err != nil {
			fmt.Fprintf(os.Stderr, "%sError:%s %v\n", ColorRed, ColorReset, err)
			os.Exit(1)
		}
		_ = os.Chdir(rootDir)

		_ = LoadDotEnv(rootDir)

		cfg, err := LoadConfig(resolvedConfig)
		if err != nil {
			fmt.Fprintf(os.Stderr, "%sError:%s %v\n", ColorRed, ColorReset, err)
			os.Exit(1)
		}

		if len(targetTasks) == 0 && cfg.DefaultTask != "" {
			targetTasks = []string{cfg.DefaultTask}
		}

		if *secretKey != "" {
			for name, t := range cfg.Tasks {
				t.SecretKey = *secretKey
				cfg.Tasks[name] = t
			}
		}

		failFast := !*noFailFast

		if *watch {
			fmt.Printf("%s[WATCH]%s Watching workspace for changes (Press Ctrl+C to stop)...\n\n", ColorCyan, ColorReset)
			runPipelineFunc := func() {
				_, _ = RunPipeline(ctx, cfg, targetTasks, *parallel, *why, false, *stream, *jsonOut, failFast, passThrough)
			}
			runPipelineFunc()

			lastMod := make(map[string]time.Time)
			updateModTimes := func() {
				_ = filepath.WalkDir(".", func(path string, d os.DirEntry, err error) error {
					if err == nil && !d.IsDir() {
						if info, err := d.Info(); err == nil {
							lastMod[path] = info.ModTime()
						}
					}
					return nil
				})
			}
			updateModTimes()

			ticker := time.NewTicker(500 * time.Millisecond)
			defer ticker.Stop()

			for {
				select {
				case <-ctx.Done():
					return
				case <-ticker.C:
					changed := false
					_ = filepath.WalkDir(".", func(path string, d os.DirEntry, err error) error {
						if err != nil || d.IsDir() {
							if d != nil && d.IsDir() && ignoredDirs[d.Name()] {
								return filepath.SkipDir
							}
							return nil
						}
						info, err := d.Info()
						if err == nil {
							if oldTime, exists := lastMod[path]; !exists || info.ModTime().After(oldTime) {
								changed = true
								lastMod[path] = info.ModTime()
							}
						}
						return nil
					})

					if changed {
						fmt.Printf("\n%s[WATCH]%s File modification detected. Re-running pipeline...\n\n", ColorYellow, ColorReset)
						runPipelineFunc()
						updateModTimes()
					}
				}
			}
		}

		summary, err := RunPipeline(ctx, cfg, targetTasks, *parallel, *why, *dryRun, *stream, *jsonOut, failFast, passThrough)
		if *jsonOut && summary != nil {
			jsonData, _ := json.MarshalIndent(summary, "", "  ")
			fmt.Println(string(jsonData))
		}

		if *provenance && summary != nil {
			fmt.Println("\n--- SLSA v1.0 Provenance Attestations ---")
			for _, r := range summary.Results {
				if r.ProvenanceJSON != "" {
					fmt.Printf("[%s Provenance]:\n%s\n", r.TaskName, r.ProvenanceJSON)
				}
			}
		}

		if err != nil {
			if summary == nil {
				fmt.Fprintf(os.Stderr, "%sError:%s %v\n", ColorRed, ColorReset, err)
			}
			os.Exit(1)
		}

	case "affected":
		fs := flag.NewFlagSet("affected", flag.ExitOnError)
		configPath := fs.String("config", "", "Path to config file")
		baseRef := fs.String("base", "main", "Git base reference to compare against")
		parallel := fs.Int("parallel", runtime.NumCPU(), "Worker pool capacity")
		why := fs.Bool("why", false, "Explain cache miss reasons")
		stream := fs.Bool("stream", false, "Stream task outputs with task prefixes")
		fs.Parse(args)

		origWd, _ := os.Getwd()
		rootDir, resolvedConfig, err := FindConfigRoot(origWd, *configPath)
		if err != nil {
			fmt.Fprintf(os.Stderr, "%sError:%s %v\n", ColorRed, ColorReset, err)
			os.Exit(1)
		}
		_ = os.Chdir(rootDir)

		cfg, err := LoadConfig(resolvedConfig)
		if err != nil {
			fmt.Fprintf(os.Stderr, "%sError:%s %v\n", ColorRed, ColorReset, err)
			os.Exit(1)
		}

		changedFiles, err := GetGitChangedFiles(*baseRef)
		if err != nil {
			fmt.Fprintf(os.Stderr, "%sError detecting git changes:%s %v\n", ColorRed, ColorReset, err)
			os.Exit(1)
		}

		tasksInputs := make(map[string][]string)
		dependentsMap := make(map[string][]string)
		for name, t := range cfg.Tasks {
			tasksInputs[name] = t.Inputs
			for _, dep := range t.DependsOn {
				dependentsMap[dep] = append(dependentsMap[dep], name)
			}
		}

		affected := ComputeAffectedTasks(tasksInputs, dependentsMap, changedFiles, matchGlob)
		if len(affected) == 0 {
			fmt.Printf("%s[AFFECTED]%s No tasks affected by changes against '%s'.\n", ColorGreen, ColorReset, *baseRef)
			return
		}

		fmt.Printf("%s[AFFECTED]%s Executing %d affected tasks: %s\n", ColorCyan, ColorReset, len(affected), strings.Join(affected, ", "))
		_, err = RunPipeline(ctx, cfg, affected, *parallel, *why, false, *stream, false, true, passThrough)
		if err != nil {
			os.Exit(1)
		}

	case "server":
		fs := flag.NewFlagSet("server", flag.ExitOnError)
		port := fs.Int("port", 8080, "Port to listen on")
		storageDir := fs.String("dir", ".cache-server", "Directory to store cached blobs")
		token := fs.String("token", os.Getenv("ZEPHYR_SERVER_TOKEN"), "Bearer token for auth")
		fs.Parse(args)

		fmt.Printf("%s[SERVER]%s Starting Zero-Dependency Remote Cache Server on :%d...\n", ColorGreen, ColorReset, *port)
		srv := NewRemoteCacheServer(*port, *storageDir, *token)
		if err := srv.Start(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			fmt.Fprintf(os.Stderr, "%sServer error:%s %v\n", ColorRed, ColorReset, err)
			os.Exit(1)
		}

	case "list":
		fs := flag.NewFlagSet("list", flag.ExitOnError)
		configPath := fs.String("config", "", "Path to config file")
		fs.Parse(args)

		origWd, _ := os.Getwd()
		rootDir, resolvedConfig, err := FindConfigRoot(origWd, *configPath)
		if err != nil {
			fmt.Fprintf(os.Stderr, "%sError:%s %v\n", ColorRed, ColorReset, err)
			os.Exit(1)
		}
		_ = os.Chdir(rootDir)

		cfg, err := LoadConfig(resolvedConfig)
		if err != nil {
			fmt.Fprintf(os.Stderr, "%sError:%s %v\n", ColorRed, ColorReset, err)
			os.Exit(1)
		}

		fmt.Println("\nConfigured Tasks:")
		w := tabwriter.NewWriter(os.Stdout, 0, 8, 2, ' ', 0)
		fmt.Fprintln(w, "Task Name\tCommand\tCWD\tTimeout\tRetries\tWeight\tShell\tDepends On")
		fmt.Fprintln(w, "---------\t-------\t---\t-------\t-------\t------\t-----\t----------")
		for name, t := range cfg.Tasks {
			cwd := t.Cwd
			if cwd == "" {
				cwd = "."
			}
			timeout := t.Timeout
			if timeout == "" {
				timeout = "-"
			}
			shell := t.Shell
			if shell == "" {
				shell = "default"
			}
			retries := fmt.Sprintf("%d", t.Retries)
			weight := fmt.Sprintf("%d", t.Weight)
			deps := strings.Join(t.DependsOn, ", ")
			if deps == "" {
				deps = "-"
			}
			fmt.Fprintf(w, "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n", name, t.Command, cwd, timeout, retries, weight, shell, deps)
		}
		w.Flush()
		fmt.Println()

	case "graph":
		fs := flag.NewFlagSet("graph", flag.ExitOnError)
		configPath := fs.String("config", "", "Path to config file")
		format := fs.String("format", "ascii", "Graph format: ascii or mermaid")
		fs.Parse(args)

		origWd, _ := os.Getwd()
		rootDir, resolvedConfig, err := FindConfigRoot(origWd, *configPath)
		if err != nil {
			fmt.Fprintf(os.Stderr, "%sError:%s %v\n", ColorRed, ColorReset, err)
			os.Exit(1)
		}
		_ = os.Chdir(rootDir)

		cfg, err := LoadConfig(resolvedConfig)
		if err != nil {
			fmt.Fprintf(os.Stderr, "%sError:%s %v\n", ColorRed, ColorReset, err)
			os.Exit(1)
		}

		if *format == "mermaid" {
			fmt.Println(GenerateMermaidGraph(cfg))
		} else {
			fmt.Println(GenerateASCIIGraph(cfg))
		}

	case "clean":
		fs := flag.NewFlagSet("clean", flag.ExitOnError)
		maxAgeStr := fs.String("max-age", "", "Purge entries older than duration (e.g. 72h, 7d)")
		maxSizeStr := fs.String("max-size", "", "LRU purge entries exceeding size budget (e.g. 2GB, 500MB)")
		fs.Parse(args)

		var maxAge time.Duration
		if *maxAgeStr != "" {
			var err error
			if strings.HasSuffix(*maxAgeStr, "d") {
				days, parseErr := strconv.Atoi(strings.TrimSuffix(*maxAgeStr, "d"))
				if parseErr != nil {
					fmt.Fprintf(os.Stderr, "Invalid duration format: %s\n", *maxAgeStr)
					os.Exit(1)
				}
				maxAge = time.Duration(days) * 24 * time.Hour
			} else {
				maxAge, err = time.ParseDuration(*maxAgeStr)
				if err != nil {
					fmt.Fprintf(os.Stderr, "Invalid duration format: %s\n", *maxAgeStr)
					os.Exit(1)
				}
			}
		}

		var maxSizeBytes int64
		if *maxSizeStr != "" {
			sz, err := parseByteSize(*maxSizeStr)
			if err != nil {
				fmt.Fprintf(os.Stderr, "Invalid size format: %s\n", *maxSizeStr)
				os.Exit(1)
			}
			maxSizeBytes = sz
		}

		if err := CleanCache(maxAge, maxSizeBytes); err != nil {
			fmt.Fprintf(os.Stderr, "%sError:%s %v\n", ColorRed, ColorReset, err)
			os.Exit(1)
		}

	case "version", "--version", "-v":
		fmt.Printf("%s (%s/%s, 100%% Go stdlib by %s)\n", ProjectName, runtime.GOOS, runtime.GOARCH, Author)

	case "help", "--help", "-h":
		printUsage()

	default:
		suggestions := SuggestSimilarTask(cmd, []string{"run", "doctor", "affected", "server", "list", "graph", "clean", "version", "help"})
		fmt.Fprintf(os.Stderr, "%sUnknown command '%s'.%s", ColorRed, cmd, ColorReset)
		if len(suggestions) > 0 {
			fmt.Fprintf(os.Stderr, " Did you mean: '%s'?", strings.Join(suggestions, "', '"))
		}
		fmt.Fprintln(os.Stderr, "\nRun 'zephyr help' for usage.")
		os.Exit(1)
	}
}
