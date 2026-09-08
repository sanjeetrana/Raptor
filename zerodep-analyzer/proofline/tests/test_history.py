import unittest
import tempfile
import os
import sqlite3
from pathlib import Path
from proofline.history import init_db, save_analysis, get_history
from proofline.rules_engine import RuleResult, Severity
from proofline.evidence_graph import EvidenceGraph

class MockRulesReport:
    def __init__(self, overall_severity, fired_rules):
        self.overall_severity = overall_severity
        self.fired_rules = fired_rules

class TestHistory(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "history.db")
        
        self.commit_info = {
            "hash": "abcdef1234567890",
            "author": "Alice",
            "message": "Fix auth bug"
        }
        
        rule1 = RuleResult(
            rule_id=1,
            rule_name="Rule 1",
            severity=Severity.HIGH,
            evidence="dummy evidence"
        )
        self.rules_report = MockRulesReport(Severity.HIGH, [rule1])
        self.eg = EvidenceGraph()
        
    def tearDown(self):
        self.temp_dir.cleanup()

    def test_init_db(self):
        init_db("dummy_repo", memory_db=self.db_path)
        self.assertTrue(os.path.exists(self.db_path))
        
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in c.fetchall()]
        self.assertIn("history", tables)
        self.assertIn("rule_hits", tables)
        conn.close()

    def test_save_and_get_history(self):
        save_analysis("dummy_repo", self.commit_info, self.rules_report, self.eg, memory_db=self.db_path)
        
        records = get_history("dummy_repo", memory_db=self.db_path)
        self.assertEqual(len(records), 1)
        r = records[0]
        self.assertEqual(r["commit_hash"], "abcdef1234567890")
        self.assertEqual(r["overall_severity"], "HIGH")
        self.assertEqual(r["rules_fired_count"], 1)
        self.assertEqual(r["total_symbols_changed"], 0)

    def test_get_history_limit(self):
        for i in range(5):
            self.commit_info["hash"] = f"hash_{i}"
            save_analysis("dummy_repo", self.commit_info, self.rules_report, self.eg, memory_db=self.db_path)
            
        records = get_history("dummy_repo", limit=3, memory_db=self.db_path)
        self.assertEqual(len(records), 3)

    def test_get_history_no_db(self):
        records = get_history("dummy_repo", memory_db=self.db_path)
        self.assertEqual(len(records), 0)

if __name__ == "__main__":
    unittest.main()
