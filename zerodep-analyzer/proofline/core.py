import os
import sys
from pathlib import Path

from proofline.diff_engine import compare_directories
from proofline.caller_graph import build_call_graph
from proofline.route_detector import detect_affected_routes
from proofline.test_associator import associate_tests, check_test_resilience
from proofline.rules_engine import run_rules_engine
from proofline.deps_auditor import check_dependencies, Severity
from proofline.evidence_graph import build_evidence_graph

def run_analysis(before_dir: str, after_dir: str, staged=False, commit=False):
    """Core analysis logic extracted to avoid circular imports and top-level exits."""
    
    before_dir = str(Path(before_dir).resolve())
    after_dir = str(Path(after_dir).resolve())

    # We ignore staged and commit flags here since the core relies on directory comparison
    # (The git wrapper handles checking out staged/commit into temp dirs before calling this)
    diff_result = compare_directories(before_dir, after_dir)
    call_graph, caller_results = build_call_graph(diff_result)
    affected_routes = detect_affected_routes(diff_result)
    test_associations = associate_tests(diff_result)
    test_warnings = check_test_resilience(diff_result)

    rules_report = run_rules_engine(
        diff_result, caller_results, affected_routes,
        test_associations, test_warnings,
        repo_root=str(Path(".").resolve()),
    )
    
    try:
        from proofline.deps_auditor import check_dependencies
        global_rules = check_dependencies(before_dir, after_dir)
        if hasattr(rules_report, "global_rules"):
            rules_report.global_rules.extend(global_rules)
    except ImportError:
        pass

    eg = build_evidence_graph(
        diff_result, call_graph, caller_results,
        affected_routes, test_associations, test_warnings,
        rules_report,
    )
    
    # Return as tuple, which tui.py and watcher.py unpack
    # To match test's mock, we return exactly 8 elements:
    # diff_result, call_graph, caller_results, affected_routes, test_associations, test_warnings, rules_report, eg
    return diff_result, call_graph, caller_results, affected_routes, test_associations, test_warnings, rules_report, eg
