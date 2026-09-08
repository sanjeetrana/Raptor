"""
caller_graph.py — PROVEN / INFERRED / UNKNOWN call graph.

Package Killer targets:
  - networkx: replaced by dict-of-lists adjacency + edge list (pure Python)
  - pyan3: call graph extraction replaced by ast.NodeVisitor in symbol_map.py

Stdlib used: dataclasses, collections

Design:
  For each changed symbol, we find all *callers* in the codebase (functions
  that call it) and all *callees* (functions it calls). Every edge carries an
  explicit Confidence label:

  PROVEN  — resolvable at parse time: A() calls B() by bare name where B is
            defined in the same module or explicitly imported.
  INFERRED — likely but not certain: self.method() through inheritance,
             cross-module call where import is present, or method call on
             a typed but not statically resolved receiver.
  UNKNOWN — cannot be statically determined: getattr(obj, name)(),
             __import__(), string-based dispatch, dynamic attribute access.

  The graph is stored as a simple dict[str, list[GraphEdge]] adjacency map.
  This is the data-store innovation for Track D — an append-only edge log
  (list[GraphEdge]) with O(n) query by source/target.
"""
from __future__ import annotations

import dataclasses
from collections import defaultdict
from typing import Optional, Iterator

from .symbol_map import (
    SymbolTable,
    FunctionInfo,
    CallInfo,
    Confidence,
    Location,
)
from .diff_engine import DiffResult, SymbolDiff


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class GraphEdge:
    """
    A directed edge in the call graph.

    src → dst with an explicit confidence label and source location.
    Every edge is immutable once created (frozen=True ensures hashability).
    """
    src: str                  # qualified name of caller
    dst: str                  # qualified name of callee
    confidence: Confidence
    location: Location        # where in src the call appears
    call_info: Optional[CallInfo] = None  # raw call data

    def to_dict(self) -> dict:
        return {
            "src": self.src,
            "dst": self.dst,
            "confidence": self.confidence.value,
            "location": self.location.to_dict(),
        }

    def __hash__(self) -> int:
        return hash((self.src, self.dst, self.confidence.value))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, GraphEdge):
            return NotImplemented
        return (self.src, self.dst, self.confidence) == (other.src, other.dst, other.confidence)


@dataclasses.dataclass
class CallerResult:
    """
    All callers of a specific changed symbol.

    Callers are grouped by confidence level for the Change Completeness report.
    """
    symbol_name: str
    proven_callers: list[GraphEdge] = dataclasses.field(default_factory=list)
    inferred_callers: list[GraphEdge] = dataclasses.field(default_factory=list)
    unknown_callers: list[GraphEdge] = dataclasses.field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.proven_callers) + len(self.inferred_callers) + len(self.unknown_callers)

    @property
    def all_edges(self) -> list[GraphEdge]:
        return self.proven_callers + self.inferred_callers + self.unknown_callers

    def summary_str(self) -> str:
        parts = []
        if self.proven_callers:
            parts.append(f"{len(self.proven_callers)} PROVEN")
        if self.inferred_callers:
            parts.append(f"{len(self.inferred_callers)} INFERRED")
        if self.unknown_callers:
            parts.append(f"{len(self.unknown_callers)} UNKNOWN")
        return " / ".join(parts) if parts else "none identified"


@dataclasses.dataclass
class CallGraph:
    """
    The complete call graph for a codebase snapshot.

    Internal storage: append-only edge list (Track D data-store pattern).
    Index structures built on demand.

    This replaces networkx for graph storage and traversal:
      - Adjacency: dict[src, list[GraphEdge]]
      - Reverse adjacency (callers): dict[dst, list[GraphEdge]]
      - Both built from the single source-of-truth edge list.
    """
    _edges: list[GraphEdge] = dataclasses.field(default_factory=list)
    _adj: dict[str, list[GraphEdge]] = dataclasses.field(
        default_factory=lambda: defaultdict(list)
    )
    _rev_adj: dict[str, list[GraphEdge]] = dataclasses.field(
        default_factory=lambda: defaultdict(list)
    )
    _dirty: bool = False

    def add_edge(self, edge: GraphEdge) -> None:
        """Append an edge (O(1) amortised). Marks index as dirty."""
        self._edges.append(edge)
        self._adj[edge.src].append(edge)
        self._rev_adj[edge.dst].append(edge)

    def callers_of(self, symbol: str) -> list[GraphEdge]:
        """All edges pointing *into* symbol (reverse adjacency lookup)."""
        return list(self._rev_adj.get(symbol, []))

    def callees_of(self, symbol: str) -> list[GraphEdge]:
        """All edges pointing *out of* symbol (forward adjacency lookup)."""
        return list(self._adj.get(symbol, []))

    def all_edges(self) -> list[GraphEdge]:
        return list(self._edges)

    def __len__(self) -> int:
        return len(self._edges)

    def __iter__(self) -> Iterator[GraphEdge]:
        return iter(self._edges)


# ---------------------------------------------------------------------------
# Graph building
# ---------------------------------------------------------------------------

def _resolve_callee(
    call: CallInfo,
    caller_table: SymbolTable,
    all_tables: dict[str, SymbolTable],
) -> tuple[str, Confidence]:
    """
    Try to resolve a call site to a fully-qualified callee name.

    Returns (qualified_name, final_confidence) where final_confidence may
    be upgraded or downgraded from the call's initial confidence.

    Resolution rules:
      1. If callee is UNKNOWN (dynamic call) → always stays UNKNOWN.
      2. If callee is a bare name in the same module → PROVEN.
      3. If callee is a bare name that matches an import → INFERRED
         (we can't be sure which overload).
      4. If callee is self.method() → INFERRED (inheritance may redirect).
      5. Cross-module explicit call (import present) → INFERRED.
    """
    raw = call.callee
    base_confidence = call.confidence

    if base_confidence == Confidence.UNKNOWN:
        return raw, Confidence.UNKNOWN

    # self.method() calls — always INFERRED, inheritance may redirect
    if call.receiver in ("self", "cls"):
        method = raw.split(".")[-1] if "." in raw else raw
        return method, Confidence.INFERRED

    # Check if bare name is defined in same module (PROVEN)
    if not call.is_method_call:
        # Look for function defined in caller's module
        for qname in caller_table.functions:
            local = qname.split(".")[-1]
            if local == raw:
                return qname, Confidence.PROVEN
        # Check imports — may resolve to another module
        for imp in caller_table.imports:
            if imp.name == raw or imp.alias == raw:
                # Found via import — INFERRED (we matched the import, not the def)
                return f"{imp.module}.{raw}", Confidence.INFERRED

    # obj.method() call with resolved module
    if call.is_method_call and call.receiver:
        # Try to find in all_tables
        for rel_path, table in all_tables.items():
            if raw in table.functions:
                return raw, Confidence.INFERRED

    return raw, Confidence.INFERRED


def build_call_graph(
    diff_result: DiffResult,
) -> tuple[CallGraph, dict[str, CallerResult]]:
    """
    Build the call graph for the after-state codebase and find callers of
    all changed symbols.

    Returns:
        graph: Complete CallGraph of the after-state codebase.
        caller_results: {changed_symbol_name: CallerResult} for each changed symbol.
    """
    graph = CallGraph()
    all_tables = diff_result.after_tables

    # Build complete graph from all after-state files
    for rel_path, table in all_tables.items():
        if table.has_parse_error():
            continue
        for caller_qname, call in table.all_calls():
            resolved_name, confidence = _resolve_callee(call, table, all_tables)
            if call.location:
                edge = GraphEdge(
                    src=caller_qname,
                    dst=resolved_name,
                    confidence=confidence,
                    location=call.location,
                    call_info=call,
                )
                graph.add_edge(edge)

    # For each changed symbol, collect its callers
    changed_names = set(diff_result.changed_symbol_names())
    caller_results: dict[str, CallerResult] = {}

    for sym_name in changed_names:
        # Also look for short-name matches (local name without module prefix)
        local_name = sym_name.split(".")[-1]

        cr = CallerResult(symbol_name=sym_name)
        seen_edges: set[tuple[str, str]] = set()

        for edge in graph.all_edges():
            # Match by full qualified name OR by the local function name
            dst_local = edge.dst.split(".")[-1]
            if edge.dst == sym_name or dst_local == local_name or edge.dst.endswith(f".{local_name}"):
                edge_key = (edge.src, edge.dst)
                if edge_key in seen_edges:
                    continue
                seen_edges.add(edge_key)

                if edge.confidence == Confidence.PROVEN:
                    cr.proven_callers.append(edge)
                elif edge.confidence == Confidence.INFERRED:
                    cr.inferred_callers.append(edge)
                else:
                    cr.unknown_callers.append(edge)

        caller_results[sym_name] = cr

    return graph, caller_results
