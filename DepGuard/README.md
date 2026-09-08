# 🛡️ DepGuard

> **Audit AI-generated code.** 
> A zero-dependency static dependency and security auditor for Python projects.

**Target Runtime:** Python 3.14.4


---

## 🛑 The Problem

Half your code is written by an AI that hallucinates package names. The registry it pulls from added 454,600 malicious packages last year alone. 

When you generate Python code, how do you know if `import fastjson_ultra` is a standard library, a local file, or a hallucinated package waiting to be typosquatted? 

**DepGuard** is the counter-move. It answers three questions statically, locally, and safely:
1. What does this project *actually* use?
2. What does this project *claim* to use?
3. What is dangerously executed or completely unknown?

---

## ✨ Features (Standard Library Only)

*   **Dependency Drift Engine:** Parses `pyproject.toml` and `requirements.txt` to compare declared dependencies against what is actually extracted from the Abstract Syntax Tree (AST).
*   **Zero-Execution Discovery:** Safely classifies imports as `stdlib`, `local`, `third-party`, or `unknown` using `importlib.util.find_spec`—without ever executing untrusted target code.
*   **Security Heuristics:** Uses native `ast.NodeVisitor` to flag dangerous API calls like `eval()`, `exec()`, `pickle.loads()`, `subprocess.run(shell=True)`, and dynamic module loading.
*   **CI/CD Enforcer:** A strict `--enforce` mode that exits with status code `1` if third-party runtime dependencies or unknown packages are detected.
*   **JSON & ANSI Terminal Reports:** Generates machine-readable output for tooling and beautifully colorized terminal reports for humans, using raw ANSI escape codes.

---

## 🚀 One-Command Execution

Because DepGuard targets the **Single File Principle** , there is no build step or installation required. It is a fully self-contained Python script.

**Run a standard audit on a directory:**
```bash
python depguard.py scan ./your_project_path
```

**Run in strict zero-dependency enforcement mode (CI/CD friendly):**

```bash
python depguard.py enforce ./your_project_path

```

**Generate a machine-readable JSON report:**

```bash
python depguard.py scan ./your_project_path --format json

```

---

## 🛠️ Zero-Dependency Craft

DepGuard replaces massive industry-standard packages with precise, hand-rolled standard library implementations:

* Replaced **`bandit` / `tree-sitter**` with `ast`.
* Replaced **`tomli`** with Python 3.14's native `tomllib`.
* Replaced **`click`** with `argparse`.
* Replaced **`colorama`** with raw ANSI escape sequences.

> 📖 **Read the full substitution log:** See [`STDLIB.md`](https://github.com/pratyay-garg/DepGuard/blob/main/STDLIB.md)

---

## 📌 Event Context & Hackathon Note

This project was built from scratch for the **Zero Dependency Hackathon** (August 28–31, 2026).

### Zero-Dependency Compliance
- **Runtime Dependencies:** `0` (Standard Library only)
- **Manifest Status:** Empty `requirements.txt`
- **Target Environment:** Python 3.14

### Key Hackathon Links
- **Event Brief & Guidelines:** [Zero Dependency Hackathon](https://unstop.com/hackathons/zero-dependency-72-hour-hackathon-hackathon-raptors-1733673)
- **Organiser:** [Hackathon Raptors](https://unstop.com/c/hackathon-raptors-1980161)
---
## Acknowledgments
I took helps from AI tools like Antigravity and Copilot to build this project. But keeping it aside, i think this is one of those moments where i felt i can also think of some new ideas. Building something so simple but useful, ( maybe only for the people taking part in this project ) is the main thing that matters for me. 😀😀😀

