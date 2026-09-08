"""
evidence_graph.py — Assembles the full evidence chain.

Chain: ChangedLine → ChangedSymbol → Caller(s) → Route(s) → CandidateTest(s) → DocRef(s)

Every node carries a file + line number. No claim without a source location.

Design (Track D data-store pattern):
  The evidence graph is stored as an append-only list of EvidenceNode and
  EvidenceEdge objects. Queries are O(n) linear scans. For hackathon scale
  (hundreds of symbols, not millions) this is correct and auditable.
  The graph serializes to/from JSON via stdlib json — no external serializer.

Package Killer: replaces networkx for graph storage, pydantic for node models.
Stdlib: dataclasses, json, enum
"""
from __future__ import annotations

import dataclasses
import json
from typing import Optional

from .symbol_map import Confidence, Location
from .diff_engine import DiffResult, SymbolDiff
from .caller_graph import CallGraph, CallerResult, GraphEdge
from .route_detector import RouteInfo
from .test_associator import TestAssociation
from .rules_engine import RulesReport, SymbolRiskReport


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class EvidenceNode:
    """A node in the evidence graph."""
    node_id: str           # unique within the graph
    kind: str              # "changed_symbol" | "caller" | "route" | "test" | "doc"
    name: str              # human-readable display name
    file: str              # source file
    line: int              # line number (0 = unknown)
    confidence: Confidence = Confidence.PROVEN
    metadata: dict = dataclasses.field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "kind": self.kind,
            "name": self.name,
            "file": self.file,
            "line": self.line,
            "confidence": self.confidence.value,
            "metadata": self.metadata,
        }


@dataclasses.dataclass
class EvidenceEdge:
    """A directed edge in the evidence graph."""
    src_id: str
    dst_id: str
    relationship: str      # "calls" | "served_by" | "tested_by" | "documented_by"
    confidence: Confidence = Confidence.PROVEN

    def to_dict(self) -> dict:
        return {
            "src_id": self.src_id,
            "dst_id": self.dst_id,
            "relationship": self.relationship,
            "confidence": self.confidence.value,
        }


@dataclasses.dataclass
class VerificationChecklistItem:
    """One item in the "Remaining verification" checklist."""
    action: str            # short imperative: "Test malformed token behavior"
    priority: str          # "HIGH" | "MEDIUM" | "LOW"
    reason: str            # why this item exists


@dataclasses.dataclass
class ChangeSummary:
    """
    The Change Completeness report for one changed symbol (§5.7 of PRD).
    """
    symbol_name: str
    file: str
    change_type: str       # "modified" | "added" | "deleted"
    implementation_changed: bool

    # Callers
    proven_callers: int = 0
    inferred_callers: int = 0
    unknown_callers: int = 0

    # Routes (always INFERRED)
    routes: list[RouteInfo] = dataclasses.field(default_factory=list)

    # Tests (association only — not coverage)
    test_count: int = 0
    tests_changed: bool = False
    test_disclaimer: str = TestAssociation.DISCLAIMER

    # Docs (file-name heuristic)
    doc_references: int = 0
    docs_updated: bool = False

    is_fully_typed: bool = False
    complexity_score: int = 1
    has_docstring: bool = False

    # Checklist
    checklist: list[VerificationChecklistItem] = dataclasses.field(default_factory=list)

    # Risk
    severity: str = "INFO"
    confidence: str = "PROVEN"

    @property
    def total_callers(self) -> int:
        return self.proven_callers + self.inferred_callers + self.unknown_callers

    def to_dict(self) -> dict:
        return {
            "symbol_name": self.symbol_name,
            "file": self.file,
            "change_type": self.change_type,
            "implementation_changed": self.implementation_changed,
            "callers": {
                "proven": self.proven_callers,
                "inferred": self.inferred_callers,
                "unknown": self.unknown_callers,
                "total": self.total_callers,
            },
            "routes": [r.to_dict() for r in self.routes],
            "tests": {
                "count": self.test_count,
                "changed": self.tests_changed,
                "disclaimer": self.test_disclaimer,
            },
            "docs": {
                "references": self.doc_references,
                "updated": self.docs_updated,
            },
            "checklist": [
                {"action": c.action, "priority": c.priority, "reason": c.reason}
                for c in self.checklist
            ],
            "severity": self.severity,
            "confidence": self.confidence,
        }


@dataclasses.dataclass
class EvidenceGraph:
    """
    The complete evidence graph for one analysis run.

    Append-only storage: nodes and edges are only ever added, never mutated.
    This is the Track D data-store innovation — crash-safe, auditable,
    trivially serializable.
    """
    # Append-only storage
    _nodes: list[EvidenceNode] = dataclasses.field(default_factory=list)
    _edges: list[EvidenceEdge] = dataclasses.field(default_factory=list)

    # Per-symbol summaries
    change_summaries: list[ChangeSummary] = dataclasses.field(default_factory=list)

    # Full rules report (for severity/confidence)
    rules_report: Optional[RulesReport] = None

    # Analysis metadata
    before_dir: str = ""
    after_dir: str = ""

    def add_node(self, node: EvidenceNode) -> None:
        self._nodes.append(node)

    def add_edge(self, edge: EvidenceEdge) -> None:
        self._edges.append(edge)

    def nodes(self) -> list[EvidenceNode]:
        return list(self._nodes)

    def edges(self) -> list[EvidenceEdge]:
        return list(self._edges)

    def nodes_by_kind(self, kind: str) -> list[EvidenceNode]:
        return [n for n in self._nodes if n.kind == kind]

    def to_dict(self) -> dict:
        d = {
            "before_dir": self.before_dir,
            "after_dir": self.after_dir,
            "nodes": [n.to_dict() for n in self._nodes],
            "edges": [e.to_dict() for e in self._edges],
            "change_summaries": [cs.to_dict() for cs in self.change_summaries],
            "rules_report": self.rules_report.to_dict() if self.rules_report else None,
        }
        try:
            from .risk_model import calculate_risk_score
            d["risk_assessment"] = dataclasses.asdict(calculate_risk_score(self))
        except Exception:
            pass
        return d

    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON. Stdlib json — no pydantic/marshmallow."""
        return json.dumps(self.to_dict(), indent=indent, default=str)


# ---------------------------------------------------------------------------
# Doc reference detection (file-name heuristic)
# ---------------------------------------------------------------------------

def _find_doc_references(
    symbol_name: str,
    after_dir: str,
) -> list[tuple[str, int]]:
    """
    Heuristically find documentation files that may reference a changed symbol.

    Strategy: look for .md, .rst, .txt files in the after-dir that contain
    the function's bare name as a substring. Returns (file_path, 0) tuples.
    This is INFERRED — text presence ≠ documentation coverage.
    """
    from pathlib import Path
    local_name = symbol_name.split(".")[-1]
    doc_refs: list[tuple[str, int]] = []

    root = Path(after_dir)
    for ext in ("*.md", "*.rst", "*.txt"):
        for doc_file in root.rglob(ext):
            try:
                content = doc_file.read_text(encoding="utf-8", errors="replace")
                if local_name in content:
                    doc_refs.append((str(doc_file), 0))
            except OSError:
                pass

    return doc_refs


# ---------------------------------------------------------------------------
# Checklist generation
# ---------------------------------------------------------------------------

def _generate_checklist(
    sym_report: SymbolRiskReport,
    test_assoc: TestAssociation,
) -> list[VerificationChecklistItem]:
    """
    Generate the "Remaining verification" checklist for one changed symbol.
    """
    items: list[VerificationChecklistItem] = []
    fn = sym_report.sym_diff.after or sym_report.sym_diff.before
    fn_name = fn.name if fn else sym_report.symbol_name.split(".")[-1]

    # Broad exception handler → test all edge cases
    if sym_report.sym_diff.broad_exception_added:
        items.append(VerificationChecklistItem(
            action=f"Test malformed input to {fn_name}()",
            priority="HIGH",
            reason="Broad exception handler may silently swallow errors",
        ))
        items.append(VerificationChecklistItem(
            action=f"Verify callers handle None return from {fn_name}()",
            priority="HIGH",
            reason="Return value changed — was exception, now None",
        ))

    # Security-related
    if fn and fn.is_auth_related:
        items.append(VerificationChecklistItem(
            action=f"Test authentication boundary behavior of {fn_name}()",
            priority="HIGH",
            reason="Auth-related function changed",
        ))

    # Routes
    for route in sym_report.routes:
        path = route.path_pattern or "?"
        methods = "+".join(route.http_methods)
        items.append(VerificationChecklistItem(
            action=f"Test {methods} {path} authorization and error handling",
            priority="HIGH",
            reason=f"HTTP route {path} calls or is {fn_name}()",
        ))

    # No tests
    if not test_assoc.has_candidates:
        items.append(VerificationChecklistItem(
            action=f"Add tests for {fn_name}()",
            priority="MEDIUM",
            reason="No statically associated tests found",
        ))
    elif not test_assoc.any_changed:
        items.append(VerificationChecklistItem(
            action=f"Update/run existing tests for {fn_name}()",
            priority="MEDIUM",
            reason="Behavior changed but associated tests appear unchanged",
        ))

    # Signature changed
    if sym_report.sym_diff.signature_changed:
        items.append(VerificationChecklistItem(
            action=f"Verify all {sym_report.caller_result.total if sym_report.caller_result else '?'} callers handle new signature of {fn_name}()",
            priority="HIGH",
            reason="Function signature changed — callers may break",
        ))

    # Unknown callers
    if sym_report.caller_result and sym_report.caller_result.unknown_callers:
        items.append(VerificationChecklistItem(
            action=f"Manually check dynamic callers of {fn_name}() (getattr / reflection)",
            priority="MEDIUM",
            reason="Dynamic dispatch detected — static analysis cannot enumerate all callers",
        ))

    return items


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_evidence_graph(
    diff_result: DiffResult,
    call_graph: CallGraph,
    caller_results: dict[str, CallerResult],
    affected_routes: list[RouteInfo],
    test_associations: dict[str, TestAssociation],
    test_warnings: dict[str, list[str]],
    rules_report: RulesReport,
) -> EvidenceGraph:
    """
    Assemble the complete evidence graph from all analysis results.

    This is the integration layer — it pulls together diff_engine,
    caller_graph, route_detector, test_associator, and rules_engine
    into a single traversable structure.
    """
    eg = EvidenceGraph(
        before_dir=diff_result.before_dir,
        after_dir=diff_result.after_dir,
        rules_report=rules_report,
    )

    node_counter = [0]

    def _node_id(prefix: str) -> str:
        node_counter[0] += 1
        return f"{prefix}_{node_counter[0]}"

    for sym_report in rules_report.symbol_reports:
        sym_diff = sym_report.sym_diff
        sym_name = sym_report.symbol_name
        fn = sym_diff.after or sym_diff.before

        # --- Changed symbol node ---
        sym_node_id = _node_id("sym")
        sym_node = EvidenceNode(
            node_id=sym_node_id,
            kind="changed_symbol",
            name=sym_name,
            file=fn.location.file if fn and fn.location else sym_diff.relative_path,
            line=fn.location.line if fn and fn.location else 0,
            confidence=Confidence.PROVEN,
            metadata={
                "change_type": sym_diff.change_type,
                "severity": sym_report.severity.value,
            },
        )
        eg.add_node(sym_node)

        # --- Caller nodes ---
        caller_node_ids: dict[str, str] = {}
        if sym_report.caller_result:
            for edge in sym_report.caller_result.all_edges:
                caller_id = _node_id("caller")
                caller_node = EvidenceNode(
                    node_id=caller_id,
                    kind="caller",
                    name=edge.src,
                    file=edge.location.file,
                    line=edge.location.line,
                    confidence=edge.confidence,
                )
                eg.add_node(caller_node)
                eg.add_edge(EvidenceEdge(
                    src_id=caller_id,
                    dst_id=sym_node_id,
                    relationship="calls",
                    confidence=edge.confidence,
                ))
                caller_node_ids[edge.src] = caller_id

        # --- Route nodes ---
        route_node_ids: list[str] = []
        for route in sym_report.routes:
            route_id = _node_id("route")
            route_node = EvidenceNode(
                node_id=route_id,
                kind="route",
                name=f"{'+'.join(route.http_methods)} {route.path_pattern or '?'}",
                file=route.location.file if route.location else "",
                line=route.location.line if route.location else 0,
                confidence=Confidence.INFERRED,  # always INFERRED
                metadata={"framework": route.framework, "decorator": route.decorator_text},
            )
            eg.add_node(route_node)
            eg.add_edge(EvidenceEdge(
                src_id=sym_node_id,
                dst_id=route_id,
                relationship="served_by",
                confidence=Confidence.INFERRED,
            ))
            route_node_ids.append(route_id)

        # --- Test nodes ---
        test_assoc = sym_report.test_assoc
        if test_assoc:
            for candidate in test_assoc.candidates:
                test_id = _node_id("test")
                test_node = EvidenceNode(
                    node_id=test_id,
                    kind="test",
                    name=candidate.test_function_name,
                    file=candidate.test_file,
                    line=candidate.location.line if candidate.location else 0,
                    confidence=Confidence.INFERRED,
                    metadata={
                        "association_method": candidate.association_method,
                        "changed_in_patch": candidate.changed_in_patch,
                        "disclaimer": TestAssociation.DISCLAIMER,
                    },
                )
                eg.add_node(test_node)
                eg.add_edge(EvidenceEdge(
                    src_id=sym_node_id,
                    dst_id=test_id,
                    relationship="tested_by",
                    confidence=Confidence.INFERRED,
                ))

        # --- Doc reference nodes ---
        doc_refs = _find_doc_references(sym_name, diff_result.after_dir)
        for doc_path, doc_line in doc_refs:
            doc_id = _node_id("doc")
            doc_node = EvidenceNode(
                node_id=doc_id,
                kind="doc",
                name=doc_path,
                file=doc_path,
                line=doc_line,
                confidence=Confidence.INFERRED,
            )
            eg.add_node(doc_node)
            eg.add_edge(EvidenceEdge(
                src_id=sym_node_id,
                dst_id=doc_id,
                relationship="documented_by",
                confidence=Confidence.INFERRED,
            ))

        # --- Change summary ---
        cr = sym_report.caller_result
        checklist = _generate_checklist(sym_report, test_assoc or TestAssociation(symbol_name=sym_name))

        summary = ChangeSummary(
            symbol_name=sym_name,
            file=fn.location.file if fn and fn.location else sym_diff.relative_path,
            change_type=sym_diff.change_type,
            implementation_changed=sym_diff.change_type in ("modified", "added"),
            proven_callers=len(cr.proven_callers) if cr else 0,
            inferred_callers=len(cr.inferred_callers) if cr else 0,
            unknown_callers=len(cr.unknown_callers) if cr else 0,
            routes=sym_report.routes,
            test_count=test_assoc.count if test_assoc else 0,
            tests_changed=test_assoc.any_changed if test_assoc else False,
            doc_references=len(doc_refs),
            docs_updated=False,  # static analysis cannot determine this
            checklist=checklist,
            severity=sym_report.severity.value,
            confidence=sym_report.confidence.value,
            is_fully_typed=fn.is_fully_typed if fn else False,
            complexity_score=fn.complexity_score if fn else 1,
            has_docstring=bool(fn.docstring) if fn else False,
        )
        eg.change_summaries.append(summary)

    return eg
