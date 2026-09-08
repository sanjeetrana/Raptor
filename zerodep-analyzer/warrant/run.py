"""
run.py — Convenience wrapper for running Warrant CLI from within the warrant/ directory.

Usage (from proof/warrant/):
    python run.py index demo_repo/src
    python run.py search "token validation"
    python run.py search "token validation" --repo demo_repo/src
    python run.py stats
"""
import sys
from pathlib import Path

# Inject parent onto path so "import warrant" works
sys.path.insert(0, str(Path(__file__).parent))

from cli import main
sys.exit(main())
