# Proofline v8.0 -- The Zero-Dependency Verification Engine

**AI made code generation cheap. Verification did not keep up.**

> Zero third-party dependencies. Python stdlib only. No pip install required.

---

## The Story

It started with a simple realization: AI coding agents are incredibly fast. They can churn out hundreds of lines of code in seconds. But there is a dark side. AI hallucinates. It quietly swallows errors by writing broad `except Exception:` blocks. It alters critical security functions and forgets to update the tests.

The human reviewer is left holding the bag, drowning in PRs they do not fully understand.

We needed a strict gatekeeper. A bouncer for our `main` branch. But there was a catch: we were entering the **Zero Dependency Hackathon**. We could not rely on `pip install`. We could not use heavy AST parsing libraries. We could not use templating engines. We had to build a weapon using only what Python gave us out of the box.

### The Engine

Using nothing but the naked Python standard library (`ast`, `importlib`, `subprocess`), we built **Proofline**. It mathematically traces the blast radius of every AI-generated change.

We taught it to understand the difference between a direct call (PROVEN) and a dynamically dispatched method (UNKNOWN). We taught it to detect when an AI breaks a public signature but leaves the test suite untouched.

### The Bouncer at the Door

But developers forget to run tools. So we built `proofline install-hook`, a pure Python feature that generates a Git pre-commit hook natively. Now, the moment an AI tries to commit a hallucinated exception handler, Proofline steps in. **Commit Blocked.**

### Closing the Loop

When Proofline catches an unverified AI change, it does not just yell at you. We built `scaffold-tests` -- a feature that reads the Evidence Graph and automatically writes the `unittest` boilerplate for you, closing the gap as fast as the AI opened it.

### The Package Killers

To secure the ultimate hackathon score, we relentlessly hunted down the most commonly installed packages and replaced them with standard library code:

| Package Killed | Stdlib Replacement |
|---|---|
| `python-dotenv` | Native `.env` parser using `str.split()` |
| `strip-ansi` | Regex-based ANSI stripper (`ansi_stripper.py`) |
| `jinja2` | HTML generation via Python `string.Template` |
| `watchdog` | File watcher using `hashlib` + `os.stat` polling |
| `fastapi` / `flask` / web servers | `http.server.BaseHTTPRequestHandler` |
| `networkx` | Caller graph as a plain `dict[str, set[str]]` |
| `gitpython` | Git operations via `subprocess` + `git` CLI |

We even built a self-enforcing gatekeeper (`deps_enforcer.py`) that scans `requirements.txt` on boot and terminates the program if it finds any third-party package!

---

## Features (v8.0)

- **11 Verification Rules (R1-R11)** -- signature breaks, silent exception swallows, missing tests, orphan code, complexity spikes, and more
- **Blast Radius Heatmap** -- visual caller graph showing exactly which functions are affected by a change
- **Cyclomatic Complexity Analysis** -- flags functions with complexity > 10 that have no test coverage
- **Route Detection** -- identifies public HTTP routes (Flask, FastAPI, Django) affected by the change
- **Git-Native Scanning** -- analyze directly from git refs (`HEAD~5`, commit hashes, branch names)
- **HTML Visual Dashboard** -- interactive report with heatmap, evidence graph, and verification checklist
- **Zero-Dependency REST API** -- built-in API server via `http.server` for CI/CD integration
- **GitHub PR Bot** -- posts Proofline findings as PR comments via the GitHub API
- **Test Scaffolding** -- auto-generates `unittest` boilerplate for unverified changed symbols
- **Git Pre-Commit Hook** -- blocks unsafe commits at the developer level
- **GitHub Actions Generator** -- one command generates a complete CI workflow
- **AST Caching Engine** -- `hashlib`-based cache in `.proofline/cache/` for fast repeat scans
- **Parallel AST Processing** -- `concurrent.futures.ProcessPoolExecutor` for large repos
- **Audit Packager** -- native `zipfile` compression for compliance artifact sharing
- **Interactive Setup Wizard** -- `proofline init` bootstraps config with pure `input()`
- **Single-File Bundle** -- `proofline_single.py` packages the entire engine into one file

---

## Usage

### Quick Start (any Python repo)

```bash
# From the project root (parent of the proofline/ module)
python -m proofline scan --base HEAD~1
```

```powershell
# Windows PowerShell -- always set PYTHONUTF8 for full Unicode output
$env:PYTHONUTF8 = "1"
python -m proofline scan --base HEAD~5 --html report.html --serve
```

### 1. Setup Wizard

```bash
python -m proofline init
```

### 2. Install the Bouncer (Git Hook)

```bash
python -m proofline install-hook --fail-on HIGH
```

### 3. Scan a Git Repository

```bash
# Scan last 5 commits
python -m proofline scan --base HEAD~5

# Scan against a specific commit hash
python -m proofline scan --base abc1234

# Scan against origin/main (for PR review)
python -m proofline scan --base origin/main --html report.html
```

### 4. Analyze Directory Snapshots

```bash
python -m proofline analyze --before ./baseline --after ./patch
```

### 5. Visual Dashboard

```bash
python -m proofline scan --base HEAD~5 --html report.html --serve
```

### 6. GitHub Actions CI

```bash
python -m proofline install-gha
# Writes: .github/workflows/proofline.yml
```

### 7. Scaffold Missing Tests

```bash
python -m proofline scaffold-tests --before ./baseline --after ./patch
```

### 8. REST API + Dashboard Server

```bash
python -m proofline serve --port 8080
```

Endpoints:
- `GET /` -- Dashboard HTML
- `POST /api/analyze` -- JSON analysis
- `GET /api/health` -- Server health check

### 9. Compliance Archive

```bash
python -m proofline archive --before ./baseline --after ./patch
# Writes: proofline_audit_YYYYMMDD_HHMMSS.zip
```

---

## Verification Rules

| Rule | ID | Severity | Description |
|------|----|----------|-------------|
| Signature Break | R1 | HIGH | Public function signature changed; callers not updated |
| Silent Exception | R2 | HIGH | Broad `except Exception:` added in security boundary |
| Test Not Updated | R3 | MEDIUM | Implementation changed but tests were not touched |
| Dep Introduced | R4 | MEDIUM | New third-party package added to requirements |
| Unauthed Route | R5 | HIGH | HTTP route exposed without authentication guard |
| No Test Candidate | R6 | MEDIUM | Changed function has zero associated test files |
| Docstring Removed | R7 | LOW | Public API docstring deleted |
| Return Type Changed | R8 | MEDIUM | Return type inferred to have changed by AST |
| Complexity Spike | R9 | MEDIUM | Recursive complexity increased without test cover |
| High Complexity | R10 | HIGH | Cyclomatic complexity > 10 with no tests |
| Orphan Code | R11 | MEDIUM | New function with zero callers in the codebase |

---

## Testing

Run the full test suite:

```bash
python run_tests.py
```

Run Proofline against itself (dog-fooding):

```bash
$env:PYTHONUTF8 = "1"
python -m proofline scan --base HEAD~3 --html self_report.html
```

---

## Project Structure

```
proofline/
  __main__.py           # python -m proofline entry point
  cli.py                # Argument parsing and command orchestration
  core.py               # Core analysis pipeline
  diff_engine.py        # Git diff parsing + AST symbol extraction
  caller_graph.py       # Cross-repo call graph (pure dict/set)
  rules_engine.py       # 11 verification rules (R1-R11)
  risk_model.py         # Severity + confidence scoring
  evidence_graph.py     # Evidence aggregator and report model
  report.py             # HTML / JSON / CLI renderers
  test_associator.py    # Test file discovery and symbol association
  route_detector.py     # HTTP route detection (Flask/FastAPI/Django)
  symbol_map.py         # Full-repo AST symbol index with caching
  server.py             # Zero-dep REST API + dashboard HTTP server
  github_integration.py # GitHub PR comment formatter and poster
  git_utils.py          # Subprocess-based git operations
  watcher.py            # File watcher for --watch mode
  scaffolder.py         # unittest boilerplate generator
  packer.py             # Single-file bundle generator
  ansi_stripper.py      # ANSI escape code stripper (no colorama)
  env_parser.py         # .env file parser (no python-dotenv)
  deps_enforcer.py      # Zero-dep constraint enforcer
  history.py            # Scan history tracker
  ignore_parser.py      # .prooflineignore parser
  sarif_formatter.py    # SARIF output formatter for IDE integration
  wizard.py             # Interactive setup wizard
  tui.py                # Terminal UI helpers
  demo_repo/            # Baseline + patch demo for quick testing
  tests/                # Test suite
```

---

## Known Issues & Fixes

| Issue | Fix |
|-------|-----|
| `UnicodeEncodeError` on Windows terminal | Run with `$env:PYTHONUTF8="1"` in PowerShell |
| `No module named proofline` | Run from the parent directory (not inside `proofline/`) |
| `No Python file changes detected` | All Python files were added in one commit -- scan with a larger `--base` range |
| Exit code 1 on HIGH findings | This is intentional -- Proofline exits 1 when HIGH severity issues are found (for CI/CD) |

---

**Built with love for the Zero Dependency Hackathon 2026.**
**Zero dependencies. Total verification.**
