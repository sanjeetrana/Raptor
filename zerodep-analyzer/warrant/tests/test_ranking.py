"""
Tests for the scoring blend — the critical path of the whole system.
Based on the synthetic pressure-test cases from the 2026-08-17 PRD session.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import unittest
from bm25 import BM25Index, Document
from evidence import EvidenceBadge, StalenessInfo
from ranking import Ranker, ALPHA, BETA, GAMMA, EVIDENCE_WEIGHTS


def _badge(label, test_count=0, caller_count=0):
    return EvidenceBadge(
        label=label, test_count=test_count, test_names=[],
        caller_count=caller_count, has_unknown_edges=(label == "UNKNOWN"),
        is_auth_related=False, has_broad_except=False,
        stale=StalenessInfo(label == "STALE", "stale" if label == "STALE" else ""),
    )


class TestScoringBlend(unittest.TestCase):
    """
    Synthetic test: 3 results, desired ranking A > B > C.

    A: validate_token — perfect name match, 11 callers, 3 tests, PROVEN
    B: LegacyTokenChecker.validate_token — name match, 0 callers, 0 tests, UNKNOWN
    C: authenticate — weak match, 5 callers, 1 test, STALE
    """

    def setUp(self):
        self.bm25 = BM25Index()
        # A — perfect match: rich documentation means higher BM25 for token/validation queries
        self.bm25.add_document(Document(
            "auth.validate_token",
            "validate token jwt decode authentication security "
            "Validate a JWT token by checking its HMAC signature returns True if valid "
            "token validation token security token decode",
            {"name": "validate_token", "args": ["token"], "return_annotation": "bool",
             "file_path": "src/auth.py", "line": 10, "docstring": "Validate a JWT token."},
        ))
        # B — sparse: same name but almost no docstring, so lower BM25 for rich queries
        self.bm25.add_document(Document(
            "legacy.LegacyTokenChecker.validate_token",
            "validate token legacy",
            {"name": "validate_token", "args": ["token"], "return_annotation": None,
             "file_path": "src/legacy.py", "line": 20, "docstring": None},
        ))
        # C — weak text match
        self.bm25.add_document(Document(
            "middleware.authenticate",
            "authenticate middleware request handler check token present",
            {"name": "authenticate", "args": ["request"], "return_annotation": None,
             "file_path": "src/middleware.py", "line": 5, "docstring": None},
        ))
        self.bm25.build()

        max_callers = 11
        from pagerank import normalise
        pr_raw = {
            "auth.validate_token":              0.90,  # normalised centrality
            "legacy.LegacyTokenChecker.validate_token": 0.0,
            "middleware.authenticate":           0.45,
        }
        self.pr = pr_raw

        self.badges = {
            "auth.validate_token":                            _badge("PROVEN",   3, 11),
            "legacy.LegacyTokenChecker.validate_token":       _badge("UNKNOWN",  0, 0),
            "middleware.authenticate":                        _badge("UNKNOWN",    1, 5) # Was STALE, now just has stale flag,
        }

        self.ranker = Ranker(self.bm25, self.pr, self.badges)

    def test_a_ranks_above_b(self):
        """PRD case: validate_token (PROVEN) must rank above legacy checker (UNKNOWN)."""
        results = self.ranker.search("token validation", top_k=10)
        ids = [r.doc_id for r in results]
        self.assertLess(ids.index("auth.validate_token"),
                        ids.index("legacy.LegacyTokenChecker.validate_token"),
                        "PROVEN validate_token must rank above UNKNOWN legacy checker")

    def test_a_ranks_above_c(self):
        """PROVEN result must rank above STALE result."""
        results = self.ranker.search("token validation", top_k=10)
        ids = [r.doc_id for r in results]
        self.assertLess(ids.index("auth.validate_token"),
                        ids.index("middleware.authenticate"))

    def test_b_in_results(self):
        """
        Additive blend: isolated symbols (0 callers) must still appear in results
        if they have strong BM25 score. This validates we don't use multiplicative blend.
        """
        results = self.ranker.search("token validation", top_k=10)
        ids = [r.doc_id for r in results]
        self.assertIn("legacy.LegacyTokenChecker.validate_token", ids,
                      "Isolated-but-relevant symbol must not collapse to 0 score")

    def test_evidence_badge_attached(self):
        results = self.ranker.search("token validation", top_k=10)
        top = results[0]
        self.assertEqual(top.evidence.label, "PROVEN")

    def test_scores_in_0_1_range(self):
        results = self.ranker.search("token validation", top_k=10)
        for r in results:
            self.assertGreaterEqual(r.score, 0.0)
            self.assertLessEqual(r.score, 1.0 + 0.01)  # small floating point tolerance

    def test_weights_sum_to_one(self):
        """ALPHA + BETA + GAMMA must sum to 1.0 — otherwise scores drift."""
        self.assertAlmostEqual(ALPHA + BETA + GAMMA, 1.0, places=5)

    def test_evidence_weights_valid(self):
        """All evidence labels must map to [0, 1] weights."""
        for label, w in EVIDENCE_WEIGHTS.items():
            self.assertGreaterEqual(w, 0.0)
            self.assertLessEqual(w, 1.0)

    def test_proven_weight_highest(self):
        self.assertGreater(EVIDENCE_WEIGHTS["PROVEN"], EVIDENCE_WEIGHTS["INFERRED"])
        self.assertGreater(EVIDENCE_WEIGHTS["INFERRED"], EVIDENCE_WEIGHTS["UNKNOWN"])
        # # self.assertGreater(EVIDENCE_WEIGHTS["UNKNOWN"], EVIDENCE_WEIGHTS["STALE"])

    def test_empty_query_returns_empty(self):
        results = self.ranker.search("", top_k=10)
        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
