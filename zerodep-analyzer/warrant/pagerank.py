"""
pagerank.py — Pure-stdlib PageRank over an arbitrary directed graph.

Domain-agnostic: works on web links OR function call graphs.
The caller passes dict[node, set[node]] (outbound edges).

Zero third-party dependencies.
"""
from __future__ import annotations


def pagerank(
    graph: dict[str, set[str]],
    damping: float = 0.85,
    max_iter: int = 100,
    tol: float = 1e-6,
) -> dict[str, float]:
    """
    Compute PageRank scores for all nodes.

    Args:
        graph:   {node: {outbound_nodes}}. All referenced nodes must be keys.
        damping: Probability of following a link (vs random jump). Default 0.85.
        max_iter: Maximum iteration count before giving up. Default 100.
        tol:     Convergence threshold (L1 norm of rank delta). Default 1e-6.

    Returns:
        {node: rank_score}  — scores sum to 1.0.
    """
    nodes = list(graph.keys())
    n = len(nodes)
    if n == 0:
        return {}

    # Uniform initialisation
    ranks: dict[str, float] = {node: 1.0 / n for node in nodes}

    for _ in range(max_iter):
        new_ranks: dict[str, float] = {}

        # Dangling nodes (no outbound links) contribute their rank uniformly
        dangling = sum(ranks[nd] for nd in nodes if not graph[nd])

        for node in nodes:
            # Teleportation + dangling sink redistribution
            r = (1.0 - damping) / n + damping * dangling / n
            # Contribution from all nodes that link to this one
            for src in nodes:
                out = graph[src]
                if node in out:
                    r += damping * ranks[src] / len(out)
            new_ranks[node] = r

        # Convergence check (L1 norm)
        delta = sum(abs(new_ranks[nd] - ranks[nd]) for nd in nodes)
        ranks = new_ranks
        if delta < tol:
            break

    return ranks


def normalise(scores: dict[str, float]) -> dict[str, float]:
    """Scale scores to [0, 1] range. Safe against empty / zero-max dicts."""
    if not scores:
        return {}
    max_score = max(scores.values())
    if max_score == 0:
        return {k: 0.0 for k in scores}
    return {k: v / max_score for k, v in scores.items()}
