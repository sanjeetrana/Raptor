"""
git_utils.py — Thin stdlib wrapper around git CLI for --repo mode.

Uses subprocess (stdlib) only. No GitPython, no dulwich.

Stdlib: subprocess, pathlib, hashlib, tempfile, shutil
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional


class GitError(RuntimeError):
    pass


def _git(args: list[str], cwd: str) -> str:
    """Run a git command, return stdout. Raises GitError on failure."""
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            cwd=cwd,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        raise GitError("git not found on PATH. Install git to use --repo mode.")
    if result.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def find_repo_root(path: str) -> str:
    """Find the git root for a given path."""
    try:
        root = _git(["rev-parse", "--show-toplevel"], cwd=path).strip()
        return root
    except GitError:
        raise GitError(f"Not a git repository: {path}")


def resolve_ref(repo_root: str, ref: str) -> str:
    """Resolve a git ref to a commit SHA."""
    return _git(["rev-parse", "--verify", ref], cwd=repo_root).strip()


def changed_python_files(repo_root: str, base_ref: str, head_ref: str = "HEAD", staged: bool = False) -> list[str]:
    """
    Return list of .py files that changed between base_ref and head_ref.
    If staged=True, ignores head_ref and compares base_ref to the git index.
    Paths are relative to repo_root.
    """
    if staged:
        args = ["diff", "--name-only", "--diff-filter=ACM", "--cached", base_ref, "--", "*.py"]
    else:
        args = ["diff", "--name-only", "--diff-filter=ACM", base_ref, head_ref, "--", "*.py"]
    output = _git(args, cwd=repo_root)
    return [f for f in output.strip().splitlines() if f.strip()]


def export_tree_to_tempdir(repo_root: str, ref: str, changed_files: list[str]) -> str:
    """
    Export only the changed Python files at a given ref to a temp directory.
    Returns the path to the temp directory.

    For each file, we use `git show <ref>:<path>` which reads from the object store
    — no working tree required.
    """
    tmpdir = tempfile.mkdtemp(prefix="proofline_")
    for rel_path in changed_files:
        try:
            content = _git(["show", f"{ref}:{rel_path}"], cwd=repo_root)
        except GitError:
            # File didn't exist at this ref (e.g., newly added) — skip
            continue
        dest = Path(tmpdir) / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8", errors="replace")
    return tmpdir


def cleanup_tempdir(tmpdir: str) -> None:
    """Remove a temp directory created by export_tree_to_tempdir."""
    shutil.rmtree(tmpdir, ignore_errors=True)


def get_commit_info(repo_root: str, ref: str) -> dict[str, str]:
    """Return basic commit metadata for display."""
    try:
        sha = resolve_ref(repo_root, ref)
        msg = _git(["log", "-1", "--pretty=%s", sha], cwd=repo_root).strip()
        author = _git(["log", "-1", "--pretty=%an <%ae>", sha], cwd=repo_root).strip()
        date = _git(["log", "-1", "--pretty=%ci", sha], cwd=repo_root).strip()
        return {"sha": sha[:12], "message": msg, "author": author, "date": date}
    except GitError:
        return {"sha": ref, "message": "", "author": "", "date": ""}


def install_pre_commit_hook(repo_root: str, fail_on: str = "HIGH") -> str:
    """
    Install a Proofline pre-commit hook in the git repo.
    Returns the path to the installed hook.
    """
    hooks_dir = Path(repo_root) / ".git" / "hooks"
    hooks_dir.mkdir(exist_ok=True)
    hook_path = hooks_dir / "pre-commit"

    hook_content = f"""#!/bin/sh
# Proofline pre-commit hook
# Installed by: proofline install-hook
# Fail threshold: {fail_on}

set -e

PROOFLINE_CMD=""
if command -v proofline >/dev/null 2>&1; then
    PROOFLINE_CMD="proofline"
elif [ -f "proofline.pyz" ]; then
    PROOFLINE_CMD="python proofline.pyz"
elif [ -f "run.py" ]; then
    PROOFLINE_CMD="python run.py"
else
    echo "[proofline] WARNING: proofline not found on PATH. Skipping analysis." >&2
    exit 0
fi

echo "[proofline] Analyzing staged changes..." >&2
$PROOFLINE_CMD scan --repo . --base HEAD --fail-on {fail_on}
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo "" >&2
    echo "[proofline] Commit blocked: severity >= {fail_on}" >&2
    echo "[proofline] Review the report above, then either:" >&2
    echo "  • Fix the issues, or" >&2
    echo "  • git commit --no-verify  (bypass hook, use at your own risk)" >&2
    exit 1
fi
echo "[proofline] OK — severity below {fail_on} threshold." >&2
exit 0
"""
    hook_path.write_text(hook_content, encoding="utf-8")
    # Make executable on Unix (no-op on Windows but harmless)
    try:
        import stat
        hook_path.chmod(hook_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    except Exception:
        pass

    return str(hook_path)


def install_github_actions(repo_root: str, fail_on: str = "HIGH") -> str:
    """
    Generate a .github/workflows/proofline.yml file for GitHub Actions CI.
    Returns the path to the created workflow file.
    """
    workflows_dir = Path(repo_root) / ".github" / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)
    wf_path = workflows_dir / "proofline.yml"

    # Using {{ }} for literal braces in YAML since this is a Python f-string
    workflow_content = f"""name: Proofline Verification

on:
  pull_request:
    branches: [ main, master ]
  push:
    branches: [ main, master ]

permissions:
  security-events: write
  contents: read

jobs:
  verify:
    name: Proofline Change Verification
    runs-on: ubuntu-latest
    
    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          fetch-depth: 0
      
      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      
      - name: Run Proofline
        run: |
          python run.py scan --repo . --base origin/${{{{github.base_ref}}}} --sarif proofline.sarif --fail-on {fail_on}
        continue-on-error: true
      
      - name: Upload SARIF to GitHub Security
        uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: proofline.sarif
        if: always()
"""
    wf_path.write_text(workflow_content, encoding="utf-8")
    return str(wf_path)
