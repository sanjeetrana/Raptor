# Project Spec: Incremental Task Runner
### Zero Dependency | 72-Hour Hackathon (Hackathon Raptors) — Track A: Developer Tools & CLI

Final build reference. Hand this to your AI coding assistant at kickoff.

---

## 1. Hackathon Facts (do not violate these)

**Event:** Zero Dependency | 72-Hour Hackathon, organized by Hackathon Raptors, listed on Unstop.

**Dates (IST):**
- Registration deadline: Aug 28, 2026, 11:00 PM
- **Kickoff (code may start): Aug 28, 2026, 11:30 PM**
- **Submission closes: Aug 31, 2026, 11:30 PM**
- Write-up submission closes: Sep 8, 2026, 11:30 PM
- Winners announced: Sep 11, 2026 (Discord)

**Team size:** 1–4 (solo allowed; 2–3 recommended by organizers)

**Track:** A — Developer Tools & CLI

**Core constraint:** Zero third-party runtime dependencies. Go stdlib only. `go.mod` must have an **empty `require` block**.

**Hard rules:**
- All project code must be written *during* the 72-hour window (Aug 28 11:30 PM → Aug 31 11:30 PM IST).
- Planning, research, and AI prompt prep are allowed before kickoff — no code before kickoff.
- No copying third-party source into the repo to fake a clean manifest.
- Repo must be public on GitHub at submission time.
- Must build with a single documented command.
- AI coding assistants are explicitly allowed and expected — be ready to explain and defend the code.

**Required submission artifacts:** public GitHub repo, working implementation, one-command build instructions, empty dependency manifest, dependency proof, `README.md`, `STDLIB.md`, tests, 5-minute demo video.

**Judging weights:**
| Criterion | Weight |
|---|---|
| Functionality & Usefulness | 35% |
| Zero-Dependency Craft | 30% |
| Code Quality & Idiom | 25% |
| Innovation | 10% |

**Bonus challenges:**
| Bonus | Points |
|---|---|
| Single File | +5 |
| Reproducible Build (byte-identical, hashes published) | +5 |
| Package Killer | +3 |
| STDLIB Log (10+ substitutions) | +3 |

**Priority reminder:** 65% of the score is Functionality + Zero-Dep Craft. Get the core working and well-tested before chasing bonus points.

---

## 2. The Idea

A dependency-aware, incremental task runner: tasks are declared in a config file with command, inputs, outputs, and dependencies. The tool builds a DAG, executes tasks in order, hashes each task's inputs, and **skips/replays cached output when nothing relevant has changed** — the same core mechanic as Turborepo or Nx.

**Package Killer target:** Turborepo / Nx (primary), `make` (secondary reference).

**Real problems this solves** (useful framing for your README and demo narration):

| Problem | How the spec addresses it |
|---|---|
| Slow CI/CD pipelines re-running unchanged work | Input-hash caching in `.taskcache/` |
| Monorepo scalability — running everything when only one part changed | `depends_on` DAG runs only necessary targets |
| "Cache blindness" — not knowing why something did/didn't rerun | `[CACHED]` tags + `--why` flag |
| Race conditions from naive parallel execution | Goroutine worker pool respecting DAG order |
| Circular dependency deadlocks | DFS-based cycle detection at startup |
| Tooling bloat (huge `node_modules` for a task runner) | Go stdlib only, single-file build |
| "Works on my machine" env drift | Env vars folded into the cache hash |
| Cross-platform shell execution bugs | OS-aware shell dispatch via `runtime.GOOS` |

---

## 3. Feature List (tiered by priority)

### Tier 1 — Must-have core (protects the 35% + 30%; build this first, no matter what)
- Config file (`tasks.json`): `name`, `command`, `inputs`, `outputs`, `depends_on`, optional `env_vars`
- DAG construction + DFS-based cycle detection
- Content hashing (sha256) of input files **and** any declared `env_vars` values
- OS-aware command execution: dispatch via `sh -c` on Unix/macOS, `cmd.exe /C` on Windows (`runtime.GOOS`)
- Sequential execution respecting dependency order
- Local cache (`.taskcache/`) keyed by hash: stdout, stderr, exit code, output file hashes
- Cache hit → instant replay with a visible `[CACHED]` tag
- CLI: `run [target]`, `list`, `clean`; correct exit codes; `--help`
- Tests: hashing (incl. env var changes), DAG/cycle detection, cache hit/miss, one end-to-end integration test

### Tier 2 — High-value differentiators (build after Tier 1 is solid)
1. **Parallel DAG execution** — goroutine worker pool, independent tasks run concurrently, respecting dependency order
2. **`--why` flag** — prints exactly which input file (or env var) changed to trigger a rerun
3. **`graph` command** — outputs an ASCII tree or Mermaid.js graph string of the task DAG; reuses existing graph structure, strong visual for the demo video
4. **Live colored terminal status** — pending/running/cached/failed via ANSI escape codes

### Tier 3 — Stretch, only if time remains
- `clean --max-age 7d` — purge cache entries older than N days

---

## 4. Architecture

**Language:** Go, one well-organized file (`main.go`) with clear section comments — aim for the Single File bonus, but drop it in favor of clean multi-file structure if it starts hurting readability (Code Quality is worth 25% vs. the bonus's 5).

**Core types:**
```go
type Task struct {
    Name      string
    Command   string
    Inputs    []string
    Outputs   []string
    DependsOn []string
    EnvVars   []string // names of env vars to include in the hash
}

type Config struct {
    Tasks map[string]Task
}

type CacheEntry struct {
    Stdout       string
    Stderr       string
    ExitCode     int
    OutputHashes map[string]string
    Timestamp    time.Time
}
```

**Core functions:**
- `loadConfig(path string) (*Config, error)` — `encoding/json`
- `buildDAG(cfg *Config) (*Graph, error)` — DFS cycle detection
- `topoOrder` / level grouping for parallel scheduling
- `hashInputs(task Task) (string, error)` — sha256 over sorted `(path, content)` pairs **plus** sorted `(envVarName, value)` pairs for any declared `EnvVars`
- `cacheLookup(hash string) (*CacheEntry, bool)` / `cacheStore(hash string, entry CacheEntry)`
- `shellCommand(cmd string) *exec.Cmd` — branches on `runtime.GOOS`: `sh -c <cmd>` on Unix/macOS/Linux, `cmd.exe /C <cmd>` on Windows
- `executeTask(task Task) (stdout, stderr string, exitCode int, err error)` — via `os/exec`, using `shellCommand`
- `runPipeline(cfg *Config, targets []string, parallel int)` — orchestrates execution, worker pool for independent tasks
- `printGraph(g *Graph, format string)` — ASCII tree or Mermaid (`graph TD; a-->b;` style string)
- `printStatus(...)` — colored terminal output
- `flag`-based CLI: `run`, `list`, `clean [--max-age Nd]`, `graph [--format mermaid|ascii]`, `--why`, `--parallel N`

**Cache directory layout:**
```
.taskcache/<hash>/stdout.txt
.taskcache/<hash>/stderr.txt
.taskcache/<hash>/exitcode
.taskcache/<hash>/output-hashes.json
```

**Sample `tasks.json`:**
```json
{
  "tasks": {
    "build": {
      "command": "go build -o bin/app ./cmd/app",
      "inputs": ["cmd/app/**/*.go"],
      "outputs": ["bin/app"],
      "depends_on": ["lint"],
      "env_vars": ["GOOS", "GOARCH"]
    },
    "lint": {
      "command": "go vet ./...",
      "inputs": ["**/*.go"],
      "outputs": []
    },
    "test": {
      "command": "go test ./...",
      "inputs": ["**/*.go"],
      "outputs": [],
      "depends_on": ["build"]
    }
  }
}
```

---

## 5. STDLIB.md — substitutions to document (target 12+)

| Normally you'd use | Instead, stdlib gives you |
|---|---|
| `commander` / `yargs` / `cobra` | `flag` package |
| a JSON parsing library | `encoding/json` |
| a hashing/checksum library | `crypto/sha256` |
| `execa` | `os/exec` |
| a glob library (`minimatch`, `globby`) | `path/filepath.Glob` / `WalkDir` |
| `p-queue` / a task scheduler lib | goroutines + channels + `sync` |
| `chalk` (terminal color) | raw ANSI escape sequences |
| `jest` / `mocha` | built-in `testing` package |
| a serialization library | `encoding/json` / `encoding/gob` |
| `cross-spawn` (cross-platform shell) | `runtime.GOOS` + `os/exec` branch |
| a cron/scheduling lib (for cache age) | `time` package (`time.Since`) |
| a graph/visualization library | plain string building for ASCII/Mermaid output |

---

## 6. Reproducible Build Plan

```bash
go build -trimpath -ldflags="-s -w -buildid=" -o taskrunner main.go
```
- Fix `GOOS`/`GOARCH` explicitly, avoid embedding timestamps
- Build twice into separate output names, `sha256sum` both, confirm they match
- Publish both hashes and the exact build command in `README.md`

---

## 7. Testing Plan

- **Unit tests:** hash determinism (incl. env var changes altering the hash), DAG cycle detection, cache hit/miss, `shellCommand` produces the right dispatch per `runtime.GOOS` branch, `graph` output is well-formed
- **Integration test:** sample `tasks.json` with 3–4 tasks; run once (all execute) → run again (all cached) → edit one input (only downstream tasks rerun) → change a declared env var (dependent task reruns even with unchanged files)

---

## 8. Demo Video Outline (5 min)

- **0:00–0:25** — Problem statement (Turborepo/Nx-style caching, why it matters)
- **0:25–1:15** — Architecture: DAG, hashing (incl. env vars), cache
- **1:15–2:45** — Live demo: first run → cached second run → edit a file → `--why` explains the rerun
- **2:45–3:30** — Parallel execution + colored live status
- **3:30–4:00** — `graph` command output (ASCII/Mermaid)
- **4:00–4:30** — `STDLIB.md` walkthrough
- **4:30–5:00** — Reproducible build: build twice, matching hashes

---

## 9. 72-Hour Build Timeline

| Hours | Focus |
|---|---|
| 0–4 | Skeleton, `Task`/`Config` structs, config parsing, CLI skeleton |
| 4–10 | DAG builder, cycle detection, topo sort, sequential executor, OS-aware `shellCommand` |
| 10–17 | Input + env-var hashing, cache read/write, `[CACHED]` replay |
| 17–23 | Unit tests: hashing, DAG, cache, shell dispatch |
| 23–31 | Parallel executor (goroutine worker pool) |
| 31–36 | `--why` flag, colored terminal status |
| 36–40 | `graph` command (ASCII/Mermaid) |
| 40–46 | CLI polish: `list`/`clean`, `--help`, exit codes |
| 46–54 | Reproducible build setup + verification |
| 54–62 | `README.md` + `STDLIB.md` |
| 62–67 | Record demo video |
| 67–71 | Buffer: bug fixes, final checks |
| 71–72 | Stretch only: `clean --max-age` if time remains |

---

## 10. Pre-Submission Checklist

- [ ] `go.mod` has an empty `require` block
- [ ] All code written within the Aug 28 11:30 PM → Aug 31 11:30 PM IST window
- [ ] GitHub repo is public
- [ ] One-command build works from a clean clone
- [ ] `README.md` complete (incl. reproducible-build hashes if attempted)
- [ ] `STDLIB.md` with 12+ substitutions
- [ ] Tests present and passing, including env-var hash and cross-platform shell dispatch tests
- [ ] 5-minute demo video recorded and linked
- [ ] `graph` command working and shown in the video
- [ ] Dependency proof included
