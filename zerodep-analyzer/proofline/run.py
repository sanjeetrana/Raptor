import sys
# Windows terminal encoding fix: ensure stdout can handle Unicode
# characters (─, →, •, ⚠) used in Proofline reports.
if sys.platform == 'win32' and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

"""
run.py — Convenience wrapper for running Proofline from within the package dir.

Usage (from New folder/proofline/):
    python run.py analyze --before demo_repo/baseline --after demo_repo/patch
    python run.py analyze --before demo_repo/baseline --after demo_repo/patch --html report.html
    python run.py analyze --before demo_repo/baseline --after demo_repo/fixed
    python run.py stdlib-notes

This script adds the parent directory to sys.path so 'import proofline' works
whether you're inside the proofline/ package dir or above it.
"""
import sys
from pathlib import Path

# Add the parent of this file to sys.path so 'proofline' is importable
# Works regardless of where you run this from.
_here = Path(__file__).resolve().parent          # .../proofline/
_parent = _here.parent                            # .../New folder/
if str(_parent) not in sys.path:
    sys.path.insert(0, str(_parent))

from proofline.cli import main                    # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
