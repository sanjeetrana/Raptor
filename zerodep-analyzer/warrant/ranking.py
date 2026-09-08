"""
ranking.py — Warrant's scoring blend.

Combines three independent signals into one final score:
  1. BM25       — text relevance (does this symbol match the query?)
  2. PageRank   — structural centrality (is this symbol important in the codebase?)
  3. Evidence   — confidence quality (do we actually know it's safe/tested?)

Score formula (additive, not multiplicative — avoids zero-collapse on isolated symbols):
  score = ALPHA * bm25_norm + BETA * pagerank_norm + GAMMA * evidence_weight

Tuning constants validated against the synthetic test cases in tests/test_ranking.py.

Zero third-party dependencies.
"""
from __future__ import annotations

import dataclasses
from typing import Optional

from bm25 import BM25Index, Document
from pagerank import pagerank, normalise
from evidence import EvidenceBadge


# ── Weights (validated against test_ranking.py synthetic cases) ───────────────

ALPHA = 0.60   # text relevance - highest weight: query intent is primary
BETA  = 0.20   # structural centrality - secondary
GAMMA = 0.20   # evidence quality - tiebreaker


# ── Evidence quality weights ──────────────────────────────────────────────────

# Evidence quality weights for the scoring blend.
#
# STALE is NOT a separate label — it is an orthogonal flag on EvidenceBadge.stale.
# These weights reflect the *confidence* axis only (PROVEN/INFERRED/UNKNOWN).
# When stale.is_stale is True, the ranker applies an additional 0.5x penalty
# on top of the confidence weight (see _ev_weight below).
EVIDENCE_WEIGHTS: dict[str, float] = {
    "PROVEN":   1.00,
    "INFERRED": 0.65,
    "UNKNOWN":  0.30,
}


def _ev_weight(badge) -> float:
    """
    Evidence weight for the scoring blend.
    If the symbol is stale (orthogonal freshness axis), we halve the weight
    as a penalty — but we don't override the confidence label.
    """
    w = EVIDENCE_WEIGHTS.get(badge.label, 0.30)
    if badge.stale.is_stale:
        w *= 0.5   # staleness penalty applied on TOP of confidence weight
    return w


# ── Result ─────────────────────────────────────────────────────────────────────

@dataclasses.dataclass
class SearchResult:
    rank: int
    doc_id: str             # qualified name: "auth.validate_token"
    file_path: str
    line: int
    name: str
    qualified_name: str
    score: float            # final blended score [0, 1]
    bm25_score: float       # raw BM25 score (pre-normalisation)
    centrality: float       # normalised PageRank [0, 1]
    evidence: EvidenceBadge
    docstring: Optional[str]
    signature: str          # "def validate_token(token: str) -> None"


# ── Scorer ────────────────────────────────────────────────────────────────────

class Ranker:
    """
    Takes a pre-built BM25Index + PageRank scores + evidence badges,
    and produces ranked SearchResult lists.
    """

    def __init__(
        self,
        bm25: BM25Index,
        pagerank_scores: dict[str, float],      # normalised [0,1]
        badges: dict[str, EvidenceBadge],        # qname → badge
    ):
        self.bm25 = bm25
        self.pagerank_scores = pagerank_scores
        self.badges = badges

    def search(self, query: str, top_k: int = 10, include_tests: bool = False) -> list[SearchResult]:
        """Run a ranked search. Returns top_k results."""
        # BM25 results (doc_id, raw_score)
        raw = self.bm25.search(query, top_k=len(self.bm25))
        if not raw:
            return []

        # Normalise BM25 scores to [0, 1]
        raw_scores = [s for _, s in raw]
        max_bm25 = max(raw_scores) if raw_scores else 1.0
        min_bm25 = min(raw_scores) if raw_scores else 0.0

        blended: list[tuple[str, float, float, float]] = []
        for doc_id, bm25_raw in raw:
            if not include_tests:
                doc = self.bm25.get(doc_id)
                if doc and doc.metadata.get("is_test", False):
                    continue

            # Min-Max normalization preserves absolute quality gap (not max-norm which compresses it)
            if max_bm25 > min_bm25:
                bm25_norm = (bm25_raw - min_bm25) / (max_bm25 - min_bm25)
            else:
                bm25_norm = 1.0 if max_bm25 > 0 else 0.0

            # Heuristic: suppress dunders because PageRank over-credits __init__ etc.
            # This is a patch for structural noise, not a principled scoring decision.
            _name = doc_id.split(".")[-1]
            if _name.startswith("__") and _name.endswith("__"):
                bm25_norm *= 0.5

            pr_n = self.pagerank_scores.get(doc_id, 0.0)
            _b = self.badges.get(doc_id)
            ev_w = _ev_weight(_b) if _b else 0.30
            final = ALPHA * bm25_norm + BETA * pr_n + GAMMA * ev_w
            blended.append((doc_id, final, bm25_norm, pr_n))

        blended.sort(key=lambda x: x[1], reverse=True)

        results = []
        for rank, (doc_id, final, bm25_n, pr_n) in enumerate(blended[:top_k], 1):
            doc = self.bm25.get(doc_id)
            if not doc:
                continue
            meta = doc.metadata
            badge = self.badges.get(doc_id)
            if badge is None:
                from evidence import EvidenceBadge, StalenessInfo
                badge = EvidenceBadge(
                    label="UNKNOWN", test_count=0, test_names=[],
                    caller_count=0, has_unknown_edges=False,
                    is_auth_related=False, has_broad_except=False,
                    stale=StalenessInfo(False, ""),
                )

            args = meta.get("args", [])
            ret = meta.get("return_annotation", "")
            sig = f"def {meta.get('name', doc_id)}({', '.join(args)})"
            if ret:
                sig += f" -> {ret}"

            results.append(SearchResult(
                rank=rank,
                doc_id=doc_id,
                file_path=meta.get("file_path", ""),
                line=meta.get("line", 0),
                name=meta.get("name", doc_id),
                qualified_name=doc_id,
                score=round(final, 4),
                bm25_score=round(bm25_n, 4),
                centrality=round(pr_n, 4),
                evidence=badge,
                docstring=meta.get("docstring"),
                signature=sig,
            ))
        return results
