<div align="center">
  <h1>Proofline</h1>
  <p><b>AI made code generation cheap. Verification did not keep up. We fixed it.</b></p>
  <p><i>A Zero-Dependency Static Analysis Guardian -- Python stdlib only, no pip install needed.</i></p>
  <p>
    <img src="https://img.shields.io/badge/Python-3.9%2B-blue?style=flat-square&logo=python" alt="Python 3.9+" />
    <img src="https://img.shields.io/badge/Dependencies-Zero-brightgreen?style=flat-square" alt="Zero Dependencies" />
    <img src="https://img.shields.io/badge/License-MIT-yellow?style=flat-square" alt="MIT License" />
    <img src="https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey?style=flat-square" alt="Cross Platform" />
  </p>
</div>

---

## The Problem

We are living in a new era of software engineering. Today, half of your codebase is written by AI. And while AI is incredibly fast, it has a fatal flaw: **it hallucinates.**

It makes up standard library functions that do not exist. It silently swallows exceptions in critical authentication boundaries. It introduces untested routes. And because human reviewers suffer from fatigue when reading massive AI-generated Pull Requests, these silent, highly-destructive bugs slip right into `main`.

Worse yet, the tools we typically use to catch these bugs rely on massive dependency trees. Every install is a trust decision delegated to a stranger, exposing you to supply chain attacks.

We built **Proofline** as the counter-move.

---

## What Proofline Does

Proofline is a change-centered static analysis engine built from **100% Python standard library**. Zero third-party packages. No supply chain risk. No `pip install`. Just pure vanilla Python.

It acts as a ruthless verification gate in your CI/CD pipeline. Instead of just regex-matching your code, Proofline actually understands it. It parses your Python AST to build a **Caller Graph** and **Evidence Graph** to understand the true *blast radius* of every AI-generated change.

### How It Catches Hallucinations

| Rule | What It Catches |
|------|-----------------|
| **R1** | Public API signature changed but callers not updated |
| **R2** | Broad `except Exception:` added inside security-critical functions |
| **R3** | Tests exist but were not updated alongside logic changes |
| **R4** | New `requirements.txt` entries introducing unknown packages |
| **R5** | Routes exposed without authentication checks |
| **R6** | Changed functions with zero associated test candidates |
| **R7** | Docstrings removed or stripped from public APIs |
| **R8** | Return type changed silently (inferred via AST) |
| **R9** | Recursive complexity increase without test coverage |
| **R10** | Cyclomatic complexity > 10 with no tests |
| **R11** | New code with zero callers in the entire codebase (orphan/dead code) |

If the calculated risk crosses the defined threshold (e.g. `HIGH`), Proofline exits non-zero -- slamming the door on the Pull Request.

---

## Quick Start

No virtual environment needed. No pip. Just Python 3.9+.

```bash
git clone https://github.com/ShreyaKaushikdev/zerodep-analyzer.git
cd zerodep-analyzer
```

**Scan your last commit:**
```bash
python -m proofline scan --base HEAD~1
```

**Analyze two directory snapshots:**
```bash
python -m proofline analyze --before ./baseline --after ./patch
```

**Generate an HTML visual dashboard:**
```bash
python -m proofline scan --base HEAD~5 --html report.html --serve
```

**Install as a Git pre-commit hook (blocks bad commits locally):**
```bash
python -m proofline install-hook --fail-on HIGH
```

> **Windows (PowerShell):** Prefix commands with `$env:PYTHONUTF8="1"` to enable full Unicode output.

---

## All Commands

```
python -m proofline COMMAND [options]
```

| Command | Description |
|---------|-------------|
| `analyze` | Analyze a before/after directory pair |
| `scan` | Analyze changes in a git repository against a base ref |
| `install-hook` | Install a Git pre-commit hook to block unsafe commits |
| `scaffold-tests` | Generate unittest boilerplate for changed functions |
| `install-gha` | Generate a GitHub Actions CI workflow for Proofline |
| `serve` | Start the zero-dependency REST API and dashboard server |
| `archive` | Generate reports and zip them for compliance audit |
| `init` | Run the interactive setup wizard |
| `stdlib-notes` | Print stdlib substitutions used instead of packages |

### Common Flags

| Flag | Description |
|------|-------------|
| `--base HEAD~N` | Compare current HEAD against N commits ago |
| `--html report.html` | Write a rich HTML visual dashboard |
| `--serve` | Open the dashboard in your browser after analysis |
| `--output report.json` | Write machine-readable JSON output |
| `--log-file proof.log` | Write a clean (ANSI-stripped) plain text log |
| `--fail-on HIGH` | Exit non-zero only on HIGH severity findings |
| `--no-color` | Disable colored terminal output |
| `--verbose` | Show extended evidence details per symbol |

---

## Testing on Real Projects

Proofline works on any Python git repository.

### Your own repo (Windows PowerShell)

```powershell
$env:PYTHONUTF8 = "1"
$env:PYTHONPATH = "C:\path\to\zerodep-analyzer"
cd your-python-project
python -m proofline scan --base HEAD~5 --html report.html --serve
```

### Any open source project (Mac/Linux)

```bash
git clone https://github.com/pallets/flask.git
cd flask
PYTHONPATH=/path/to/zerodep-analyzer python -m proofline scan --base HEAD~10 --html report.html --serve
```

### CI/CD (GitHub Actions)

```bash
python -m proofline install-gha
```

This writes `.github/workflows/proofline.yml` that runs on every PR. No secrets, no tokens, no pip installs.

---

## Architecture: The Package Killers

Every common Python package that Proofline replaced with standard library code:

| Package Killed | What We Built Instead |
|---|---|
| `python-dotenv` | Native `.env` parser using `str.split()` |
| `jinja2` | HTML templates via Python `string.Template` |
| `strip-ansi` | Regex-based ANSI stripper (`ansi_stripper.py`) |
| `watchdog` | File watcher using `hashlib` + `os.stat` polling |
| `fastapi` / `flask` | Dashboard server via `http.server.BaseHTTPRequestHandler` |
| `gitpython` | Git operations via `subprocess` + `git` CLI |
| `colorama` | ANSI color codes written directly as escape sequences |
| `networkx` | Caller graph as a plain `dict[str, set[str]]` |

---

## Sample Output

```
  PROOFLINE  Change Verification Report
  AI made code generation cheap. Verification did not keep up.

  Severity:   HIGH
  Confidence: 69/100 [INFERRED]
  Risk Score: 79/100 [CRITICAL]

  HIGH because:
    - High complexity (score 20) with NO tests.
    - High complexity (score 11) with NO tests.

  CHANGE COMPLETENESS  auth.validate_token
  Implementation changed:         YES
  Direct callers identified:      10  (1 PROVEN / 9 INFERRED)
  Public routes affected:         3
  Relevant tests changed:         NO
  Remaining verification:
    [ ] [HIGH] Signature change breaks 9 INFERRED callers
    [ ] [HIGH] 3 authenticated routes now use updated token logic
    [ ] [MEDIUM] Add or update tests for validate_token()
```

---

## Honest Limits

Proofline is transparent about its trade-offs:

- **Dynamic calls** (`getattr`, decorators, metaclasses) are flagged as `UNKNOWN` confidence -- static AST cannot resolve runtime dispatch.
- **Test association** is via name/import heuristics, not runtime coverage. It assumes `test_*.py` naming conventions.
- **Large monorepos** may take extra seconds on first scan (no C-extension AST parsers). Subsequent scans use the `hashlib`-based AST cache in `.proofline/cache/`.
- **Proofline never certifies 'safe to merge'** -- it flags what needs human review.

---

## Project Structure

```
proofline/
  cli.py              # Entry point, argument parsing, orchestration
  diff_engine.py      # Git diff parsing and AST-level symbol extraction
  caller_graph.py     # Cross-repo call graph builder (pure dict/set)
  rules_engine.py     # 11 verification rules (R1-R11)
  risk_model.py       # Severity scoring and confidence calculation
  evidence_graph.py   # Evidence aggregator and report data model
  report.py           # HTML/JSON/CLI report renderers
  test_associator.py  # Test file discovery and symbol association
  route_detector.py   # Web framework route detection (Flask/FastAPI/Django)
  symbol_map.py       # Full-repo AST symbol index with caching
  server.py           # Zero-dependency REST API + dashboard HTTP server
  github_integration.py  # GitHub PR comment formatter and poster
  git_utils.py        # Subprocess-based git operations
  watcher.py          # File watcher for --watch mode
  scaffolder.py       # Unittest boilerplate generator
```

---

## License

MIT License -- built for the Zero Dependency Hackathon 2026.
