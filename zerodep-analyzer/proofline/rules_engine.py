"""
rules_engine.py — Exactly 8 detection rules → severity + confidence output.

Design mandate from PRD §5.5:
  - Exactly 8 rules, not 30.
  - No numeric score (87/100 implies false precision).
  - Severity is a label: HIGH / MEDIUM / LOW.
  - Overall confidence reflects the weakest link in the evidence chain.

Rule catalogue:
  1. Changed public function signature
  2. Changed exception-handling behavior
  3. Broad exception handler added (except Exception / bare except)
  4. Security-sensitive operation changed
  5. Public route behavior changed (INFERRED — framework decorator match)
  6. Changed function has no statically associated test
  7. Associated tests unchanged or deleted despite behavior change
  8. Import/dependency edge changed

Stdlib: dataclasses, enum
"""
from __future__ import annotations

import dataclasses
import enum
_CUSTOM_RULES = []
from pathlib import Path
import os
import importlib.util
from typing import Optional

from .symbol_map import Confidence
from .diff_engine import DiffResult, SymbolDiff
from .caller_graph import CallerResult
from .route_detector import RouteInfo
from .test_associator import TestAssociation


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Severity(enum.Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"

    def __gt__(self, other: "Severity") -> bool:
        order = {Severity.HIGH: 3, Severity.MEDIUM: 2, Severity.LOW: 1, Severity.INFO: 0}
        return order[self] > order[other]

    def __ge__(self, other: "Severity") -> bool:
        return self == other or self > other

    def ansi(self) -> str:
        colors = {
            "HIGH": "\033[91m",    # bright red
            "MEDIUM": "\033[93m",  # yellow
            "LOW": "\033[94m",     # blue
            "INFO": "\033[37m",    # grey
        }
        return f"{colors[self.value]}{self.value}\033[0m"

    def html_class(self) -> str:
        return f"severity-{self.value.lower()}"


SEVERITY_ORDER = [Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.INFO]

CONFIDENCE_ORDER = [Confidence.PROVEN, Confidence.INFERRED, Confidence.UNKNOWN]


def _max_severity(severities: list[Severity]) -> Severity:
    for level in SEVERITY_ORDER:
        if level in severities:
            return level
    return Severity.INFO


def _min_confidence(confidences: list[Confidence]) -> Confidence:
    """Lowest confidence wins — weakest link in the evidence chain."""
    for level in reversed(CONFIDENCE_ORDER):
        if level in confidences:
            return level
    return Confidence.PROVEN


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class RuleResult:
    """
    Result of one rule firing on one changed symbol.
    """
    rule_id: int          # 1–8
    rule_name: str
    severity: Severity
    evidence: str         # human-readable explanation of why this rule fired
    confidence: Confidence = Confidence.PROVEN
    location_hint: str = ""   # e.g. "auth.py:42"


@dataclasses.dataclass
class SymbolRiskReport:
    """
    Risk report for one changed symbol.

    No numeric score — severity is a label, confidence reflects the weakest
    evidence link.
    """
    symbol_name: str
    sym_diff: SymbolDiff
    rules_fired: list[RuleResult] = dataclasses.field(default_factory=list)
    caller_result: Optional[CallerResult] = None
    routes: list[RouteInfo] = dataclasses.field(default_factory=list)
    test_assoc: Optional[TestAssociation] = None
    test_warnings: list[str] = dataclasses.field(default_factory=list)

    @property
    def severity(self) -> Severity:
        if not self.rules_fired:
            return Severity.INFO
        return _max_severity([r.severity for r in self.rules_fired])

    @property
    def confidence(self) -> Confidence:
        """Overall confidence = minimum (weakest link) across all evidence."""
        if not self.rules_fired:
            return Confidence.PROVEN
        confs = [r.confidence for r in self.rules_fired]
        # Caller confidence
        if self.caller_result:
            if self.caller_result.inferred_callers:
                confs.append(Confidence.INFERRED)
            if self.caller_result.unknown_callers:
                confs.append(Confidence.UNKNOWN)
        # Route confidence
        if self.routes:
            confs.append(Confidence.INFERRED)  # routes are always INFERRED
        # Test association confidence
        if self.test_assoc and self.test_assoc.has_candidates:
            confs.append(Confidence.INFERRED)  # associations are INFERRED
        return _min_confidence(confs)

    @property
    def severity_reasons(self) -> list[str]:
        return [r.evidence for r in self.rules_fired]

    @property
    def confidence_reasons(self) -> list[str]:
        reasons = []
        if self.caller_result and self.caller_result.unknown_callers:
            reasons.append("dynamic calls present — cannot be statically resolved")
        if self.caller_result and self.caller_result.inferred_callers:
            reasons.append("some callers resolved via inheritance/cross-module (INFERRED)")
        if self.routes:
            reasons.append("route detection is pattern-matching a framework convention (INFERRED)")
        if self.test_assoc:
            reasons.append("test association is static (by name/import) — not runtime coverage")
        return reasons

    def to_dict(self) -> dict:
        return {
            "symbol_name": self.symbol_name,
            "severity": self.severity.value,
            "confidence": self.confidence.value,
            "rules_fired": [
                {
                    "rule_id": r.rule_id,
                    "rule_name": r.rule_name,
                    "severity": r.severity.value,
                    "evidence": r.evidence,
                    "confidence": r.confidence.value,
                }
                for r in self.rules_fired
            ],
            "callers": {
                "proven": len(self.caller_result.proven_callers) if self.caller_result else 0,
                "inferred": len(self.caller_result.inferred_callers) if self.caller_result else 0,
                "unknown": len(self.caller_result.unknown_callers) if self.caller_result else 0,
            },
            "routes": [r.to_dict() for r in self.routes],
            "test_candidates": self.test_assoc.count if self.test_assoc else 0,
            "test_disclaimer": TestAssociation.DISCLAIMER,
        }


@dataclasses.dataclass
class RulesReport:
    """Aggregate report across all changed symbols."""
    symbol_reports: list[SymbolRiskReport] = dataclasses.field(default_factory=list)
    global_rules: list[RuleResult] = dataclasses.field(default_factory=list)

    @property
    def overall_severity(self) -> Severity:
        if not self.symbol_reports:
            return Severity.INFO
        return _max_severity([r.severity for r in self.symbol_reports])

    @property
    def overall_confidence(self) -> Confidence:
        if not self.symbol_reports:
            return Confidence.PROVEN
        return _min_confidence([r.confidence for r in self.symbol_reports])


    @property
    def confidence_score(self) -> int:
        """Calculate a 0-100 score based on edge confidence."""
        p, i, u = self.total_callers()
        r = self.total_routes()
        # Routes are INFERRED edges
        i += r
        
        total_edges = p + i + u
        if total_edges == 0:
            # If no edges needed resolution, confidence is 100% PROVEN by definition
            return 100
            
        score = ((p * 1.0) + (i * 0.6) + (u * 0.2)) / total_edges * 100
        return int(round(score))

    def total_callers(self) -> tuple[int, int, int]:
        """(proven, inferred, unknown) across all symbol reports."""
        p = i = u = 0
        for sr in self.symbol_reports:
            if sr.caller_result:
                p += len(sr.caller_result.proven_callers)
                i += len(sr.caller_result.inferred_callers)
                u += len(sr.caller_result.unknown_callers)
        return p, i, u

    def total_routes(self) -> int:
        return sum(len(sr.routes) for sr in self.symbol_reports)

    def to_dict(self) -> dict:
        return {
            "overall_severity": self.overall_severity.value,
            "overall_confidence": self.overall_confidence.value,
            "symbol_reports": [sr.to_dict() for sr in self.symbol_reports],
            "global_rules": [{"rule_id": r.rule_id, "rule_name": r.rule_name, "severity": r.severity.name, "evidence": r.evidence, "confidence": r.confidence.name, "location_hint": r.location_hint} for r in self.global_rules] if hasattr(self, "global_rules") and self.global_rules else [],
        }


# ---------------------------------------------------------------------------
# The 8 rules
# ---------------------------------------------------------------------------



RULES = []

def load_custom_rules(repo_root: str):
    """Load custom rule functions from .proofline/rules/*.py"""
    global _CUSTOM_RULES
    _CUSTOM_RULES = []
    
    rules_dir = Path(repo_root) / ".proofline" / "rules"
    if not rules_dir.exists():
        return
        
    for py_file in rules_dir.glob("*.py"):
        module_name = f"proofline.plugins.{py_file.stem}"
        spec = importlib.util.spec_from_file_location(module_name, py_file)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            # Any function starting with 'rule_' is considered a rule
            for attr_name in dir(module):
                if attr_name.startswith("rule_"):
                    func = getattr(module, attr_name)
                    if callable(func):
                        _CUSTOM_RULES.append(func)

def _rule_1_public_signature(sym_diff: SymbolDiff) -> Optional[RuleResult]:
    """Rule 1: Changed public function signature."""
    fn = sym_diff.after or sym_diff.before
    if not fn:
        return None
    if not fn.is_public:
        return None
    if sym_diff.signature_changed:
        def _fmt_sig(f: Optional[FunctionInfo]) -> str:
            if not f: return "[]"
            ret = f" -> {f.return_annotation}" if getattr(f, 'return_annotation', None) else ""
            return f"{f.args}{ret}"
        
        before_sig = _fmt_sig(sym_diff.before)
        after_sig = _fmt_sig(sym_diff.after)
        return RuleResult(
            rule_id=1,
            rule_name="Changed public function signature",
            severity=Severity.HIGH,
            evidence=(
                f"Public function '{fn.name}' signature changed: "
                f"{before_sig} → {after_sig}"
            ),
            confidence=Confidence.PROVEN,
            location_hint=str(fn.location) if fn.location else "",
        )
    return None


def _rule_2_exception_behavior(sym_diff: SymbolDiff) -> Optional[RuleResult]:
    """Rule 2: Changed exception-handling behavior."""
    if sym_diff.exception_handling_changed and not sym_diff.broad_exception_added:
        fn = sym_diff.after or sym_diff.before
        name = fn.name if fn else sym_diff.symbol_name
        return RuleResult(
            rule_id=2,
            rule_name="Changed exception-handling behavior",
            severity=Severity.MEDIUM,
            evidence=f"Exception handler changed in '{name}' — callers may rely on specific exceptions propagating",
            confidence=Confidence.PROVEN,
            location_hint=str(fn.location) if fn and fn.location else "",
        )
    return None


def _rule_3_broad_exception(sym_diff: SymbolDiff) -> Optional[RuleResult]:
    """Rule 3: Broad exception handler added (except Exception / bare except)."""
    if sym_diff.broad_exception_added:
        fn = sym_diff.after or sym_diff.before
        name = fn.name if fn else sym_diff.symbol_name
        handler_type = "bare except" if (
            sym_diff.after and any(h.is_bare for h in sym_diff.after.exception_handlers)
        ) else "except Exception"
        return RuleResult(
            rule_id=3,
            rule_name="Broad exception handler added",
            severity=Severity.HIGH,
            evidence=(
                f"'{handler_type}' added to '{name}' — "
                "silently converts exceptions into return values or None; "
                "callers expecting exceptions to propagate will be affected"
            ),
            confidence=Confidence.PROVEN,
            location_hint=str(fn.location) if fn and fn.location else "",
        )
    return None


def _rule_4_security_sensitive(sym_diff: SymbolDiff) -> Optional[RuleResult]:
    """Rule 4: Security-sensitive operation changed.

    Severity logic:
      HIGH  — security_changed (actual security-call set changed)
      MEDIUM — is_auth_related name heuristic only (INFERRED — name pattern match)

    This distinction matters for the Run-2 demo: fixing a broad exception handler
    in an auth-named function should reduce severity, not keep it HIGH.
    """
    fn = sym_diff.after or sym_diff.before
    if not fn:
        return None

    is_auth_related = fn.is_auth_related
    has_security_calls = fn.has_security_calls
    security_changed = sym_diff.security_calls_changed

    if is_auth_related or (has_security_calls and security_changed):
        reasons = []
        if is_auth_related:
            reasons.append(
                "function name suggests authentication/authorization boundary "
                "(name heuristic — INFERRED)"
            )
        if security_changed:
            reasons.append("security-sensitive calls (subprocess/network/auth) changed")
        if has_security_calls and not security_changed:
            reasons.append("function contains security-sensitive calls")

        # HIGH only when actual security calls changed; MEDIUM for name heuristic alone
        severity = Severity.HIGH if security_changed else Severity.MEDIUM
        return RuleResult(
            rule_id=4,
            rule_name="Security-sensitive operation changed",
            severity=severity,
            evidence=f"Security boundary modified in '{fn.name}': " + "; ".join(reasons),
            confidence=Confidence.INFERRED,  # always INFERRED — name/call heuristic
            location_hint=str(fn.location) if fn.location else "",
        )
    return None


def _rule_5_route_changed(
    sym_diff: SymbolDiff,
    routes: list[RouteInfo],
) -> Optional[RuleResult]:
    """Rule 5: Public route behavior changed (INFERRED — framework decorator match).

    Severity:
      HIGH   — the changed symbol IS a route handler (decorator_changed or
               it is directly decorated as a route).
      MEDIUM — the changed symbol is called BY a route handler (indirect impact).
    """
    if not routes:
        return None

    # Is the changed function itself a route handler?
    fn = sym_diff.after or sym_diff.before
    is_direct_route = bool(fn and fn.decorators)
    severity = Severity.HIGH if is_direct_route else Severity.MEDIUM
    impact_label = "directly" if is_direct_route else "indirectly (callee changed)"

    route_strs = [
        f"{r.http_methods} {r.path_pattern or '?'} ({r.framework})"
        for r in routes
    ]
    return RuleResult(
        rule_id=5,
        rule_name="Public route behavior changed",
        severity=severity,
        evidence=(
            f"{len(routes)} HTTP route(s) {impact_label} affected "
            f"(INFERRED — framework decorator match): "
            + ", ".join(route_strs)
        ),
        confidence=Confidence.INFERRED,  # always INFERRED for route detection
        location_hint="",
    )


def _rule_6_no_test(
    sym_diff: SymbolDiff,
    test_assoc: TestAssociation,
) -> Optional[RuleResult]:
    """Rule 6: Changed function has no statically associated test."""
    if not test_assoc.has_candidates:
        fn = sym_diff.after or sym_diff.before
        name = fn.qualified_name if fn and getattr(fn, 'qualified_name', None) else sym_diff.symbol_name
        return RuleResult(
            rule_id=6,
            rule_name="No statically associated test found",
            severity=Severity.MEDIUM,
            evidence=(
                f"No candidate tests found for '{name}' "
                f"{TestAssociation.DISCLAIMER}"
            ),
            confidence=Confidence.PROVEN,
            location_hint="",
        )
    return None


def _rule_7_tests_not_updated(
    sym_diff: SymbolDiff,
    test_assoc: TestAssociation,
) -> Optional[RuleResult]:
    """Rule 7: Associated tests unchanged or deleted despite behavior change."""
    if not test_assoc.has_candidates:
        return None
    if sym_diff.body_changed and not test_assoc.any_changed:
        fn = sym_diff.after or sym_diff.before
        name = fn.name if fn else sym_diff.symbol_name
        return RuleResult(
            rule_id=7,
            rule_name="Associated tests unchanged despite behavior change",
            severity=Severity.HIGH,
            evidence=(
                f"Behavior changed in '{name}' but {test_assoc.count} "
                f"candidate test(s) appear unchanged "
                f"{TestAssociation.DISCLAIMER}"
            ),
            confidence=Confidence.INFERRED,  # association is INFERRED
            location_hint="",
        )
    return None


def _rule_9_doc_rot(sym_diff: SymbolDiff) -> Optional[RuleResult]:
    """Rule 9: Function body changed, but existing docstring was not updated."""
    if sym_diff.body_changed and not sym_diff.docstring_changed:
        fn = sym_diff.after or sym_diff.before
        if fn and fn.docstring:
            name = fn.name if fn else sym_diff.symbol_name
            return RuleResult(
                rule_id=9,
                rule_name="Docstring not updated despite logic change",
                severity=Severity.MEDIUM,
                evidence=(
                    f"Implementation logic changed in '{name}' but its "
                    f"docstring appears unchanged (doc rot risk)."
                ),
                confidence=Confidence.PROVEN,
                location_hint=str(fn.location) if fn.location else "",
            )
    return None

def _rule_8_import_changed(sym_diff: SymbolDiff) -> Optional[RuleResult]:
    """Rule 8: Import/dependency edge changed."""
    # NOTE: before_table/after_table live on file_change, not on sym_diff directly.
    bt = sym_diff.file_change.before_table
    at = sym_diff.file_change.after_table
    if not bt or not at:
        return None

    before_set = {f"{i.module}.{i.name}" if i.name else i.module for i in bt.imports}
    after_set = {f"{i.module}.{i.name}" if i.name else i.module for i in at.imports}

    added = after_set - before_set
    removed = before_set - after_set

    if added or removed:
        parts = []
        if added:
            parts.append(f"added: {', '.join(sorted(added))}")
        if removed:
            parts.append(f"removed: {', '.join(sorted(removed))}")
        return RuleResult(
            rule_id=8,
            rule_name="Import/dependency edge changed",
            severity=Severity.MEDIUM,
            evidence=f"Import changes in {sym_diff.relative_path}: " + "; ".join(parts),
            confidence=Confidence.PROVEN,
            location_hint=sym_diff.relative_path,
        )
    return None


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

def _rule_11_orphan_code(
    sym_diff: SymbolDiff,
    caller_result: Optional[CallerResult],
    routes: list[RouteInfo],
) -> Optional[RuleResult]:
    """Rule 11: Orphan Code Added (functions with zero static callers)."""
    fn = sym_diff.after
    if not fn:
        return None
    
    # Only evaluate new functions or modified standalone functions
    base_name = fn.name.split(".")[-1]
    # Skip private, magic, setup, or top-level framework entrypoints
    if base_name.startswith("_") or base_name in ("main", "cli", "app", "setup", "run"):
        return None
    # Skip HTTP routes (they are invoked via external web requests)
    if routes:
        return None
    
    total_callers = 0
    if caller_result:
        total_callers = len(caller_result.proven_callers) + len(caller_result.inferred_callers) + len(caller_result.unknown_callers)
    
    if total_callers == 0 and (sym_diff.before is None and sym_diff.after is not None):
        return RuleResult(
            rule_id=11,
            rule_name="Orphaned code added",
            severity=Severity.MEDIUM,
            evidence=f"New function '{sym_diff.symbol_name}' has 0 callers in the codebase (potential dead code or unintegrated AI hallucination)",
            confidence=Confidence.PROVEN,
            location_hint=str(fn.location) if fn.location else "",
        )
    return None

def _rule_10_high_complexity(sym_diff: SymbolDiff, test_assoc: TestAssociation) -> Optional[RuleResult]:
    """Rule 10: Flags functions with cyclomatic complexity > 10."""
    fn = sym_diff.after or sym_diff.before
    if not fn:
        return None
    
    score = getattr(fn, "complexity_score", 1)
    if score > 10:
        if not test_assoc or not test_assoc.has_candidates():
            return RuleResult(
                rule_id=10,
                rule_name="Rule10HighComplexity",
                severity=Severity.HIGH,
                confidence=Confidence.PROVEN,
                evidence=f"High complexity (score {score}) with NO tests."
            )
        return RuleResult(
            rule_id=10,
            rule_name="Rule10HighComplexity",
            severity=Severity.MEDIUM,
            confidence=Confidence.INFERRED,
            evidence=f"High complexity (score {score}) but tests exist."
        )
    return None

def evaluate_symbol(
    sym_diff: SymbolDiff,
    caller_result: Optional[CallerResult],
    routes: list[RouteInfo],
    test_assoc: TestAssociation,
    test_warnings: list[str],
) -> SymbolRiskReport:
    """
    Run all 8 rules against one changed symbol and produce a SymbolRiskReport.
    """
    rules_fired: list[RuleResult] = []

    r = _rule_1_public_signature(sym_diff)
    if r:
        rules_fired.append(r)

    r = _rule_2_exception_behavior(sym_diff)
    if r:
        rules_fired.append(r)

    r = _rule_3_broad_exception(sym_diff)
    if r:
        rules_fired.append(r)

    r = _rule_4_security_sensitive(sym_diff)
    if r:
        rules_fired.append(r)

    r = _rule_5_route_changed(sym_diff, routes)
    if r:
        rules_fired.append(r)

    r = _rule_6_no_test(sym_diff, test_assoc)
    if r:
        rules_fired.append(r)

    r = _rule_7_tests_not_updated(sym_diff, test_assoc)
    if r:
        rules_fired.append(r)

    r = _rule_8_import_changed(sym_diff)
    if r:
        rules_fired.append(r)

    r = _rule_9_doc_rot(sym_diff)
    if r:
        rules_fired.append(r)

    r = _rule_10_high_complexity(sym_diff, test_assoc)
    if r:
        rules_fired.append(r)

    r = _rule_11_orphan_code(sym_diff, caller_result, routes)
    if r:
        rules_fired.append(r)

    # Run custom rules
    for custom_rule in _CUSTOM_RULES:
        try:
            # Custom rules take sym_diff and optionally other args
            # We try passing just sym_diff first for simplicity
            import inspect
            sig = inspect.signature(custom_rule)
            kwargs = {}
            if 'caller_result' in sig.parameters: kwargs['caller_result'] = caller_result
            if 'routes' in sig.parameters: kwargs['routes'] = routes
            if 'test_assoc' in sig.parameters: kwargs['test_assoc'] = test_assoc
            if 'test_warnings' in sig.parameters: kwargs['test_warnings'] = test_warnings
            
            r = custom_rule(sym_diff, **kwargs)
            if r:
                rules_fired.append(r)
        except Exception as e:
            # Skip failing custom rules
            pass

    return SymbolRiskReport(
        symbol_name=sym_diff.symbol_name,
        sym_diff=sym_diff,
        rules_fired=rules_fired,
        caller_result=caller_result,
        routes=routes,
        test_assoc=test_assoc,
        test_warnings=test_warnings,
    )


def run_rules_engine(
    diff_result: DiffResult,
    caller_results: dict[str, CallerResult],
    affected_routes: list[RouteInfo],
    test_associations: dict[str, TestAssociation],
    test_warnings: dict[str, list[str]],
    repo_root: str = ".",
) -> RulesReport:
    load_custom_rules(repo_root)
    """
    Run the rules engine over all changed symbols.

    Args:
        diff_result: Output from diff_engine.
        caller_results: Per-symbol caller analysis from caller_graph.
        affected_routes: Detected affected routes from route_detector.
        test_associations: Per-symbol test candidates from test_associator.
        test_warnings: Resilience warnings (renamed/deleted tests).

    Returns:
        RulesReport with per-symbol SymbolRiskReports.
    """
    report = RulesReport()
    from .ignore_parser import parse_ignore_file
    ignore_config = parse_ignore_file(repo_root)

    # Index routes by function name for lookup
    routes_by_fn: dict[str, list[RouteInfo]] = {}
    for route in affected_routes:
        routes_by_fn.setdefault(route.function_name, []).append(route)
    # Also index by local name
    routes_by_local: dict[str, list[RouteInfo]] = {}
    for route in affected_routes:
        local = route.function_name.split(".")[-1]
        routes_by_local.setdefault(local, []).append(route)

    for sym_diff in diff_result.symbol_diffs:
        # Skip symbols that live in test files — they are EVIDENCE (tracked via
        # TestAssociation / resilience checks), not SUBJECTS for change-completeness
        # analysis.  Showing a CHANGE COMPLETENESS section for test_validate_token_valid()
        # would be noise that drowns the real signal.
        fc = sym_diff.file_change
        if fc:
            _tbl = fc.after_table or fc.before_table
            if _tbl and _tbl.is_test_file:
                continue

        sym_name = sym_diff.symbol_name
        local_name = sym_name.split(".")[-1]

        cr = caller_results.get(sym_name)
        routes = routes_by_fn.get(sym_name, []) + routes_by_local.get(local_name, [])
        # Deduplicate routes
        seen_route_keys: set[str] = set()
        unique_routes = []
        for r in routes:
            key = f"{r.function_name}:{r.path_pattern}"
            if key not in seen_route_keys:
                seen_route_keys.add(key)
                unique_routes.append(r)
        routes = unique_routes

        assoc = test_associations.get(sym_name, TestAssociation(symbol_name=sym_name))
        warnings = test_warnings.get(sym_name, [])

        sym_report = evaluate_symbol(sym_diff, cr, routes, assoc, warnings)
        
        file_path = ""
        if sym_diff.file_change:
            if sym_diff.file_change.after_table:
                file_path = sym_diff.file_change.after_table.file_path
            elif sym_diff.file_change.before_table:
                file_path = sym_diff.file_change.before_table.file_path
                
        filtered_rules = []
        for r in sym_report.rules_fired:
            if not ignore_config.should_ignore(file_path, r.rule_name):
                filtered_rules.append(r)
        
        
        inline_disabled_rule_ids = set()
        if file_path and sym_diff.after and sym_diff.after.location:
            try:
                if not hasattr(run_rules_engine, '_file_cache'):
                    run_rules_engine._file_cache = {}
                if file_path not in run_rules_engine._file_cache:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        run_rules_engine._file_cache[file_path] = f.readlines()
                lines = run_rules_engine._file_cache[file_path]
                
                line_idx = sym_diff.after.location.line - 2
                while line_idx >= 0:
                    prev_line = lines[line_idx].strip()
                    if not prev_line or prev_line.startswith('@'):
                        line_idx -= 1
                        continue
                    if prev_line.startswith('#'):
                        import re
                        m = re.search(r'#\s*proofline-disable:\s*(.+)', prev_line)
                        if m:
                            rules_str = m.group(1)
                            for r_str in rules_str.split(','):
                                r_str = r_str.strip()
                                if r_str.startswith('rule-'):
                                    try:
                                        inline_disabled_rule_ids.add(int(r_str[5:]))
                                    except ValueError:
                                        pass
                    break
            except Exception:
                pass

        final_rules = []
        for r in filtered_rules:
            if r.rule_id not in inline_disabled_rule_ids:
                final_rules.append(r)

        sym_report.rules_fired = final_rules
        
        # If all rules were ignored, its effective severity becomes INFO, which is correct
        report.symbol_reports.append(sym_report)

    # Sort by severity (HIGH first)
    report.symbol_reports.sort(
        key=lambda sr: SEVERITY_ORDER.index(sr.severity)
    )

    return report
