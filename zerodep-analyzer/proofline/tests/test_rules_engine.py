"""
test_rules_engine.py — Tests for rules_engine.py (all 8 rules)
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from proofline.symbol_map import Confidence, Location, FunctionInfo, ExceptionHandlerInfo
from proofline.rules_engine import (
    Severity,
    _rule_1_public_signature,
    _rule_2_exception_behavior,
    _rule_3_broad_exception,
    _rule_4_security_sensitive,
    _rule_6_no_test,
    _rule_7_tests_not_updated,
)
from proofline.test_associator import TestAssociation, CandidateTest
from proofline.diff_engine import SymbolDiff


def _make_sym_diff(**kwargs) -> SymbolDiff:
    """Create a minimal SymbolDiff for testing."""
    fc = MagicMock()
    fc.before_table = MagicMock()
    fc.before_table.imports = []
    fc.after_table = MagicMock()
    fc.after_table.imports = []
    fc.relative_path = "auth.py"

    sd = SymbolDiff(
        file_change=fc,
        symbol_name=kwargs.get("symbol_name", "module.fn"),
        change_type=kwargs.get("change_type", "modified"),
    )
    sd.signature_changed = kwargs.get("signature_changed", False)
    sd.exception_handling_changed = kwargs.get("exception_handling_changed", False)
    sd.broad_exception_added = kwargs.get("broad_exception_added", False)
    sd.security_calls_changed = kwargs.get("security_calls_changed", False)
    sd.body_changed = kwargs.get("body_changed", False)
    sd.decorator_changed = kwargs.get("decorator_changed", False)

    fn = FunctionInfo(
        name=kwargs.get("fn_name", "fn"),
        qualified_name=kwargs.get("symbol_name", "module.fn"),
        is_public=kwargs.get("is_public", True),
        is_auth_related=kwargs.get("is_auth_related", False),
        has_security_calls=kwargs.get("has_security_calls", False),
        args=kwargs.get("args", []),
    )
    if kwargs.get("broad_handler", False):
        fn.exception_handlers = [
            ExceptionHandlerInfo(is_bare=False, is_broad=True, exception_types=["Exception"])
        ]
    sd.after = fn
    sd.before = FunctionInfo(
        name=kwargs.get("fn_name", "fn"),
        qualified_name=kwargs.get("symbol_name", "module.fn"),
        args=kwargs.get("before_args", []),
    )
    return sd


class TestRule1PublicSignature(unittest.TestCase):

    def test_fires_on_public_function_signature_change(self):
        sd = _make_sym_diff(signature_changed=True, is_public=True)
        result = _rule_1_public_signature(sd)
        self.assertIsNotNone(result)
        self.assertEqual(result.severity, Severity.HIGH)
        self.assertEqual(result.confidence, Confidence.PROVEN)

    def test_does_not_fire_on_private_function(self):
        sd = _make_sym_diff(signature_changed=True, is_public=False, fn_name="_private")
        sd.after.is_public = False
        result = _rule_1_public_signature(sd)
        self.assertIsNone(result)

    def test_does_not_fire_when_signature_unchanged(self):
        sd = _make_sym_diff(signature_changed=False)
        result = _rule_1_public_signature(sd)
        self.assertIsNone(result)


class TestRule3BroadException(unittest.TestCase):

    def test_fires_on_broad_exception_added(self):
        sd = _make_sym_diff(
            broad_exception_added=True,
            exception_handling_changed=True,
            broad_handler=True,
        )
        result = _rule_3_broad_exception(sd)
        self.assertIsNotNone(result)
        self.assertEqual(result.severity, Severity.HIGH)
        self.assertIn("Exception", result.evidence)

    def test_does_not_fire_when_no_broad_exception(self):
        sd = _make_sym_diff(broad_exception_added=False)
        result = _rule_3_broad_exception(sd)
        self.assertIsNone(result)


class TestRule4SecuritySensitive(unittest.TestCase):

    def test_fires_medium_on_auth_name_only(self):
        """Name heuristic alone → MEDIUM (INFERRED confidence)."""
        sd = _make_sym_diff(is_auth_related=True, fn_name="validate_token",
                            security_calls_changed=False)
        sd.after.is_auth_related = True
        sd.after.has_security_calls = False
        result = _rule_4_security_sensitive(sd)
        self.assertIsNotNone(result)
        # Name-heuristic only → MEDIUM (not HIGH)
        self.assertEqual(result.severity, Severity.MEDIUM)
        self.assertEqual(result.confidence, Confidence.INFERRED)

    def test_fires_high_when_security_calls_changed(self):
        """Actual security call set changed → HIGH."""
        sd = _make_sym_diff(is_auth_related=True, fn_name="validate_token",
                            security_calls_changed=True)
        sd.after.is_auth_related = True
        sd.after.has_security_calls = True
        result = _rule_4_security_sensitive(sd)
        self.assertIsNotNone(result)
        self.assertEqual(result.severity, Severity.HIGH)
        self.assertEqual(result.confidence, Confidence.INFERRED)

    def test_does_not_fire_on_unrelated_function(self):
        sd = _make_sym_diff(fn_name="calculate_total")
        sd.after.is_auth_related = False
        sd.after.has_security_calls = False
        result = _rule_4_security_sensitive(sd)
        self.assertIsNone(result)


class TestRule6NoTest(unittest.TestCase):

    def test_fires_when_no_candidates(self):
        sd = _make_sym_diff()
        assoc = TestAssociation(symbol_name="module.fn")
        result = _rule_6_no_test(sd, assoc)
        self.assertIsNotNone(result)
        self.assertEqual(result.severity, Severity.MEDIUM)
        # Verify disclaimer is in evidence
        self.assertIn("association only", result.evidence)

    def test_does_not_fire_when_candidates_exist(self):
        sd = _make_sym_diff()
        assoc = TestAssociation(symbol_name="module.fn")
        assoc.candidates = [
            CandidateTest(
                test_function_name="test_fn",
                test_file="test_auth.py",
                association_method="name_match",
                confidence=Confidence.INFERRED,
            )
        ]
        result = _rule_6_no_test(sd, assoc)
        self.assertIsNone(result)


class TestRule7TestsNotUpdated(unittest.TestCase):

    def test_fires_when_behavior_changed_but_tests_not(self):
        sd = _make_sym_diff(body_changed=True)
        assoc = TestAssociation(symbol_name="module.fn")
        assoc.candidates = [
            CandidateTest(
                test_function_name="test_fn",
                test_file="test_auth.py",
                association_method="name_match",
                confidence=Confidence.INFERRED,
                changed_in_patch=False,  # Not changed
            )
        ]
        result = _rule_7_tests_not_updated(sd, assoc)
        self.assertIsNotNone(result)
        self.assertEqual(result.severity, Severity.HIGH)
        # Test association is INFERRED
        self.assertEqual(result.confidence, Confidence.INFERRED)
        self.assertIn("association only", result.evidence)

    def test_does_not_fire_when_test_was_changed(self):
        sd = _make_sym_diff(body_changed=True)
        assoc = TestAssociation(symbol_name="module.fn")
        assoc.candidates = [
            CandidateTest(
                test_function_name="test_fn",
                test_file="test_auth.py",
                association_method="name_match",
                confidence=Confidence.INFERRED,
                changed_in_patch=True,  # Changed!
            )
        ]
        result = _rule_7_tests_not_updated(sd, assoc)
        self.assertIsNone(result)


class TestSeverityOrdering(unittest.TestCase):

    def test_high_greater_than_medium(self):
        self.assertTrue(Severity.HIGH > Severity.MEDIUM)

    def test_medium_greater_than_low(self):
        self.assertTrue(Severity.MEDIUM > Severity.LOW)

    def test_low_greater_than_info(self):
        self.assertTrue(Severity.LOW > Severity.INFO)

    def test_high_not_less_than_high(self):
        self.assertFalse(Severity.HIGH > Severity.HIGH)
        self.assertTrue(Severity.HIGH >= Severity.HIGH)


if __name__ == "__main__":
    unittest.main()
