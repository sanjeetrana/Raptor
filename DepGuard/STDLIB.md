# STDLIB.md — Standard Library Substitution Log

## Project: DepGuard
**Target Runtime:** Python 3.14  
**Runtime Manifest:** Empty (`requirements.txt` contains 0 dependencies)  
**Hackathon Track:** Track A — Developer Tools & CLI  

---

## Executive Summary

DepGuard is a zero-dependency static auditor for Python projects designed to detect dependency drift, undeclared packages, unknown imports, and dangerous API calls. 

To achieve a strictly empty dependency manifest, DepGuard relies entirely on primitives provided by the Python 3.14 standard library. This document details every third-party package that would typically be used in an industry-standard security/auditing CLI and explains how standard-library functionality was leveraged instead.

---

## Standard Library Substitutions (12 Logged)

| # | Package Replaced | Standard Library Module | Category | Rationale & Implementation Detail |
|---|---|---|---|---|
| **1** | `tomli` / `toml` | `tomllib` | Configuration Parsing | Replaced third-party TOML parsers with `tomllib` (introduced in Python 3.11) to parse `pyproject.toml` dependency manifests natively from binary streams. |
| **2** | `bandit` | `ast` (`ast.NodeVisitor`) | Security Analysis | Replaced external static security analyzers by implementing a custom `ast.NodeVisitor` that inspects Python Abstract Syntax Trees for dangerous calls (`eval`, `exec`, `pickle.loads`, `subprocess(shell=True)`). |
| **3** | `tree-sitter` / `parso` | `ast` | Code Parsing | Replaced heavy C-bound code parsers with Python's native `ast.parse()` to extract `Import` and `ImportFrom` nodes without external binary bindings. |
| **4** | `packaging` / `pkg_resources` | `re` (Custom Parser) | Dependency Spec Parsing | Replaced `packaging.requirements` by writing a targeted regular-expression parser to extract normalized base package names from `requirements.txt` files. |
| **5** | `importlib_metadata` / `pkgutil` | `importlib.util.find_spec()` | Module Discovery | Replaced runtime package lookup libraries with `importlib.util.find_spec()` to verify whether an imported package exists in the current environment without executing target code. |
| **6** | `stdlib-list` / `isort` internals | `sys.stdlib_module_names` | Stdlib Detection | Replaced hardcoded standard-library lists with `sys.stdlib_module_names` to dynamically classify imports as standard library members across Python versions. |
| **7** | `click` / `typer` | `argparse` | CLI Interface | Replaced third-party CLI frameworks with `argparse` using subcommands (`scan`, `enforce`), custom help formatters, and POSIX exit code mappings. |
| **8** | `rich` / `colorama` | Raw ANSI Escape Sequences | Terminal Formatting | Replaced terminal styling libraries by using raw ANSI escape codes (`\033[31m`, `\033[32m`, etc.) while respecting environment conventions. |
| **9** | `pydantic` / `attrs` | `dataclasses` & `enum.Enum` | Data Modeling | Replaced runtime data validation frameworks with standard `@dataclass` objects and typed `Enum` classes for `ImportRecord`, `Finding`, and `Project` domain models. |
| **10** | `pytest` | `unittest` | Testing Suite | Replaced external test frameworks with `unittest.TestCase` and `unittest` test discovery to maintain a zero-dependency test suite in `tests/`. |
| **11** | `glob2` / `scandir` | `pathlib.Path` | Filesystem Traversal | Replaced filesystem walking libraries with object-oriented `pathlib.Path.iterdir()` traversal and exclusion set matching (`.git`, `venv`, `__pycache__`). |
| **12** | `orjson` / `ujson` | `json` | Report Serialization | Replaced third-party JSON serializers with standard `json.dumps(..., indent=2)` for generating structured machine-readable `--format json` audit reports. |

---

## Architectural Deep Dive into Key Substitutions

### 1. Static Security Inspection via `ast.NodeVisitor` (Replacing `bandit`)
Rather than relying on `bandit` or regex-based pattern matching (which suffers from high false-positive rates on comments and variable names), DepGuard walks the formal Abstract Syntax Tree using `ast.NodeVisitor`. 

```python
# Extracting calls statically without external tooling
class SecurityNodeVisitor(ast.NodeVisitor):
    def visit_Call(self, node: ast.Call):
        # Inspects AST Call nodes for eval/exec/pickle/subprocess
        ...
```
### 2. Safe Installed-Module Resolution via `importlib.util` (Replacing `pkg_resources`)

Executing `__import__(module)` to check if a package is installed poses a severe supply-chain risk because top-level package code runs on import. DepGuard uses `importlib.util.find_spec(module_name)` to statically query module availability without executing untrusted code.

### 3. Native TOML Parsing via `tomllib` (Replacing `tomli`)

DepGuard leverages Python 3.14's built-in `tomllib` module to read `pyproject.toml` manifests in binary mode (`open(path, "rb")`), successfully extracting `project.dependencies` without third-party dependencies.

---

## Honest Trade-offs & Limitations

In accordance with hackathon guidelines, we document the following standard-library trade-offs:

1. **TOML Writing:** Python's `tomllib` is read-only by design. DepGuard reads `pyproject.toml` to audit dependencies, but does not modify or write TOML manifests.
2. **Dynamic Spec Evaluation:** `importlib.util.find_spec()` resolves installed modules in the current environment context; offline analysis of uninstalled target environments relies on manifest matching.
3. **Complex C-Extensions:** Static `ast` analysis operates on Python source code; compiled `.so` / `.pyd` extensions without Python stubs are categorized using import references rather than symbol analysis.



