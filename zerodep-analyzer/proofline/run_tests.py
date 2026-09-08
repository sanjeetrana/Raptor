import sys
if sys.platform == 'win32' and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

"""
run_tests.py — Self-contained test runner that works without make/shell PATH issues.

Usage from project root:
    python proofline/run_tests.py

Or:
    python -c "import subprocess, sys; subprocess.run([sys.executable, 'proofline/run_tests.py'])"

This script:
1. Adds the project root to sys.path
2. Runs all unittest tests
3. Runs the verification gates
"""
import sys
import unittest
from pathlib import Path

# Ensure project root is on path
root = Path(__file__).parent.parent
sys.path.insert(0, str(root))

print("\n\033[96m  Proofline — Test Runner\033[0m\n")
print(f"  Python: {sys.version}")
print(f"  Root: {root}\n")

# --- Run unittest suite ---
print("  \033[1m[1/2] Running stdlib unittest suite...\033[0m\n")

loader = unittest.TestLoader()
start_dir = str(Path(__file__).parent / "tests")
suite = loader.discover(start_dir=start_dir, pattern="test_*.py", top_level_dir=str(root))

runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
result = runner.run(suite)

print()

if result.wasSuccessful():
    print(f"  \033[92m✓ All {result.testsRun} tests passed\033[0m")
else:
    print(f"  \033[91m✗ {len(result.failures)} failure(s), {len(result.errors)} error(s)\033[0m")
    for fail in result.failures:
        print(f"    FAIL: {fail[0]}")
    for err in result.errors:
        print(f"    ERROR: {err[0]}")

# --- Run verify.py gates ---
print("\n  \033[1m[2/2] Running verification gates...\033[0m\n")

import importlib.util, os
verify_path = Path(__file__).parent / "verify.py"

if verify_path.exists():
    # Execute verify.py in the proofline directory context
    orig_dir = os.getcwd()
    os.chdir(str(Path(__file__).parent))
    spec = importlib.util.spec_from_file_location("verify", verify_path)
    verify_mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(verify_mod)
    except SystemExit as e:
        if e.code != 0:
            print(f"\n  \033[91m✗ Verification gates failed (exit code {e.code})\033[0m")
    finally:
        os.chdir(orig_dir)
else:
    print("  verify.py not found — skipping gate checks")

print()

sys.exit(0 if result.wasSuccessful() else 1)
