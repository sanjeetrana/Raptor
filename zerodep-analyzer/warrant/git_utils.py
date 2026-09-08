"""
git_utils.py - Subprocess wrapper to get Git staleness information.

Zero third-party dependencies.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


def get_recently_modified_files(repo_root: Path, days: int = 7) -> set[str]:
    """
    Returns a set of relative file paths that have been modified in the last `days` days.
    If the directory is not a git repository, or git is not installed, returns an empty set.
    """
    try:
        subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True
        )

        result = subprocess.run(
            ["git", "log", "--relative", f"--since={days}.days", "--name-only", "--pretty=format:"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True
        )

        modified_files = set()
        for line in result.stdout.splitlines():
            line = line.strip()
            if line:
                modified_files.add(line)

        return modified_files
    except (subprocess.CalledProcessError, FileNotFoundError):
        return set()

def get_previous_file_content(repo_root: Path, filepath: str) -> str:
    """
    Get the content of a file from the git index/HEAD.
    If the file is modified in the working tree, this gets the last committed version.
    """
    try:
        # Use HEAD:{filepath} to get the committed version
        # Replace backslashes with forward slashes for git
        git_path = filepath.replace("\\", "/")
        result = subprocess.run(
            ["git", "show", f"HEAD:./{git_path}"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True
        )
        return result.stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""
