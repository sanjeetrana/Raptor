"""
test_power_features.py — Unit tests for PRD 12.0 Hackathon Power Features.
"""
import unittest
import json
from unittest.mock import MagicMock, patch

from proofline.symbol_map import SymbolTable, FunctionInfo, Location, Confidence
from proofline.diff_engine import SymbolDiff, FileChange, DiffResult
from proofline.caller_graph import CallerResult, GraphEdge
from proofline.route_detector import RouteInfo
from proofline.rules_engine import RuleResult, Severity, SymbolRiskReport, RulesReport, _rule_11_orphan_code
from proofline.evidence_graph import EvidenceGraph, ChangeSummary
from proofline.risk_model import calculate_risk_score, RiskBreakdown
from proofline.github_integration import format_pr_comment_markdown, post_github_pr_comment
from proofline.server import ProoflineAPIHandler
from proofline.single_file_bundler import bundle_to_single_file


class TestRiskModel(unittest.TestCase):
    def test_risk_score_empty_graph(self):
        eg = EvidenceGraph()
        eg.rules_report = RulesReport()
        risk = calculate_risk_score(eg)
        self.assertIsInstance(risk, RiskBreakdown)
        self.assertGreaterEqual(risk.total_score, 0)
        self.assertLessEqual(risk.total_score, 100)
        self.assertEqual(risk.risk_level, "LOW")

    def test_risk_score_high_severity_and_callers(self):
        eg = EvidenceGraph()
        rr = RulesReport()
        fc = FileChange(relative_path="auth.py")
        sym_diff = SymbolDiff(file_change=fc, symbol_name="auth.validate_token", change_type="modified")
        sr = SymbolRiskReport(
            symbol_name="auth.validate_token",
            sym_diff=sym_diff,
            rules_fired=[
                RuleResult(rule_id=1, rule_name="Signature", severity=Severity.HIGH, evidence="Changed"),
                RuleResult(rule_id=3, rule_name="BroadException", severity=Severity.HIGH, evidence="except Exception"),
                RuleResult(rule_id=4, rule_name="Security", severity=Severity.HIGH, evidence="Security boundary"),
            ],
        )
        rr.symbol_reports.append(sr)
        eg.rules_report = rr
        
        eg.change_summaries = [
            ChangeSummary(
                symbol_name="auth.validate_token",
                file="auth.py",
                change_type="modified",
                implementation_changed=True,
                proven_callers=2,
                inferred_callers=6,
                unknown_callers=0,
                severity="HIGH",
            )
        ]

        risk = calculate_risk_score(eg)
        self.assertGreaterEqual(risk.total_score, 50)
        self.assertIn(risk.risk_level, ("HIGH", "CRITICAL"))
        self.assertTrue(any("HIGH" in f for f in risk.factors))


class TestRule11OrphanCode(unittest.TestCase):
    def test_rule_11_fires_on_new_function_with_zero_callers(self):
        fn = FunctionInfo(
            name="calculate_discount",
            qualified_name="pricing.calculate_discount",
            location=Location(file="pricing.py", line=10, col=0),
            docstring="Calculates discount",
            is_public=True,
        )
        fc = FileChange(relative_path="pricing.py")
        sym_diff = SymbolDiff(
            file_change=fc,
            symbol_name="pricing.calculate_discount",
            change_type="added",
            before=None,
            after=fn,
        )
        
        caller_res = CallerResult(symbol_name="pricing.calculate_discount", proven_callers=[], inferred_callers=[], unknown_callers=[])
        res = _rule_11_orphan_code(sym_diff, caller_res, routes=[])
        self.assertIsNotNone(res)
        self.assertEqual(res.rule_id, 11)
        self.assertEqual(res.severity, Severity.MEDIUM)
        self.assertIn("0 callers", res.evidence)

    def test_rule_11_does_not_fire_on_routes_or_functions_with_callers(self):
        fn = FunctionInfo(
            name="handle_request",
            qualified_name="api.handle_request",
            location=Location(file="api.py", line=10, col=0),
            is_public=True,
        )
        fc = FileChange(relative_path="api.py")
        sym_diff = SymbolDiff(
            file_change=fc,
            symbol_name="api.handle_request",
            change_type="added",
            before=None,
            after=fn,
        )
        route = RouteInfo(function_name="api.handle_request", framework="Flask", http_methods=["GET"], path_pattern="/api/v1")
        res_with_route = _rule_11_orphan_code(sym_diff, None, routes=[route])
        self.assertIsNone(res_with_route)
        
        caller_res = CallerResult(
            symbol_name="api.handle_request",
            proven_callers=[GraphEdge(src="main", dst="api.handle_request", confidence=Confidence.PROVEN, location="api.py:1")],
            inferred_callers=[],
            unknown_callers=[],
        )
        res_with_callers = _rule_11_orphan_code(sym_diff, caller_res, routes=[])
        self.assertIsNone(res_with_callers)


class TestGitHubIntegration(unittest.TestCase):
    def test_format_pr_comment_markdown(self):
        eg = EvidenceGraph()
        rr = RulesReport()
        eg.rules_report = rr
        eg.change_summaries = [
            ChangeSummary(
                symbol_name="auth.validate_token",
                file="auth.py",
                change_type="modified",
                implementation_changed=True,
                severity="HIGH",
                proven_callers=1,
                inferred_callers=9,
                unknown_callers=0,
                test_count=2,
                tests_changed=True,
                routes=[],
            )
        ]
        md = format_pr_comment_markdown(eg)
        self.assertIn("Proofline Verification Gate", md)
        self.assertIn("auth.validate_token", md)
        self.assertIn("Zero Dependencies", md)

    @patch("urllib.request.urlopen")
    def test_post_github_pr_comment_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"html_url": "https://github.com/owner/repo/pull/1#issuecomment-123"}).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        eg = EvidenceGraph()
        eg.rules_report = RulesReport()
        ok, msg = post_github_pr_comment("owner/repo", 1, eg, token="fake_token_123")
        self.assertTrue(ok)
        self.assertIn("Successfully posted comment", msg)


class TestRESTAPIHandler(unittest.TestCase):
    def test_api_health_endpoint(self):
        handler = MagicMock(spec=ProoflineAPIHandler)
        handler.path = "/api/health"
        
        sent_data = {}
        def fake_send_json(data, status_code=200):
            sent_data["data"] = data
            sent_data["status"] = status_code

        handler._send_json = fake_send_json
        ProoflineAPIHandler.do_GET(handler)
        
        self.assertEqual(sent_data["status"], 200)
        self.assertEqual(sent_data["data"]["status"], "healthy")
        self.assertTrue(sent_data["data"]["zero_dependency"])

    def test_api_rules_endpoint(self):
        handler = MagicMock(spec=ProoflineAPIHandler)
        handler.path = "/api/rules"
        
        sent_data = {}
        def fake_send_json(data, status_code=200):
            sent_data["data"] = data
            sent_data["status"] = status_code

        handler._send_json = fake_send_json
        ProoflineAPIHandler.do_GET(handler)
        
        self.assertEqual(sent_data["status"], 200)
        self.assertGreaterEqual(len(sent_data["data"]["rules"]), 10)


class TestSingleFileBundler(unittest.TestCase):
    def test_bundle_generates_valid_python_file(self):
        out_file = bundle_to_single_file("proofline_single_test.py")
        self.assertTrue(out_file.exists())
        content = out_file.read_text(encoding="utf-8")
        self.assertIn("_bootstrap_and_run", content)
        self.assertIn("Proofline Standalone Single-File Distribution", content)
        if out_file.exists():
            out_file.unlink()


if __name__ == "__main__":
    unittest.main()
