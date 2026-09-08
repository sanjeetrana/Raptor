"""
test_diff_engine.py — Tests for diff_engine.py
"""
import sys
import os
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from proofline.diff_engine import compare_directories


class TestDiffEngine(unittest.TestCase):

    def setUp(self):
        """Create temp before/after directory pairs."""
        self.before_dir = tempfile.mkdtemp(prefix="proofline_before_")
        self.after_dir = tempfile.mkdtemp(prefix="proofline_after_")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.before_dir, ignore_errors=True)
        shutil.rmtree(self.after_dir, ignore_errors=True)

    def _write(self, d: str, filename: str, content: str) -> str:
        path = os.path.join(d, filename)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        Path(path).write_text(content, encoding="utf-8")
        return path

    def test_detects_modified_file(self):
        self._write(self.before_dir, "mod.py", "def foo():\n    pass\n")
        self._write(self.after_dir, "mod.py", "def foo():\n    return 1\n")
        result = compare_directories(self.before_dir, self.after_dir)
        changed = [fc for fc in result.file_changes if fc.is_modified]
        self.assertTrue(len(changed) >= 1)

    def test_detects_added_file(self):
        self._write(self.after_dir, "new.py", "def bar():\n    pass\n")
        result = compare_directories(self.before_dir, self.after_dir)
        added = result.added_files
        self.assertTrue(len(added) >= 1)
        self.assertTrue(any(fc.relative_path == "new.py" for fc in added))

    def test_detects_deleted_file(self):
        self._write(self.before_dir, "old.py", "def baz():\n    pass\n")
        result = compare_directories(self.before_dir, self.after_dir)
        deleted = result.deleted_files
        self.assertTrue(len(deleted) >= 1)
        self.assertTrue(any(fc.relative_path == "old.py" for fc in deleted))

    def test_unchanged_file_not_reported(self):
        content = "def same():\n    pass\n"
        self._write(self.before_dir, "same.py", content)
        self._write(self.after_dir, "same.py", content)
        result = compare_directories(self.before_dir, self.after_dir)
        # File should not appear in file_changes (hash match)
        self.assertEqual(len(result.file_changes), 0)

    def test_symbol_diff_detects_broad_exception_added(self):
        before = "def fn():\n    x = 1\n"
        after = "def fn():\n    try:\n        x = 1\n    except Exception:\n        pass\n"
        self._write(self.before_dir, "fn.py", before)
        self._write(self.after_dir, "fn.py", after)
        result = compare_directories(self.before_dir, self.after_dir)
        broad_diffs = [sd for sd in result.symbol_diffs if sd.broad_exception_added]
        self.assertTrue(len(broad_diffs) >= 1)

    def test_symbol_diff_detects_signature_change(self):
        before = "def fn(a, b):\n    pass\n"
        after = "def fn(a, b, c):\n    pass\n"
        self._write(self.before_dir, "sig.py", before)
        self._write(self.after_dir, "sig.py", after)
        result = compare_directories(self.before_dir, self.after_dir)
        sig_diffs = [sd for sd in result.symbol_diffs if sd.signature_changed]
        self.assertTrue(len(sig_diffs) >= 1)

    def test_invalid_before_dir_raises(self):
        with self.assertRaises(NotADirectoryError):
            compare_directories("/nonexistent/path", self.after_dir)

    def test_invalid_after_dir_raises(self):
        with self.assertRaises(NotADirectoryError):
            compare_directories(self.before_dir, "/nonexistent/path")

    def test_unified_diff_generated(self):
        self._write(self.before_dir, "diff.py", "x = 1\n")
        self._write(self.after_dir, "diff.py", "x = 2\n")
        result = compare_directories(self.before_dir, self.after_dir)
        modified = [fc for fc in result.file_changes if fc.is_modified]
        self.assertTrue(len(modified) >= 1)
        self.assertTrue(len(modified[0].unified_diff) > 0)

    def test_nested_subdirectory(self):
        self._write(self.before_dir, "sub/deep.py", "def foo(): pass\n")
        self._write(self.after_dir, "sub/deep.py", "def foo(): return 1\n")
        result = compare_directories(self.before_dir, self.after_dir)
        paths = [fc.relative_path for fc in result.file_changes]
        self.assertIn("sub/deep.py", paths)


if __name__ == "__main__":
    unittest.main()
