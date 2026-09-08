"""Tests for BM25 text ranking engine."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import unittest
from bm25 import BM25Index, Document, tokenize


class TestTokenizer(unittest.TestCase):
    def test_camel_case_split(self):
        tokens = tokenize("validateToken")
        self.assertIn("validate", tokens)
        self.assertIn("token", tokens)

    def test_snake_case_split(self):
        tokens = tokenize("validate_token")
        self.assertIn("validate", tokens)
        self.assertIn("token", tokens)

    def test_stop_words_removed(self):
        tokens = tokenize("the token is valid")
        self.assertNotIn("the", tokens)
        self.assertNotIn("is", tokens)
        self.assertIn("token", tokens)
        self.assertIn("valid", tokens)

    def test_short_tokens_removed(self):
        tokens = tokenize("a b c abc")
        self.assertNotIn("a", tokens)
        self.assertNotIn("b", tokens)
        self.assertNotIn("c", tokens)
        self.assertIn("abc", tokens)

    def test_empty_string(self):
        self.assertEqual(tokenize(""), [])


class TestBM25Index(unittest.TestCase):
    def setUp(self):
        self.idx = BM25Index()
        docs = [
            Document("auth.validate_token",
                     "validate token jwt decode authentication security",
                     {"name": "validate_token"}),
            Document("auth.login",
                     "login username password authenticate session",
                     {"name": "login"}),
            Document("utils.slugify",
                     "slugify text url slug convert lowercase",
                     {"name": "slugify"}),
        ]
        for d in docs:
            self.idx.add_document(d)
        self.idx.build()

    def test_search_returns_relevant(self):
        results = self.idx.search("token validation")
        self.assertTrue(len(results) > 0)
        top_doc_id = results[0][0]
        self.assertEqual(top_doc_id, "auth.validate_token")

    def test_search_no_match_returns_empty(self):
        results = self.idx.search("xyzzy quantum flux")
        self.assertEqual(results, [])

    def test_unrelated_query_ranks_correctly(self):
        results = self.idx.search("login password")
        self.assertTrue(len(results) > 0)
        self.assertEqual(results[0][0], "auth.login")

    def test_scores_are_positive(self):
        results = self.idx.search("token")
        for _, score in results:
            self.assertGreater(score, 0)

    def test_top_k_respected(self):
        results = self.idx.search("auth", top_k=1)
        self.assertLessEqual(len(results), 1)

    def test_document_count(self):
        self.assertEqual(len(self.idx), 3)

    def test_get_document(self):
        doc = self.idx.get("auth.validate_token")
        self.assertIsNotNone(doc)
        self.assertEqual(doc.doc_id, "auth.validate_token")

    def test_get_missing_document(self):
        self.assertIsNone(self.idx.get("does.not.exist"))

    def test_json_round_trip(self, tmp_path=None):
        import json, tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "idx.json"
            self.idx.save(p)
            loaded = BM25Index.load(p)
            r1 = self.idx.search("token")
            r2 = loaded.search("token")
            self.assertEqual(r1, r2)

    def test_empty_query(self):
        self.assertEqual(self.idx.search(""), [])

    def test_build_idempotent(self):
        self.idx.build()  # second build should not raise or break search
        results = self.idx.search("token")
        self.assertTrue(len(results) > 0)


class TestBM25ScoringBlend(unittest.TestCase):
    """
    Synthetic test cases that validate the scoring blend produces correct rankings.
    See: PRD pressure-test from 2026-08-17 planning session.
    """

    def setUp(self):
        self.idx = BM25Index()
        # Result A: perfect name match, full docstring
        self.idx.add_document(Document(
            "auth.validate_token",
            "validate token jwt decode authentication security "
            "Validate a JWT token by checking its HMAC signature returns True if valid",
            {"name": "validate_token"},
        ))
        # Result B: name match, sparse docstring
        self.idx.add_document(Document(
            "legacy.LegacyTokenChecker.validate_token",
            "validate token legacy checker",
            {"name": "validate_token"},
        ))
        # Result C: weak text match (token appears once in comment)
        self.idx.add_document(Document(
            "middleware.authenticate",
            "authenticate middleware request handler check token present",
            {"name": "authenticate"},
        ))
        self.idx.build()

    def test_validate_token_ranks_first_for_token_query(self):
        """PRD synthetic case: validate_token must rank above authenticate."""
        results = self.idx.search("token validation")
        doc_ids = [r[0] for r in results]
        auth_idx = doc_ids.index("auth.validate_token")
        middleware_idx = doc_ids.index("middleware.authenticate")
        self.assertLess(auth_idx, middleware_idx,
            "auth.validate_token must rank above middleware.authenticate")

    def test_legacy_token_checker_in_results(self):
        """Result B (legacy token checker) must appear in results despite sparse doc."""
        results = self.idx.search("token validation")
        doc_ids = [r[0] for r in results]
        self.assertIn("legacy.LegacyTokenChecker.validate_token", doc_ids,
            "Legacy token checker must appear in results (not collapsed to 0)")


if __name__ == "__main__":
    unittest.main()
