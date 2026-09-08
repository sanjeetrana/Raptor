"""
cli.py - Warrant CLI entry point.

Commands:
    warrant index  <repo_path>          Build and save the index
    warrant search <query>              Search the index
    warrant search <query> --explain    Show score breakdown per result
    warrant search <query> --repo <p>   Index + search in one step (no persist)
    warrant impact <name>               Blast radius: who breaks if this changes?
    warrant audit                       Whole-repo trust map: untested load-bearing code
    warrant stats                       Show index statistics

Zero third-party dependencies.
"""
from __future__ import annotations

import argparse
import sys
import json
from pathlib import Path

from warrant_index import WarrantIndex
from compare import compare_indexes, print_compare_report
from ranking import SearchResult


# -- ANSI colour helpers -------------------------------------------------------

_ANSI = {
    "reset":  "\033[0m",
    "bold":   "\033[1m",
    "dim":    "\033[2m",
    "cyan":   "\033[36m",
    "green":  "\033[32m",
    "yellow": "\033[33m",
    "red":    "\033[31m",
    "white":  "\033[37m",
    "grey":   "\033[90m",
}

def _c(text: str, *codes: str) -> str:
    """Wrap text in ANSI codes (skip if stdout is not a TTY)."""
    if not sys.stdout.isatty():
        return text
    prefix = "".join(_ANSI[c] for c in codes if c in _ANSI)
    return f"{prefix}{text}{_ANSI['reset']}"


# -- Result renderer ------------------------------------------------------------

def render_result(r: SearchResult, verbose: bool = False) -> None:
    badge = r.evidence

    # Header line: rank, score, name, badge
    score_str = _c(f"[{r.score:.2f}]", "cyan")
    name_str  = _c(r.qualified_name, "bold", "white")
    badge_str = badge.display()
    print(f"  {r.rank}. {score_str} {name_str}  {badge_str}")

    # Signature
    print(f"     {_c(r.signature, 'dim')}")

    # Location
    print(f"     {_c(r.file_path, 'grey')}:{r.line}")

    # Evidence details
    for detail in badge.detail_lines():
        print(f"     {_c('-', 'grey')} {detail}")

    if verbose and r.docstring:
        # Show first 120 chars of docstring
        ds = r.docstring[:120].replace("\n", " ")
        if len(r.docstring) > 120:
            ds += "..."
        print(f"     {_c(ds, 'dim')}")

    print()


def render_explain(r: SearchResult, alpha: float, beta: float, gamma: float) -> None:
    """Show score breakdown for a single result."""
    from ranking import EVIDENCE_WEIGHTS, _ev_weight
    ev_raw = _ev_weight(r.evidence)

    badge = r.evidence
    score_str = _c(f"[{r.score:.2f}]", "cyan")
    name_str  = _c(r.qualified_name, "bold", "white")
    print(f"  {r.rank}. {score_str} {name_str}  {badge.display()}")

    bm25_contrib  = alpha * r.bm25_score
    pr_contrib    = beta  * r.centrality
    ev_contrib    = gamma * ev_raw

    print(f"     {_c('Score breakdown:', 'dim')}")
    print(f"     {_c('+-', 'dim')} Text match:   "
          f"{r.bm25_score:.3f} x {alpha:.2f} = {bm25_contrib:.3f}  "
          f"{_c('(name boosted 3x, BM25 relevance)', 'grey')}")
    print(f"     {_c('+-', 'dim')} Centrality:   "
          f"{r.centrality:.3f} x {beta:.2f} = {pr_contrib:.3f}  "
          f"{_c(f'({r.evidence.caller_count} callers, PageRank blast radius)', 'grey')}")
    print(f"     {_c('+-', 'dim')} Evidence:     "
          f"{ev_raw:.3f} x {gamma:.2f} = {ev_contrib:.3f}  "
          f"{_c(f'({r.evidence.label}: {r.evidence.test_count} tests, {r.evidence.caller_count} callers)', 'grey')}")
    if r.evidence.stale.is_stale:
        print(f"     {_c('  [STALE] staleness penalty applied: evidence halved', 'yellow')}")
    print(f"     {_c('= Total: ' + f'{r.score:.3f}', 'bold')}")
    print(f"     {_c(r.file_path, 'grey')}:{r.line}")
    print()


# -- Commands ------------------------------------------------------------------

def cmd_index(args) -> int:
    repo = Path(args.repo).resolve()
    if not repo.exists():
        print(f"error: repo path does not exist: {repo}", file=sys.stderr)
        return 1

    index_dir = Path(args.index_dir)
    print(_c(f"Warrant  indexing {repo}", "bold"))
    print("  [1/4] Extracting symbols from Python files...")
    print("  [2/4] Building BM25 full-text index...")
    print("  [3/4] Computing PageRank over call graph...")
    print("  [4/4] Computing evidence badges...")

    idx = WarrantIndex.build(repo_root=repo)
    idx.save(index_dir)
    stats = idx.stats()
    
    if getattr(args, "json", False):
        print(json.dumps(stats, indent=2))
        return 0

    if getattr(args, "json", False):
        print(json.dumps(stats, indent=2))
        return 0

    print()
    print(_c("  Index built successfully!", "green", "bold"))
    print(f"  Symbols indexed:  {stats['total_symbols']}")
    print(f"  Badge breakdown:  {stats['badge_counts']}")
    print(f"  Index saved to:   {index_dir}")
    return 0


def cmd_search(args) -> int:
    query = args.query

    # If --repo given, build on the fly (no persist)
    if args.repo:
        repo = Path(args.repo).resolve()
        if not repo.exists():
            print(f"error: repo path does not exist: {repo}", file=sys.stderr)
            return 1
        idx = WarrantIndex.build(repo_root=repo)
    else:
        index_dir = Path(args.index_dir)
        if not index_dir.exists():
            print(
                f"error: no index found at {index_dir}. Run: warrant index <repo>",
                file=sys.stderr,
            )
            return 1
        idx = WarrantIndex.load(index_dir)

    results = idx.search(query, top_k=args.top_k, include_tests=args.include_tests)

    if getattr(args, "json", False):
        import json, dataclasses
        def _asdict(o):
            if hasattr(o, "stale"):
                d = dataclasses.asdict(o)
                d["stale"] = dataclasses.asdict(o.stale)
                return d
            if dataclasses.is_dataclass(o):
                return dataclasses.asdict(o)
            return o
            
        out = []
        for r in results:
            d = dataclasses.asdict(r)
            if hasattr(r, 'badge') and r.badge:
                d['badge'] = _asdict(r.badge)
            out.append(d)
        print(json.dumps(out, indent=2))
        return 0


    print()
    print(_c("  WARRANT  Search Results", "bold", "cyan"))
    print(_c("  AI made code generation cheap. Warrant tells you what's safe to touch.", "dim"))
    print()
    print(_c(f"  Query: \"{query}\"", "bold"))
    print(_c("  " + "-" * 56, "dim"))
    print()

    if not results:
        print("  No results found. Try different keywords.")
        return 0

    from ranking import ALPHA, BETA, GAMMA
    for r in results:
        if getattr(args, "explain", False):
            render_explain(r, ALPHA, BETA, GAMMA)
        else:
            render_result(r, verbose=args.verbose)

    print(_c("  -" * 28, "dim"))
    print(_c("  Limits:", "dim"))
    print(_c("  - Static analysis only - runtime behavior not observed", "dim"))
    print(_c("  - Evidence badges are heuristic (name/import), not runtime coverage", "dim"))
    print(_c("  - Warrant never certifies 'safe to merge'", "dim"))
    print()

    # Exit code: 1 if any UNKNOWN or STALE results in top 3
    top3_labels = {r.evidence.label for r in results[:3]}
    if top3_labels & {"UNKNOWN", "STALE"}:
        return 1
    return 0


def cmd_impact(args) -> int:
    """warrant impact <name> -- show blast radius."""
    name = args.name
    if args.repo:
        repo = Path(args.repo).resolve()
        if not repo.exists():
            print(f"error: repo not found: {repo}", file=sys.stderr)
            return 1
        idx = WarrantIndex.build(repo_root=repo)
    else:
        index_dir = Path(args.index_dir)
        if not index_dir.exists():
            print(f"error: no index at {index_dir}. Run: warrant index <repo>", file=sys.stderr)
            return 1
        idx = WarrantIndex.load(index_dir)

    result = idx.impact(name)
    if "error" in result:
        print(f"  error: {result['error']}", file=sys.stderr)
        return 1

    print()
    print(_c("  WARRANT  Blast Radius Analysis", "bold", "cyan"))
    print(_c(f"  Symbol: {result['qname']}", "bold"))
    print()
    badge_str = _c(f"[{result['badge']}]", "green" if result["badge"] == "PROVEN" else "yellow")
    print(f"  Badge: {badge_str}  Centrality: {result['centrality']:.3f}")
    print()
    print(_c("  Direct impact:", "bold"))
    print(f"    {result['direct_callers']} function(s) call this directly")
    print()
    print(_c("  Transitive impact:", "bold"))
    print(f"    {result['transitive_broken']} function(s) would break transitively")
    print(f"    {result['transitive_reachable']} function(s) this reaches")
    if result["api_routes_affected"] > 0:
        print(f"    {_c(str(result['api_routes_affected']) + ' API route(s) affected', 'yellow')}")
    print()
    if result["tests_that_would_catch"] > 0:
        print(_c(f"  {result['tests_that_would_catch']} test(s) in blast radius will catch regressions", "green"))
    else:
        print(_c("  WARNING: No tests in blast radius -- changes here have no safety net", "yellow"))
    print(f"  Symbol has {result['test_count']} test(s) directly associated")
    print()
    if result["transitive_broken_list"]:
        print(_c("  Transitive callers:", "dim"))
        for qn in result["transitive_broken_list"][:15]:
            print(f"    {_c('-', 'grey')} {qn}")
        if len(result["transitive_broken_list"]) > 15:
            print(f"    {_c('... and ' + str(len(result['transitive_broken_list'])-15) + ' more', 'dim')}")
    print()
    return 0


def cmd_audit(args) -> int:
    """warrant audit -- whole-repo trust map."""
    if args.repo:
        repo = Path(args.repo).resolve()
        if not repo.exists():
            print(f"error: repo not found: {repo}", file=sys.stderr)
            return 1
        idx = WarrantIndex.build(repo_root=repo)
    else:
        index_dir = Path(args.index_dir)
        if not index_dir.exists():
            print(f"error: no index at {index_dir}. Run: warrant index <repo>", file=sys.stderr)
            return 1
        idx = WarrantIndex.load(index_dir)

    result = idx.audit()
    breakdown = result["badge_breakdown"]
    risky = result["risky_symbols"]
    total = result["total_symbols"]

    print()
    print(_c("  WARRANT  Repo Audit", "bold", "cyan"))
    print()
    print(f"  {total} symbols indexed")
    for label in ("PROVEN", "INFERRED", "UNKNOWN"):
        count = breakdown.get(label, 0)
        color = "green" if label == "PROVEN" else ("yellow" if label == "INFERRED" else "red")
        bar = "#" * count
        print(f"  {_c(label + ':', color):20s} {count:3d}  {_c(bar, color)}")
    print()

    if not risky:
        print(_c("  All load-bearing symbols have associated tests.", "green"))
        return 0

    print(_c(f"  WARNING: {len(risky)} load-bearing, untested function(s) -- start here:", "yellow"))
    print()
    for sym in risky[:10]:
        auth_warn = "  [!] auth-sensitive" if sym["is_auth"] else ""
        exc_warn = "  [!] broad except" if sym["has_broad_except"] else ""
        label_color = "yellow" if sym["badge"] == "INFERRED" else "grey"
        print(f"  {_c(sym['qname'], 'bold')}")
        print(f"    {sym['callers']} caller(s), 0 tests  "
              f"badge={_c(sym['badge'], label_color)}{_c(auth_warn, 'red')}{_c(exc_warn, 'yellow')}")
    if len(risky) > 10:
        print(f"  {_c('... and ' + str(len(risky)-10) + ' more', 'dim')}")
    print()
    print(_c("  Limits: association is name/import heuristic, not runtime coverage", "dim"))
    print()
    return 0


def cmd_stats(args) -> int:
    index_dir = Path(args.index_dir)
    if not index_dir.exists():
        print(f"error: no index at {index_dir}", file=sys.stderr)
        return 1
    idx = WarrantIndex.load(index_dir)
    stats = idx.stats()
    
    if getattr(args, "json", False):
        print(json.dumps(stats, indent=2))
        return 0
    print(_c("  WARRANT  Index Statistics", "bold", "cyan"))
    print(f"  Total symbols:  {stats['total_symbols']}")
    print(f"  Badge counts:")
    for label, count in sorted(stats['badge_counts'].items()):
        print(f"    {label}: {count}")
    return 0


# -- Main ----------------------------------------------------------------------


def cmd_compare(args) -> int:
    before_dir = Path(args.before)
    after_dir = Path(args.after)
    
    if not before_dir.exists():
        print(f"error: --before index does not exist at {before_dir}", file=sys.stderr)
        return 1
    if not after_dir.exists():
        print(f"error: --after index does not exist at {after_dir}", file=sys.stderr)
        return 1
        
    before_idx = WarrantIndex.load(before_dir)
    after_idx = WarrantIndex.load(after_dir)
    
    delta = compare_indexes(before_idx, after_idx)
    
    if getattr(args, "json", False):
        print(json.dumps(delta, indent=2))
        return 0
        
    print_compare_report(delta)
    
    return 0

def main() -> int:

    parser = argparse.ArgumentParser(
        prog="warrant",
        description="Code search with evidence badges. "
                    "Every result tells you WHERE it is, HOW central it is, "
                    "and WHETHER you actually have evidence it's safe.",
    )
    parser.add_argument(
        "--index-dir",
        default=".warrant_index",
        help="Directory where the index is stored (default: .warrant_index)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output in JSON format",
    )
    sub = parser.add_subparsers(dest="command")

    # warrant index
    p_index = sub.add_parser("index", help="Build the search index for a repo")
    p_index.add_argument("repo", help="Path to the Python repo root")

    # warrant search
    p_search = sub.add_parser("search", help="Search the index")
    p_search.add_argument("query", help="Search query (e.g. \"token validation\")")
    p_search.add_argument("--repo", default=None, help="Index this repo on-the-fly")
    p_search.add_argument("--top-k", type=int, default=10, help="Max results (default 10)")
    p_search.add_argument("--verbose", "-v", action="store_true",
                          help="Show docstring snippet for each result")
    p_search.add_argument("--explain", "-e", action="store_true",
                          help="Show score breakdown (BM25 / PageRank / Evidence) per result")
    p_search.add_argument("--include-tests", action="store_true",
                          help="Include test functions in search results")

    # warrant impact
    p_impact = sub.add_parser("impact", help="Blast radius: who breaks if this function changes?")
    p_impact.add_argument("name", help="Function name (short or qualified)")
    p_impact.add_argument("--repo", default=None, help="Repo to analyse on-the-fly")

    # warrant audit
    p_audit = sub.add_parser("audit", help="Whole-repo trust map: untested, load-bearing code")
    p_audit.add_argument("--repo", default=None, help="Repo to audit on-the-fly")


    # warrant stats
    sub.add_parser("stats", help="Show index statistics")

    # warrant compare
    p_compare = sub.add_parser("compare", help="Compare two indexes to track severity delta")
    p_compare.add_argument("--before", required=True, help="Path to the previous .warrant_index")
    p_compare.add_argument("--after", required=True, help="Path to the current .warrant_index")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    if args.command == "index":
        return cmd_index(args)
    elif args.command == "search":
        return cmd_search(args)
    elif args.command == "impact":
        return cmd_impact(args)
    elif args.command == "audit":
        return cmd_audit(args)

    elif args.command == "stats":
        return cmd_stats(args)
    elif args.command == "compare":
        return cmd_compare(args)
    return 0



if __name__ == "__main__":
    sys.exit(main())
