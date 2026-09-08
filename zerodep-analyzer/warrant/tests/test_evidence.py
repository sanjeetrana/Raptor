"""Tests for evidence badge computation."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import unittest
from evidence import find_tests, compute_badge, compute_staleness, _test_name_matches
from symbol_extractor import SymbolInfo, CallRef
from call_graph import build_call_graph, CallGraphResult


def _make_sym(name, qname=None, is_test=False, is_auth=False, has_broad=False, docstring=None):
    return SymbolInfo(
        name=name,
        qualified_name=qname or f"mod.{name}",
        file_path=f"mod.py",
        line=1,
        args=[],
        return_annotation=None,
        is_public=True,
        is_async=False,
        is_method=False,
        is_test=is_test,
        docstring=docstring,
        is_auth_related=is_auth,
        has_broad_except=has_broad,
    )


class TestTestNameMatch(unittest.TestCase):
    def test_test_prefix_exact(self):
        self.assertTrue(_test_name_matches("validate_token", "test_validate_token"))

    def test_test_prefix_with_suffix(self):
        self.assertTrue(_test_name_matches("validate_token", "test_validate_token_malformed"))

    def test_suffix_convention(self):
        self.assertTrue(_test_name_matches("validate_token", "validate_token_test"))

    def test_no_match(self):
        self.assertFalse(_test_name_matches("validate_token", "test_login"))

    def test_empty_fn_name(self):
        self.assertFalse(_test_name_matches("", "test_something"))

    def test_empty_test_name(self):
        self.assertFalse(_test_name_matches("validate_token", ""))


class TestFindTests(unittest.TestCase):
    def setUp(self):
        self.sym = _make_sym("validate_token", "auth.validate_token")
        self.test_sym = _make_sym("test_validate_token", "tests.test_validate_token", is_test=True)
        self.other_test = _make_sym("test_login", "tests.test_login", is_test=True)

    def test_finds_matching_test(self):
        tests = find_tests(self.sym, [self.sym, self.test_sym, self.other_test])
        self.assertIn("tests.test_validate_token", tests)

    def test_does_not_find_unrelated_test(self):
        tests = find_tests(self.sym, [self.sym, self.test_sym, self.other_test])
        self.assertNotIn("tests.test_login", tests)

    def test_no_tests_returns_empty(self):
        tests = find_tests(self.sym, [self.sym])
        self.assertEqual(tests, [])


class TestComputeBadge(unittest.TestCase):
    def _cg(self, syms):
        return build_call_graph(syms)

    def test_proven_when_tests_and_callers(self):
        sym = _make_sym("validate_token", "auth.validate_token")
        caller = _make_sym("create_order", "orders.create_order")
        caller.calls = [CallRef(callee="validate_token", confidence="PROVEN")]
        test_sym = _make_sym("test_validate_token", "tests.test_validate_token", is_test=True)
        all_syms = [sym, caller, test_sym]
        cg = self._cg(all_syms)
        badge = compute_badge(sym, all_syms, cg, set())
        self.assertEqual(badge.label, "PROVEN")
        self.assertEqual(badge.test_count, 1)
        self.assertGreater(badge.caller_count, 0)

    def test_unknown_when_no_tests_no_callers(self):
        sym = _make_sym("orphan_fn", "mod.orphan_fn")
        cg = self._cg([sym])
        badge = compute_badge(sym, [sym], cg, set())
        self.assertEqual(badge.label, "UNKNOWN")

    def test_inferred_when_tests_only(self):
        sym = _make_sym("validate_token", "auth.validate_token")
        test_sym = _make_sym("test_validate_token", "tests.test_validate_token", is_test=True)
        cg = self._cg([sym, test_sym])
        badge = compute_badge(sym, [sym, test_sym], cg, set())
        self.assertEqual(badge.label, "INFERRED")

    def test_stale_when_changed_no_docstring(self):
        sym = _make_sym("validate_token", "auth.validate_token", docstring=None)
        cg = self._cg([sym])
        badge = compute_badge(sym, [sym], cg, {"auth.validate_token"})
        self.assertEqual(badge.stale.is_stale, True)

    def test_not_stale_with_good_docstring(self):
        sym = _make_sym("validate_token", "auth.validate_token",
                        docstring="Validates a JWT token by checking the HMAC signature.")
        cg = self._cg([sym])
        badge = compute_badge(sym, [sym], cg, {"auth.validate_token"})
        self.assertEqual(badge.stale.is_stale, False)


class TestDisplayBadge(unittest.TestCase):
    def test_display_proven(self):
        from evidence import EvidenceBadge, StalenessInfo
        b = EvidenceBadge("PROVEN", 2, [], 5, False, False, False, StalenessInfo(False, ""))
        self.assertIn("PROVEN", b.display())
        self.assertIn("[PROVEN]", b.display())

    def test_detail_lines_auth_warning(self):
        from evidence import EvidenceBadge, StalenessInfo
        b = EvidenceBadge("INFERRED", 0, [], 0, False, True, False, StalenessInfo(False, ""))
        details = b.detail_lines()
        self.assertTrue(any("auth" in d.lower() or "security" in d.lower() for d in details))


if __name__ == "__main__":
    unittest.main()
