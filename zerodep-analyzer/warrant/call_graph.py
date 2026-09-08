"""
call_graph.py — Build a function call graph from SymbolInfo objects.

The call graph drives PageRank: functions called by many other functions
have higher structural centrality (like pages with many inbound links).

Zero third-party dependencies.
"""
from __future__ import annotations

import dataclasses
from typing import Optional
from symbol_extractor import SymbolInfo, CallRef


@dataclasses.dataclass
class CallerInfo:
    caller: str          # qualified name of caller
    callee: str          # qualified name or short name of callee
    confidence: str      # PROVEN | INFERRED | UNKNOWN


@dataclasses.dataclass
class CallGraphResult:
    # Outbound edges: who does each function call?
    outbound: dict[str, set[str]]   # qname → {callee qnames} — for PageRank input
    # Inbound edges: who calls each function?
    inbound: dict[str, list[CallerInfo]]
    # Counts
    caller_counts: dict[str, int]   # qname → how many unique callers


def build_call_graph(symbols: list[SymbolInfo]) -> CallGraphResult:
    """
    Build a directed call graph from extracted symbols.

    Matching strategy:
      1. Exact qualified name match: "auth.validate_token" in callees
      2. Short name match: "validate_token" in callees
    """
    # Build lookup: short name → list of qnames (for disambiguation)
    short_to_qnames: dict[str, list[str]] = {}
    for sym in symbols:
        short_to_qnames.setdefault(sym.name, []).append(sym.qualified_name)

    all_qnames = {sym.qualified_name for sym in symbols}

    outbound: dict[str, set[str]] = {sym.qualified_name: set() for sym in symbols}
    inbound: dict[str, list[CallerInfo]] = {sym.qualified_name: [] for sym in symbols}

    for sym in symbols:
        for call in sym.calls:
            # Try to resolve callee to a known qualified name
            resolved: Optional[str] = None
            if call.callee in all_qnames:
                resolved = call.callee
            elif call.callee in short_to_qnames:
                candidates = short_to_qnames[call.callee]
                if len(candidates) == 1:
                    resolved = candidates[0]
                else:
                    # Ambiguous — pick first, downgrade to INFERRED
                    resolved = candidates[0]

            if resolved and resolved in all_qnames:
                outbound[sym.qualified_name].add(resolved)
                inbound[resolved].append(CallerInfo(
                    caller=sym.qualified_name,
                    callee=resolved,
                    confidence=call.confidence,
                ))

    caller_counts = {qn: len(callers) for qn, callers in inbound.items()}

    return CallGraphResult(
        outbound=outbound,
        inbound=inbound,
        caller_counts=caller_counts,
    )
