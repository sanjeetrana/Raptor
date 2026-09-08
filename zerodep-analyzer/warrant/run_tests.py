"""
run_tests.py — One-shot test runner for Warrant.

Usage:
    python run_tests.py

Runs all unit tests and the integration test.
"""
import sys
import unittest
from pathlib import Path

# Ensure warrant package is on path
sys.path.insert(0, str(Path(__file__).parent))

def main():
    print("\n  Warrant — Test Runner")
    print(f"  Python: {sys.version}")
    print(f"  Root:   {Path(__file__).parent}\n")

    loader = unittest.TestLoader()
    suite = loader.discover(
        start_dir=str(Path(__file__).parent / "tests"),
        pattern="test_*.py",
    )

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print()
    if result.wasSuccessful():
        print(f"  v All {result.testsRun} tests passed")
        return 0
    else:
        print(f"  x {len(result.failures)} failures, {len(result.errors)} errors")
        return 1


if __name__ == "__main__":
    sys.exit(main())
