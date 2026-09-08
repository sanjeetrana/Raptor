"""
evidence.py - Evidence badge computation per symbol.

This is the Proofline-derived confidence model, adapted for search results.
Each symbol gets a confidence badge (PROVEN | INFERRED | UNKNOWN) and an
orthogonal staleness flag (is_stale). These are independent axes:
- Confidence: how sure are we the evidence is real?
- Freshness: is that evidence current?
A function can be PROVEN but STALE (tested, but tests are outdated).

Badge meaning:
  PROVEN  - high-confidence evidence (direct callers, tests found)
  INFERRED - heuristic evidence (name-match tests, indirect callers)
  UNKNOWN  - no evidence or dynamic dispatch gaps
  (Staleness is an orthogonal flag, not a label — see StalenessInfo)

Zero third-party dependencies.
"""
from __future__ import annotations

import dataclasses
import re
from pathlib import Path
from typing import Optional
from symbol_extractor import SymbolInfo, extract_symbols_from_source
from git_utils import get_previous_file_content
from call_graph import CallGraphResult


# ── Test association ──────────────────────────────────────────────────────────

_DISCLAIMER = "(name/import association only - not runtime coverage)"


def _test_name_matches(fn_name: str, test_name: str) -> bool:
    """
    Does test_name plausibly cover fn_name?

    Conventions checked:
      test_validate_token      matches  validate_token
      test_validate_token_*    matches  validate_token
      validate_token_test      matches  validate_token
    """
    if not fn_name or not test_name:
        return False
    fn_lower = fn_name.lower()
    t_lower = test_name.lower()
    # test_fn_name prefix
    if t_lower == f"test_{fn_lower}":
        return True
    if t_lower.startswith(f"test_{fn_lower}_"):
        return True
    # fn_name_test suffix
    if t_lower == f"{fn_lower}_test":
        return True
    # fn_name anywhere in test name
    if fn_lower in t_lower:
        return True
    return False


def find_tests(
    symbol: SymbolInfo,
    all_symbols: list[SymbolInfo],
) -> list[str]:
    """
    Return qualified names of tests that plausibly cover this symbol.
    Uses name heuristic only (INFERRED confidence).
    """
    return [
        s.qualified_name
        for s in all_symbols
        if s.is_test and _test_name_matches(symbol.name, s.name)
    ]


# ── Staleness ─────────────────────────────────────────────────────────────────

@dataclasses.dataclass
class StalenessInfo:
    is_stale: bool
    reason: str          # human-readable reason for staleness flag


def compute_staleness(symbol: SymbolInfo, recent_changes: set[str], repo_root: Optional[Path] = None) -> StalenessInfo:
    """
    Doc Rot Detection:
    A symbol is STALE if it appears in recent_changes (modified files)
    and its AST logic changed but its docstring did not.
    """
    if symbol.qualified_name not in recent_changes and symbol.file_path not in recent_changes:
        return StalenessInfo(is_stale=False, reason="")
        
    if not repo_root or not symbol.docstring:
        # Fallback to simple check if we can't do doc-rot
        if not symbol.docstring or len(symbol.docstring.strip()) < 20:
            return StalenessInfo(
                is_stale=True,
                reason="recently changed but docstring is absent or very short",
            )
        return StalenessInfo(is_stale=False, reason="")
        
    # Doc Rot detection: compare previous file version
    prev_source = get_previous_file_content(repo_root, symbol.file_path)
    if not prev_source:
        return StalenessInfo(is_stale=False, reason="")
        
    prev_symbols = extract_symbols_from_source(prev_source, symbol.file_path)
    old_sym = next((s for s in prev_symbols if s.qualified_name == symbol.qualified_name), None)
    
    if old_sym:
        # Check if logic changed but docstring stayed exactly the same
        logic_changed = old_sym.ast_hash != symbol.ast_hash
        doc_unchanged = old_sym.docstring == symbol.docstring
        
        if logic_changed and doc_unchanged:
            return StalenessInfo(
                is_stale=True,
                reason="Doc Rot: logic changed but docstring wasn't updated",
            )
            
    return StalenessInfo(is_stale=False, reason="")


# ── Evidence badge ────────────────────────────────────────────────────────────

@dataclasses.dataclass
class EvidenceBadge:
    label: str             # PROVEN | INFERRED | UNKNOWN  (staleness is orthogonal, see .stale)
    test_count: int
    test_names: list[str]
    caller_count: int
    has_unknown_edges: bool
    is_auth_related: bool
    has_broad_except: bool
    stale: StalenessInfo
    disclaimer: str = _DISCLAIMER

    def display(self) -> str:
        """One-line badge for CLI output."""
        icons = {
            "PROVEN":   "[PROVEN]",
            "INFERRED": "[INFERRED]",
            "UNKNOWN":  "[UNKNOWN]",
        }
        icon = icons.get(self.label, "[UNKNOWN]")
        base = f"{icon} {self.label}"
        if self.stale.is_stale:
            return f"{base}  -  [STALE] STALE"
        return base

    def detail_lines(self) -> list[str]:
        """Multi-line detail for CLI result display."""
        lines = []
        if self.caller_count > 0:
            lines.append(f"Called by {self.caller_count} function(s)")
        else:
            lines.append("No callers found (isolated or entry point)")
        if self.has_unknown_edges:
            lines.append("[!] Dynamic dispatch edges present (UNKNOWN confidence)")
        if self.test_count > 0:
            lines.append(
                f"{self.test_count} test(s) associated {self.disclaimer}"
            )
        else:
            lines.append(f"No tests associated {self.disclaimer}")
        if self.is_auth_related:
            lines.append("[!] Auth/security-sensitive (name heuristic - INFERRED)")
        if self.has_broad_except:
            lines.append("[!] Broad exception handler found (except Exception / bare except)")
        if self.stale.is_stale:
            lines.append(f"[STALE] STALE: {self.stale.reason}")
        return lines


def compute_badge(
    symbol: SymbolInfo,
    all_symbols: list[SymbolInfo],
    cg: CallGraphResult,
    recent_changes: set[str],
    repo_root: Optional[Path] = None,
) -> EvidenceBadge:
    """Compute the evidence badge for one symbol."""
    tests = find_tests(symbol, all_symbols)
    callers = cg.inbound.get(symbol.qualified_name, [])
    caller_count = len(callers)
    has_unknown = any(c.confidence == "UNKNOWN" for c in callers) or any(
        c.confidence == "UNKNOWN" for c in symbol.calls
    )
    stale = compute_staleness(symbol, recent_changes, repo_root)

    # Determine badge label
    if has_unknown:
        label = "UNKNOWN"
    elif tests and caller_count > 0:
        label = "PROVEN"
    elif tests or caller_count > 0:
        label = "INFERRED"
    else:
        label = "UNKNOWN"

    return EvidenceBadge(
        label=label,
        test_count=len(tests),
        test_names=tests,
        caller_count=caller_count,
        has_unknown_edges=has_unknown,
        is_auth_related=symbol.is_auth_related,
        has_broad_except=symbol.has_broad_except,
        stale=stale,
    )
