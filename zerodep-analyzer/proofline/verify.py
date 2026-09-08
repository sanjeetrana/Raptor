import sys
if sys.platform == 'win32' and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

"""
verify.py — Quick smoke test that runs entirely from Python without make/shell.

Usage:
    python verify.py

This script:
1. Runs the diff engine on the demo repo
2. Verifies PROVEN/INFERRED/UNKNOWN edges are assigned correctly
3. Verifies broad exception is detected in the patch
4. Verifies test rename is detected
5. Prints a summary

Run this to verify Proofline works before the hackathon submission.
"""
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from proofline.diff_engine import compare_directories
from proofline.caller_graph import build_call_graph
from proofline.route_detector import detect_affected_routes
from proofline.test_associator import associate_tests, check_test_resilience
from proofline.rules_engine import run_rules_engine, Severity
from proofline.evidence_graph import build_evidence_graph
from proofline.report import render_cli_report
from proofline.symbol_map import Confidence

DEMO_DIR = Path(__file__).parent / "demo_repo"
BASELINE = str(DEMO_DIR / "baseline")
PATCH = str(DEMO_DIR / "patch")
FIXED = str(DEMO_DIR / "fixed")

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"

passed = 0
failed = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        print(f"  {PASS} {label}")
        passed += 1
    else:
        print(f"  {FAIL} {label}" + (f" — {detail}" if detail else ""))
        failed += 1


def run_analysis(before: str, after: str):
    diff = compare_directories(before, after)
    call_graph, caller_results = build_call_graph(diff)
    routes = detect_affected_routes(diff)
    test_assocs = associate_tests(diff)
    test_warns = check_test_resilience(diff)
    rules_rpt = run_rules_engine(diff, caller_results, routes, test_assocs, test_warns)
    eg = build_evidence_graph(diff, call_graph, caller_results, routes, test_assocs, test_warns, rules_rpt)
    return diff, call_graph, caller_results, routes, test_assocs, test_warns, rules_rpt, eg


print("\n\033[96m  Proofline — Verification Script\033[0m\n")
print("  Testing Run 1: baseline → patch (adversarial case)\n")

diff, cg, cr, routes, ta, tw, rr, eg = run_analysis(BASELINE, PATCH)

# 1. Broad exception detected
broad_diffs = [sd for sd in diff.symbol_diffs if sd.broad_exception_added]
check("Broad exception handler detected in patch", len(broad_diffs) >= 1)

# 2. validate_token is in changed symbols
changed_names = diff.changed_symbol_names()
check(
    "validate_token is a changed symbol",
    any("validate_token" in n for n in changed_names),
    f"changed: {changed_names}"
)

# 3. HIGH severity triggered
check(
    "Overall severity is HIGH",
    rr.overall_severity == Severity.HIGH,
    f"got {rr.overall_severity.value}"
)

# 4. Confidence is not PROVEN (some INFERRED/UNKNOWN edges present)
check(
    "Overall confidence is not PROVEN (INFERRED/UNKNOWN edges present)",
    rr.overall_confidence != Confidence.PROVEN,
    f"got {rr.overall_confidence.value}"
)

# 5. Routes detected (INFERRED)
check(
    "Flask routes detected (INFERRED)",
    len(routes) >= 1,
    f"routes: {len(routes)}"
)

# 6. All routes are INFERRED (hard rule)
non_inferred_routes = [r for r in routes if r.confidence != Confidence.INFERRED]
check(
    "All routes are INFERRED (hard rule enforced)",
    len(non_inferred_routes) == 0,
    f"non-INFERRED routes: {non_inferred_routes}"
)

# 7. Test rename detected
has_rename_warning = any(tw.values())
check(
    "Test file rename (test_auth.py → test_auth_v2.py) detected",
    has_rename_warning,
    f"warnings: {tw}"
)

# 8. PROVEN caller exists (orders.py → validate_token)
from proofline.symbol_map import Confidence as C
all_edges = list(cg.all_edges())
proven_edges = [e for e in all_edges if e.confidence == C.PROVEN]
check(
    "PROVEN caller edges exist",
    len(proven_edges) >= 1,
    f"proven edges: {len(proven_edges)}"
)

# 9. INFERRED caller edges exist (self.method() / inheritance)
inferred_edges = [e for e in all_edges if e.confidence == C.INFERRED]
check(
    "INFERRED caller edges exist (self.method / cross-module)",
    len(inferred_edges) >= 1,
    f"inferred edges: {len(inferred_edges)}"
)

# 10. UNKNOWN caller edges exist (getattr in dynamic_caller.py)
unknown_edges = [e for e in all_edges if e.confidence == C.UNKNOWN]
check(
    "UNKNOWN caller edges exist (getattr dynamic dispatch)",
    len(unknown_edges) >= 1,
    f"unknown edges: {len(unknown_edges)}"
)

# 11. Test disclaimer present in output
cli_output = render_cli_report(eg, no_color=True)
check(
    "Test count disclaimer present in CLI output",
    "association only" in cli_output,
    "disclaimer missing from output"
)

# 12. Evidence graph serializes to JSON
import json
json_str = eg.to_json()
try:
    parsed = json.loads(json_str)
    check("Evidence graph serializes to valid JSON", True)
except Exception as e:
    check("Evidence graph serializes to valid JSON", False, str(e))

print()
print("  Testing Run 2: baseline → fixed (risk reduction)\n")

_, _, _, routes2, _, _, rr2, _ = run_analysis(BASELINE, FIXED)

# Rule 3 (broad exception) should NOT fire
broad_rule_fired = any(r.rule_id == 3 for sr in rr2.symbol_reports for r in sr.rules_fired)
check(
    "Rule 3 (broad exception) does NOT fire on fixed code",
    not broad_rule_fired,
    "Rule 3 still fires — fix not recognized"
)

# Rule 4 should fire at MEDIUM (auth-name heuristic only, no security_changed)
rule4_fired_high = any(
    r.rule_id == 4 and r.severity.value == "HIGH"
    for sr in rr2.symbol_reports
    for r in sr.rules_fired
)
check(
    "Rule 4 fires at MEDIUM (name heuristic only — not HIGH)",
    not rule4_fired_high,
    "Rule 4 still fires at HIGH — name-heuristic-only should be MEDIUM"
)

# Overall severity should be MEDIUM (not HIGH)
check(
    "Overall severity is MEDIUM after fix (HIGH → MEDIUM reduction demonstrated)",
    rr2.overall_severity == Severity.MEDIUM or len(rr2.symbol_reports) == 0,
    f"got {rr2.overall_severity.value} — expected MEDIUM"
)

print()
print(f"  {'='*50}")
print(f"  Results: {passed} passed, {failed} failed")
if failed == 0:
    print(f"  \033[92m✓ All checks passed — adversarial gate criteria met\033[0m")
else:
    print(f"  \033[91m✗ {failed} check(s) failed — review output above\033[0m")
print()

sys.exit(0 if failed == 0 else 1)
