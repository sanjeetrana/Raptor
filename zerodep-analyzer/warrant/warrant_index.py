"""
warrant_index.py — The glue layer that ties BM25 + PageRank + Evidence together.

Usage:
    idx = WarrantIndex.build(repo_root=Path("."))
    idx.save(Path(".warrant_index"))
    idx2 = WarrantIndex.load(Path(".warrant_index"))
    results = idx2.search("token validation")

Zero third-party dependencies.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from bm25 import BM25Index, Document
from pagerank import pagerank, normalise
from symbol_extractor import extract_repo, SymbolInfo
from call_graph import build_call_graph, CallGraphResult
from evidence import compute_badge, EvidenceBadge, StalenessInfo
from ranking import Ranker, SearchResult
from git_utils import get_recently_modified_files


class WarrantIndex:
    """
    Persistent, searchable index of a Python codebase.

    Internal state:
        - bm25:         BM25Index of all symbols
        - cg:           CallGraphResult (inbound/outbound edges)
        - pr_scores:    normalised PageRank over call graph
        - badges:       EvidenceBadge per symbol
        - ranker:       Ranker that blends the three signals
    """

    def __init__(
        self,
        bm25: BM25Index,
        cg: CallGraphResult,
        pr_scores: dict[str, float],
        badges: dict[str, EvidenceBadge],
    ):
        self.bm25 = bm25
        self.cg = cg
        self.pr_scores = pr_scores
        self.badges = badges
        self.ranker = Ranker(bm25, pr_scores, badges)

    # ── Build ────────────────────────────────────────────────────────────────

    @classmethod
    def build(
        cls,
        repo_root: Path,
        recent_changes: Optional[set[str]] = None,
    ) -> "WarrantIndex":
        """
        Extract all symbols, build BM25 index, call graph, PageRank, and evidence badges.

        Args:
            repo_root:      Root directory of the Python repo to index.
            recent_changes: Set of recently-modified file paths (for staleness detection).
                            If None, auto-detects using Git (files changed in last 7 days).
                            Pass empty set to disable staleness.
        """
        if recent_changes is None:
            recent_changes = get_recently_modified_files(repo_root)

        # 1. Extract all symbols from the repo
        symbols = extract_repo(repo_root)

        # 2. Build BM25 index
        bm25 = BM25Index()
        for sym in symbols:
            doc = Document(
                doc_id=sym.qualified_name,
                body=sym.index_body(),
                metadata={
                    "name": sym.name,
                    "qualified_name": sym.qualified_name,
                    "file_path": sym.file_path,
                    "line": sym.line,
                    "args": sym.args,
                    "return_annotation": sym.return_annotation,
                    "docstring": sym.docstring,
                    "is_test": sym.is_test,
                    "is_public": sym.is_public,
                },
            )
            bm25.add_document(doc)
        bm25.build()

        # 3. Build call graph
        cg = build_call_graph(symbols)

        # 4. PageRank over call graph
        # Convert outbound edges: set → list for pagerank()
        graph_for_pr: dict[str, set[str]] = {
            qn: set(targets)
            for qn, targets in cg.outbound.items()
        }
        raw_pr = pagerank(graph_for_pr)
        pr_scores = normalise(raw_pr)

        # 5. Evidence badges
        badges: dict[str, EvidenceBadge] = {}
        for sym in symbols:
            badges[sym.qualified_name] = compute_badge(
                sym, symbols, cg, recent_changes, repo_root=repo_root
            )

        return cls(bm25, cg, pr_scores, badges)

    # ── Search ────────────────────────────────────────────────────────────────

    def search(self, query: str, top_k: int = 10, include_tests: bool = False) -> list[SearchResult]:
        return self.ranker.search(query, top_k=top_k, include_tests=include_tests)

        # ── Impact ────────────────────────────────────────────────────────────────

    def impact(self, name: str) -> dict:
        """
        Compute blast radius of a symbol: direct and transitive callers.
        Also returns how many API routes and tests are reachable.
        """
        qname = self._resolve_name(name)
        if not qname:
            return {"error": f"Symbol not found: {name!r}"}

        badge = self.badges.get(qname)
        pr_score = self.pr_scores.get(qname, 0.0)

        # Real BFS on outbound — who does this function reach?
        reachable: set[str] = set()
        queue = [qname]
        while queue:
            node = queue.pop()
            for target in self.cg.outbound.get(node, set()):
                if target not in reachable:
                    reachable.add(target)
                    queue.append(target)

        # Who calls this function directly
        direct_count = self.cg.caller_counts.get(qname, 0)

        # Transitive "who would break" — BFS inward using inbound edges
        inbound_map: dict[str, list[str]] = {}
        for caller, callees in self.cg.outbound.items():
            for callee in callees:
                inbound_map.setdefault(callee, []).append(caller)

        broken: set[str] = set()
        queue2 = [qname]
        while queue2:
            node = queue2.pop()
            for caller in inbound_map.get(node, []):
                if caller not in broken:
                    broken.add(caller)
                    queue2.append(caller)

        test_count = sum(1 for s in broken if "test_" in s.split(".")[-1])
        route_count = sum(1 for s in broken
                         if any(kw in s for kw in ("route", "handler", "view", "endpoint", "api")))

        return {
            "qname": qname,
            "direct_callers": direct_count,
            "transitive_broken": len(broken),
            "transitive_broken_list": sorted(broken),
            "transitive_reachable": len(reachable),
            "tests_that_would_catch": test_count,
            "api_routes_affected": route_count,
            "badge": badge.label if badge else "UNKNOWN",
            "test_count": badge.test_count if badge else 0,
            "centrality": pr_score,
        }

    def _resolve_name(self, name: str) -> str:
        if name in self.badges:
            return name
        for qn in self.badges:
            if qn.split(".")[-1] == name:
                return qn
        for qn in self.badges:
            if name in qn:
                return qn
        return ""

    # ── Audit ─────────────────────────────────────────────────────────────────

    def audit(self) -> dict:
        """
        Whole-repo trust map.
        Returns symbols grouped by risk: load-bearing (callers > 0) but untested (tests == 0).
        """
        risky = []
        for qname, badge in self.badges.items():
            # Skip test functions
            doc = self.bm25.get(qname)
            is_test_sym = doc.metadata.get("is_test", False) if doc else False
            if is_test_sym:
                continue
            if badge.caller_count > 0 and badge.test_count == 0:
                risky.append({
                    "qname": qname,
                    "callers": badge.caller_count,
                    "tests": badge.test_count,
                    "badge": badge.label,
                    "centrality": self.pr_scores.get(qname, 0.0),
                    "is_auth": badge.is_auth_related,
                    "has_broad_except": badge.has_broad_except,
                })
        risky.sort(key=lambda x: (x["callers"], x["centrality"]), reverse=True)

        all_badges = list(self.badges.values())
        breakdown: dict[str, int] = {}
        for b in all_badges:
            breakdown[b.label] = breakdown.get(b.label, 0) + 1

        return {
            "total_symbols": len(self.badges),
            "badge_breakdown": breakdown,
            "risky_symbols": risky,
        }

    # ── Stats ─────────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        total = len(self.bm25)
        label_counts: dict[str, int] = {}
        for badge in self.badges.values():
            label_counts[badge.label] = label_counts.get(badge.label, 0) + 1
        return {
            "total_symbols": total,
            "badge_counts": label_counts,
        }

    # ── Persistence ────────────────────────────────────────────────────────────

    def save(self, index_dir: Path) -> None:
        """Save the index to a directory."""
        index_dir.mkdir(parents=True, exist_ok=True)
        # BM25
        self.bm25.save(index_dir / "bm25.json")
        # PageRank scores
        (index_dir / "pagerank.json").write_text(
            json.dumps(self.pr_scores, indent=2), encoding="utf-8"
        )
        # Badges
        badges_data = {
            qn: {
                "label": b.label,
                "test_count": b.test_count,
                "test_names": b.test_names,
                "caller_count": b.caller_count,
                "has_unknown_edges": b.has_unknown_edges,
                "is_auth_related": b.is_auth_related,
                "has_broad_except": b.has_broad_except,
                "stale": {"is_stale": b.stale.is_stale, "reason": b.stale.reason},
            }
            for qn, b in self.badges.items()
        }
        (index_dir / "badges.json").write_text(
            json.dumps(badges_data, indent=2), encoding="utf-8"
        )
        # Call graph - full outbound edges for impact analysis + counts
        cg_data = {
            "caller_counts": self.cg.caller_counts,
            "outbound": {qn: sorted(targets) for qn, targets in self.cg.outbound.items()},
        }
        (index_dir / "call_graph.json").write_text(
            json.dumps(cg_data, indent=2), encoding="utf-8"
        )

    @classmethod
    def load(cls, index_dir: Path) -> "WarrantIndex":
        """Load a previously saved index."""
        bm25 = BM25Index.load(index_dir / "bm25.json")
        pr_scores = json.loads((index_dir / "pagerank.json").read_text(encoding="utf-8"))
        raw_badges = json.loads((index_dir / "badges.json").read_text(encoding="utf-8"))
        badges: dict[str, EvidenceBadge] = {}
        for qn, bd in raw_badges.items():
            badges[qn] = EvidenceBadge(
                label=bd["label"],
                test_count=bd["test_count"],
                test_names=bd["test_names"],
                caller_count=bd["caller_count"],
                has_unknown_edges=bd["has_unknown_edges"],
                is_auth_related=bd["is_auth_related"],
                has_broad_except=bd["has_broad_except"],
                stale=StalenessInfo(
                    is_stale=bd["stale"]["is_stale"],
                    reason=bd["stale"]["reason"],
                ),
            )
        cg_data = json.loads((index_dir / "call_graph.json").read_text(encoding="utf-8"))
        from call_graph import CallGraphResult
        # Restore outbound edges (saved as sorted lists, convert back to sets)
        saved_outbound = cg_data.get("outbound", {})
        cg = CallGraphResult(
            outbound={qn: set(targets) for qn, targets in saved_outbound.items()},
            inbound={qn: [] for qn in cg_data["caller_counts"]},
            caller_counts=cg_data["caller_counts"],
        )
        return cls(bm25, cg, pr_scores, badges)
