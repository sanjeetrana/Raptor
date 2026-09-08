"""
test_test_associator.py — Tests for test_associator.py

Key invariant: every count output must carry the disclaimer
"name/import association only — not runtime coverage"
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from proofline.test_associator import (
    TestAssociation,
    CandidateTest,
    _name_matches,
    _import_matches,
    check_test_resilience,
)
from proofline.symbol_map import Confidence, SymbolTable, ImportInfo, Location
from proofline.diff_engine import compare_directories


class TestNameMatching(unittest.TestCase):

    def test_test_prefix_match(self):
        self.assertTrue(_name_matches("test_validate_token", "validate_token"))

    def test_test_prefix_with_suffix(self):
        self.assertTrue(_name_matches("test_validate_token_expired", "validate_token"))

    def test_suffix_convention(self):
        self.assertTrue(_name_matches("validate_token_test", "validate_token"))

    def test_no_match(self):
        self.assertFalse(_name_matches("test_unrelated_thing", "validate_token"))

    def test_case_insensitive_snake(self):
        # test_VALIDATE_TOKEN (all-caps) matches validate_token (lower)
        # because lower_test = "test_validate_token" == "test_validate_token"
        self.assertTrue(_name_matches("test_VALIDATE_TOKEN", "validate_token"))

    def test_case_insensitive_camel_does_not_match_snake(self):
        # test_ValidateToken (camelCase) does NOT match validate_token (snake_case)
        # because "test_validatetoken" != "test_validate_token" (no underscore boundary)
        self.assertFalse(_name_matches("test_ValidateToken", "validate_token"))

    def test_empty_function_name(self):
        self.assertFalse(_name_matches("test_foo", ""))


class TestImportMatching(unittest.TestCase):

    def _make_table(self, module: str, imports: list) -> SymbolTable:
        return SymbolTable(
            file_path=f"{module}.py",
            module_name=module,
            imports=imports,
        )

    def test_exact_module_match(self):
        test_tbl = self._make_table("tests.test_auth", [
            ImportInfo(module="auth", location=Location(file="test_auth.py", line=1))
        ])
        changed_tbl = self._make_table("auth", [])
        self.assertTrue(_import_matches(test_tbl, changed_tbl))

    def test_submodule_match(self):
        test_tbl = self._make_table("tests.test_api", [
            ImportInfo(module="myapp.auth", location=Location(file="test_api.py", line=1))
        ])
        changed_tbl = self._make_table("myapp.auth", [])
        self.assertTrue(_import_matches(test_tbl, changed_tbl))

    def test_no_match(self):
        test_tbl = self._make_table("tests.test_other", [
            ImportInfo(module="unrelated", location=Location(file="test_other.py", line=1))
        ])
        changed_tbl = self._make_table("auth", [])
        self.assertFalse(_import_matches(test_tbl, changed_tbl))


class TestAssociationModel(unittest.TestCase):

    def test_disclaimer_always_present_in_count_str(self):
        """Hard rule: disclaimer present in every count output."""
        assoc = TestAssociation(symbol_name="module.fn")
        # Empty
        self.assertIn("association only", assoc.count_str())
        self.assertIn("not runtime coverage", assoc.count_str())
        # With candidates
        assoc.candidates = [
            CandidateTest(
                test_function_name="test_fn",
                test_file="test_auth.py",
                association_method="name_match",
                confidence=Confidence.INFERRED,
            )
        ]
        self.assertIn("association only", assoc.count_str())
        self.assertIn("not runtime coverage", assoc.count_str())

    def test_changed_count_str_disclaimer(self):
        assoc = TestAssociation(symbol_name="module.fn")
        assoc.candidates = [
            CandidateTest(
                test_function_name="test_fn",
                test_file="test.py",
                association_method="name_match",
                confidence=Confidence.INFERRED,
                changed_in_patch=True,
            )
        ]
        result = assoc.changed_count_str()
        self.assertIn("association only", result)
        self.assertIn("not runtime coverage", result)

    def test_has_candidates_false_when_empty(self):
        assoc = TestAssociation(symbol_name="module.fn")
        self.assertFalse(assoc.has_candidates)

    def test_any_changed_requires_changed_in_patch(self):
        assoc = TestAssociation(symbol_name="module.fn")
        assoc.candidates = [
            CandidateTest(
                test_function_name="test_fn",
                test_file="test.py",
                association_method="name_match",
                confidence=Confidence.INFERRED,
                changed_in_patch=False,
            )
        ]
        self.assertFalse(assoc.any_changed)
        assoc.candidates[0].changed_in_patch = True
        self.assertTrue(assoc.any_changed)


class TestResilienceCheck(unittest.TestCase):

    def test_detects_renamed_test_file(self):
        """Adversarial case §8: test_auth.py → test_auth_v2.py must be detected."""
        before_dir = tempfile.mkdtemp(prefix="pl_before_")
        after_dir = tempfile.mkdtemp(prefix="pl_after_")
        try:
            # Baseline has test_auth.py
            before_test = Path(before_dir) / "test_auth.py"
            before_test.write_text(
                "def test_validate_token(): pass\n", encoding="utf-8"
            )
            # Source file changed
            before_auth = Path(before_dir) / "auth.py"
            before_auth.write_text("def validate_token(t):\n    return t\n", encoding="utf-8")

            # Patch has test_auth_v2.py (renamed)
            after_test = Path(after_dir) / "test_auth_v2.py"
            after_test.write_text(
                "def test_validate_token(): pass\n", encoding="utf-8"
            )
            # Source file changed (broad exception)
            after_auth = Path(after_dir) / "auth.py"
            after_auth.write_text(
                "def validate_token(t):\n    try:\n        return t\n    except Exception:\n        return None\n",
                encoding="utf-8",
            )

            diff = compare_directories(str(before_dir), str(after_dir))
            warnings = check_test_resilience(diff)

            # There should be a warning about test_auth.py being missing
            has_rename_warning = any(
                "test_auth.py" in w
                for wlist in warnings.values()
                for w in wlist
            )
            self.assertTrue(
                has_rename_warning,
                f"Expected rename warning for test_auth.py. Got: {warnings}"
            )
        finally:
            import shutil
            shutil.rmtree(before_dir, ignore_errors=True)
            shutil.rmtree(after_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
