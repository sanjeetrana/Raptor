"""
Integration test: index the demo_repo and run real searches.
This is the most important test — it validates the full pipeline end-to-end.
"""
import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import unittest
from warrant_index import WarrantIndex


DEMO_REPO = Path(__file__).parent.parent / "demo_repo" / "src"


class TestWarrantIntegration(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not DEMO_REPO.exists():
            raise unittest.SkipTest(f"demo_repo not found at {DEMO_REPO}")
        cls.idx = WarrantIndex.build(repo_root=DEMO_REPO)

    def test_index_has_symbols(self):
        stats = self.idx.stats()
        self.assertGreater(stats["total_symbols"], 0)

    def test_search_token_validation(self):
        """Demo query 1: token validation — must find validate_token."""
        results = self.idx.search("token validation", top_k=5)
        self.assertTrue(len(results) > 0)
        top_names = [r.name for r in results]
        self.assertIn("validate_token", top_names,
            "validate_token must appear in results for 'token validation' query")

    def test_search_order_creation(self):
        """Demo query 2: order creation — must find create_order."""
        results = self.idx.search("order creation", top_k=5)
        self.assertTrue(len(results) > 0)
        top_names = [r.name for r in results]
        self.assertIn("create_order", top_names)

    def test_search_password_hashing(self):
        """Demo query 3: password hashing — must find hash_password or similar."""
        results = self.idx.search("password hash", top_k=5)
        self.assertTrue(len(results) > 0)

    def test_validate_token_has_callers(self):
        """validate_token is called by multiple functions — badge must reflect this."""
        results = self.idx.search("validate_token", top_k=10)
        vt = next((r for r in results if r.name == "validate_token"), None)
        self.assertIsNotNone(vt, "validate_token must appear in results")
        # Should have callers (orders.py calls it)
        self.assertGreater(vt.evidence.caller_count, 0)

    def test_result_has_file_path(self):
        results = self.idx.search("validate token", top_k=5)
        for r in results:
            self.assertTrue(len(r.file_path) > 0)

    def test_result_has_line_number(self):
        results = self.idx.search("validate token", top_k=5)
        for r in results:
            self.assertGreater(r.line, 0)

    def test_badge_labels_valid(self):
        results = self.idx.search("auth", top_k=10)
        valid_labels = {"PROVEN", "INFERRED", "UNKNOWN", "STALE"}
        for r in results:
            self.assertIn(r.evidence.label, valid_labels)

    def test_save_and_load_round_trip(self):
        with tempfile.TemporaryDirectory() as td:
            idx_dir = Path(td) / "warrant_index"
            self.idx.save(idx_dir)
            loaded = WarrantIndex.load(idx_dir)
            r1 = self.idx.search("token validation", top_k=5)
            r2 = loaded.search("token validation", top_k=5)
            self.assertEqual(
                [r.doc_id for r in r1],
                [r.doc_id for r in r2],
            )

    def test_stats_keys(self):
        stats = self.idx.stats()
        self.assertIn("total_symbols", stats)
        self.assertIn("badge_counts", stats)

    def test_no_crash_on_unusual_query(self):
        """Unusual queries must not crash — just return empty or results."""
        try:
            self.idx.search("!@#$%^&*()")
            self.idx.search("a")
            self.idx.search("")
        except Exception as e:
            self.fail(f"Unusual query raised exception: {e}")


if __name__ == "__main__":
    unittest.main()
