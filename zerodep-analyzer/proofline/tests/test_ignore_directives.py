import unittest
import os
import tempfile
from proofline.diff_engine import compare_directories
from proofline.caller_graph import build_call_graph
from proofline.rules_engine import run_rules_engine

class TestIgnoreDirectives(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_dir = self.temp_dir.name
        self.v1_dir = os.path.join(self.repo_dir, "v1")
        self.v2_dir = os.path.join(self.repo_dir, "v2")
        os.makedirs(self.v1_dir)
        os.makedirs(self.v2_dir)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_ignore_directive_suppresses_rule(self):
        v1_code = """
def my_func():
    try:
        pass
    except ValueError:
        pass
"""
        with open(os.path.join(self.v1_dir, "test.py"), "w") as f:
            f.write(v1_code)

        v2_code = """
# proofline-disable: rule-3
def my_func():
    try:
        pass
    except Exception:
        pass
"""
        with open(os.path.join(self.v2_dir, "test.py"), "w") as f:
            f.write(v2_code)

        diff_result = compare_directories(self.v1_dir, self.v2_dir)
        _, caller_results = build_call_graph(diff_result)
        
        report = run_rules_engine(
            diff_result,
            caller_results,
            affected_routes=[],
            test_associations={},
            test_warnings={},
            repo_root=self.repo_dir
        )
        
        sym_reports = report.symbol_reports
        self.assertEqual(len(sym_reports), 1)
        
        rules_fired = [r.rule_id for r in sym_reports[0].rules_fired]
        self.assertNotIn(3, rules_fired)

if __name__ == "__main__":
    unittest.main()
