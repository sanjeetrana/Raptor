"""
cli.py — Command Line Interface for Proofline.

Supports:
  - analyze: Compare before/after directories
  - scan: Compare git refs in a repository
  - install-hook: Install git pre-commit hook
  - stdlib-notes: Print STDLIB.md notes

Zero third-party dependencies. Python stdlib only.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .diff_engine import compare_directories
from .caller_graph import build_call_graph
from .route_detector import detect_affected_routes
from .test_associator import associate_tests, check_test_resilience
from .rules_engine import run_rules_engine, Severity
from .evidence_graph import build_evidence_graph
from .report import render_cli_report, render_html_report, render_json_report, serve_report, render_sarif_report, render_summary_report, render_graph_report, render_diff_report

DESCRIPTION = """\
Proofline — Change-centered Python code verification.
AI made code generation cheap. Verification didn't keep up.

Zero third-party dependencies. Python stdlib only.
"""

EPILOG = """\
Examples:
  # Analyze a directory pair
  python -m proofline analyze --before ./baseline --after ./patch

  # Scan a git repository against a commit/ref
  python -m proofline scan --base HEAD~1

  # Install git pre-commit hook to block unsafe commits
  python -m proofline install-hook --fail-on HIGH

  # Save HTML report
  python -m proofline scan --base origin/main --html report.html
"""

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="proofline",
        description=DESCRIPTION,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    # --- analyze ---
    analyze = subparsers.add_parser(
        "analyze",
        help="Analyze a before/after directory pair",
        description="Compare two directory trees and produce a verification report.",
    )
    analyze.add_argument(
        "--before",
        metavar="DIR",
        help="Path to the baseline directory (before the change)",
    )
    analyze.add_argument(
        "--after",
        metavar="DIR",
        help="Path to the patched directory (after the change)",
    )
    analyze.add_argument(
        "--staged",
        action="store_true",
        help="Compare HEAD to the git staging area (requires git repo)",
    )
    analyze.add_argument(
        "--commit",
        metavar="REF",
        help="Compare a specific commit to its parent (requires git repo)",
    )
    analyze.add_argument(
        "--html",
        metavar="FILE",
        default=None,
        help="Write a self-contained HTML report to FILE",
    )
    analyze.add_argument(
        "--serve",
        action="store_true",
        default=False,
        help="Serve the HTML report on localhost:8080",
    )
    import os
    analyze.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PROOF_PORT", 8080)),
        metavar="PORT",
        help="Port for --serve (default: 8080, overrides: PROOF_PORT env var)",
    )
    analyze.add_argument(
        "--log-file",
        metavar="FILE",
        default=None,
        help="Write plain text (ANSI-stripped) CLI output to FILE",
    )
    analyze.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Print JSON report to stdout (instead of CLI report)",
    )
    analyze.add_argument(
        "--output",
        metavar="FILE",
        default=None,
        help="Write JSON report to FILE",
    )
    analyze.add_argument(
        "--sarif",
        metavar="FILE",
        default=None,
        help="Write a SARIF report to FILE for GitHub Code Scanning integration",
    )
    analyze.add_argument(
        "--fail-on",
        choices=["HIGH", "MEDIUM", "LOW"],
        default="HIGH",
        help="Exit with code 1 if overall severity is >= this level",
    )
    analyze.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="Show detailed caller list",
    )
    analyze.add_argument(
        "--no-color",
        action="store_true",
        default=False,
        help="Disable ANSI color codes (for piped output)",
    )
    analyze.add_argument(
        "--summary",
        action="store_true",
        default=False,
        help="Print a one-line summary (for CI log output)",
    )
    analyze.add_argument(
        "--graph",
        action="store_true",
        default=False,
        help="Show text-based impact graph with box-drawing characters",
    )
    analyze.add_argument(
        "--diff",
        action="store_true",
        default=False,
        help="Show annotated unified diff",
    )
    analyze.add_argument(
        "--watch",
        action="store_true",
        default=False,
        help="Watch for file changes and auto re-run",
    )

    # --- scan ---
    scan = subparsers.add_parser(
        "scan",
        help="Analyze changes in a git repository",
        description="Compare two git commits/refs and produce a verification report.",
    )
    scan.add_argument(
        "--repo",
        default=".",
        metavar="DIR",
        help="Path to the git repository (default: current directory)",
    )
    scan.add_argument(
        "--base",
        required=True,
        metavar="REF",
        help="Base git ref/commit to compare against (e.g. HEAD~1 or origin/main)",
    )
    scan.add_argument(
        "--head",
        default="HEAD",
        metavar="REF",
        help="Head git ref/commit (default: HEAD)",
    )
    scan.add_argument(
        "--html",
        metavar="FILE",
        default=None,
        help="Write a self-contained HTML report to FILE",
    )
    scan.add_argument(
        "--serve",
        action="store_true",
        default=False,
        help="Serve the HTML report on localhost:8080",
    )
    scan.add_argument(
        "--port",
        type=int,
        default=8080,
        metavar="PORT",
        help="Port for --serve (default: 8080)",
    )
    scan.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Print JSON report to stdout (instead of CLI report)",
    )
    scan.add_argument(
        "--output",
        metavar="FILE",
        default=None,
        help="Write JSON report to FILE",
    )
    scan.add_argument(
        "--sarif",
        metavar="FILE",
        default=None,
        help="Write a SARIF report to FILE for GitHub Code Scanning integration",
    )
    scan.add_argument(
        "--github-comment",
        action="store_true",
        default=False,
        help="Automatically post verification report as a comment on GitHub PR",
    )
    scan.add_argument(
        "--github-repo",
        metavar="OWNER/REPO",
        default=None,
        help="GitHub repository slug e.g. 'owner/repo' (required for --github-comment)",
    )
    scan.add_argument(
        "--github-pr",
        type=int,
        metavar="NUMBER",
        default=None,
        help="GitHub Pull Request number (required for --github-comment)",
    )
    scan.add_argument(
        "--github-token",
        metavar="TOKEN",
        default=None,
        help="GitHub Personal Access Token (defaults to GITHUB_TOKEN env var)",
    )
    scan.add_argument(
        "--fail-on",
        choices=["HIGH", "MEDIUM", "LOW"],
        default="HIGH",
        help="Exit with code 1 if overall severity is >= this level",
    )
    scan.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="Show detailed caller list",
    )
    scan.add_argument(
        "--no-color",
        action="store_true",
        default=False,
        help="Disable ANSI color codes (for piped output)",
    )

    # --- install-hook ---
    hook = subparsers.add_parser(
        "install-hook",
        help="Install a git pre-commit hook",
        description="Install a Proofline pre-commit hook in the repository.",
    )
    hook.add_argument(
        "--repo",
        default=".",
        metavar="DIR",
        help="Path to the git repository (default: current directory)",
    )
    hook.add_argument(
        "--fail-on",
        choices=["HIGH", "MEDIUM", "LOW"],
        default="HIGH",
        help="Severity threshold to block commits (default: HIGH)",
    )

    # --- scaffold-tests ---
    scaffold = subparsers.add_parser(
        "scaffold-tests",
        help="Generate boilerplate unittest files for changed functions",
    )
    scaffold.add_argument(
        "--before",
        required=True,
        metavar="DIR",
        help="Path to the baseline directory",
    )
    scaffold.add_argument(
        "--after",
        required=True,
        metavar="DIR",
        help="Path to the patched directory",
    )

    # --- install-gha ---
    gha = subparsers.add_parser(
        "install-gha",
        help="Generate a GitHub Actions workflow for Proofline CI",
        description="Generate a .github/workflows/proofline.yml for automated PR verification.",
    )
    gha.add_argument(
        "--repo",
        default=".",
        metavar="DIR",
        help="Path to the git repository (default: current directory)",
    )
    gha.add_argument(
        "--fail-on",
        choices=["HIGH", "MEDIUM", "LOW"],
        default="HIGH",
        help="Severity threshold for CI failure (default: HIGH)",
    )

    # --- stdlib-notes ---
    subparsers.add_parser(
        "stdlib-notes",
        help="Print STDLIB.md content (stdlib-for-package substitutions)",
    )

    # --- init ---
    subparsers.add_parser(
        "init",
        help="Run the interactive Proofline setup wizard",
        description="Generate .env and .prooflineignore files interactively.",
    )

    # --- serve ---
    serve = subparsers.add_parser(
        "serve",
        help="Start the Proofline zero-dependency REST API & dashboard server",
        description="Run a local HTTP server for programmatic static verification API and visual dashboard.",
    )
    serve.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port to bind server to (default: 8080)",
    )
    serve.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host address to bind server to (default: 127.0.0.1)",
    )
    serve.add_argument(
        "--no-browser",
        action="store_true",
        default=False,
        help="Do not automatically open browser on startup",
    )

    # --- archive ---
    archive = subparsers.add_parser(
        "archive",
        help="Generate reports and securely zip them for compliance audit",
    )
    archive.add_argument(
        "--before",
        required=True,
        metavar="DIR",
    )
    archive.add_argument(
        "--after",
        required=True,
        metavar="DIR",
    )
    archive.add_argument(
        "--out",
        default=None,
        metavar="FILE",
        help="Output .zip filename",
    )

    return parser


def _get_dir_hash(d: str) -> str:
    import hashlib
    h = hashlib.sha256()
    for p in sorted(Path(d).rglob('*')):
        if p.is_file() and p.name.endswith('.py'):
            h.update(str(p.relative_to(d)).encode())
            h.update(str(p.stat().st_mtime).encode())
    return h.hexdigest()


def _handle_exit(args, eg, rules_report) -> int:
    from .rules_engine import SEVERITY_ORDER
    import sys
    
    if getattr(args, 'interactive', False):
        high_med = [s for s in eg.change_summaries if s.severity in ("HIGH", "MEDIUM")]
        if not high_med:
            return 0
            
        print(f"\n\033[93m[Interactive Triage] Found {len(high_med)} issues requiring review.\033[0m")
        for summary in high_med:
            print(f"\n\033[96mSymbol:\033[0m {summary.symbol_name} ({summary.file})")
            print(f"\033[95mSeverity:\033[0m {summary.severity}")
            
            while True:
                sys.stdout.write("Action [A]pprove, [R]eject, [S]kip: ")
                sys.stdout.flush()
                try:
                    choice = input().strip().upper()
                except (EOFError, KeyboardInterrupt):
                    return 1
                if choice == 'A':
                    print("\033[92mApproved.\033[0m")
                    break
                elif choice == 'R':
                    print("\033[91mRejected. Blocking commit.\033[0m")
                    return 1
                elif choice == 'S':
                    print("\033[93mSkipped.\033[0m")
                    break
        return 0

    try:
        from .git_utils import get_commit_info
        from .history import save_analysis
        commit_info = get_commit_info(str(Path(".").resolve()), "HEAD")
        if commit_info:
            save_analysis(str(Path(".").resolve()), commit_info, rules_report, eg)
    except Exception as e:
        pass

    fail_threshold = rules_report.overall_severity.__class__[args.fail_on]
    try:
        if SEVERITY_ORDER.index(rules_report.overall_severity) <= SEVERITY_ORDER.index(fail_threshold):
            return 1
    except ValueError:
        pass
    return 0

def _run_analyze_watch(args: argparse.Namespace) -> int:
    """Run analyze in watch mode."""
    import time
    before_dir = str(Path(args.before).resolve())
    after_dir = str(Path(args.after).resolve())
    
    last_hash = ""
    try:
        while True:
            current_hash = _get_dir_hash(after_dir)
            if current_hash != last_hash:
                print("\033[H\033[J", end="") # Clear terminal
                _run_analyze_single(args)
                last_hash = current_hash
                print("\n  \033[2mWatching for changes in --after dir... (Ctrl+C to stop)\033[0m")
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n  \033[2mWatch stopped.\033[0m")
        return 0

def _run_analyze(args: argparse.Namespace) -> int:
    if getattr(args, 'staged', False):
        args.repo = "."
        args.base = "HEAD"
        args.head = "" # use index
        args.staged_mode = True
        return _run_scan(args)
    elif getattr(args, 'commit', None):
        args.repo = "."
        args.base = f"{args.commit}~1"
        args.head = args.commit
        args.staged_mode = False
        return _run_scan(args)

    if not args.before or not args.after:
        print("Error: You must provide either --before and --after, or --staged, or --commit.", file=sys.stderr)
        return 2

    if getattr(args, 'watch', False):
        return _run_analyze_watch(args)
    return _run_analyze_single(args)

def _run_analyze_single(args: argparse.Namespace) -> int:

    """Run the full analysis pipeline and render output."""
    before_dir = str(Path(args.before).resolve())
    after_dir = str(Path(args.after).resolve())

    if not Path(before_dir).is_dir():
        print(f"Error: --before directory does not exist: {before_dir}", file=sys.stderr)
        return 2
    if not Path(after_dir).is_dir():
        print(f"Error: --after directory does not exist: {after_dir}", file=sys.stderr)
        return 2

    print(f"\033[96m  Proofline\033[0m  analyzing changes...", file=sys.stderr)
    print(f"\033[2m  Before: {before_dir}\033[0m", file=sys.stderr)
    print(f"\033[2m  After:  {after_dir}\033[0m\n", file=sys.stderr)

    diff_result = compare_directories(before_dir, after_dir)

    if not diff_result.symbol_diffs and not diff_result.file_changes:
        print("  No changes detected between the two directories.")
        return 0

    call_graph, caller_results = build_call_graph(diff_result)
    affected_routes = detect_affected_routes(diff_result)
    test_associations = associate_tests(diff_result)
    test_warnings = check_test_resilience(diff_result)

    rules_report = run_rules_engine(
        diff_result, caller_results, affected_routes,
        test_associations, test_warnings,
        repo_root=str(Path(".").resolve()),
    )

    eg = build_evidence_graph(
        diff_result, call_graph, caller_results,
        affected_routes, test_associations, test_warnings,
        rules_report,
    )

    no_color = args.no_color or not sys.stdout.isatty()
    
    if args.json:
        print(render_json_report(eg))
    elif getattr(args, 'summary', False):
        print(render_summary_report(eg))
    elif getattr(args, 'graph', False):
        print(render_graph_report(eg, no_color=no_color))
    elif getattr(args, 'diff', False):
        print(render_diff_report(eg, diff_result, no_color=no_color))
    else:
        cli_output = render_cli_report(eg, no_color=no_color, verbose=args.verbose)
        print(cli_output)

    if args.html:
        html_path = Path(args.html)
        html_path.write_text(render_html_report(eg), encoding="utf-8")
        print(f"\033[92m  HTML report written to: {html_path.resolve()}\033[0m")

    if args.output:
        output_path = Path(args.output)
        output_path.write_text(render_json_report(eg), encoding="utf-8")
        print(f"\033[92m  JSON report written to: {output_path.resolve()}\033[0m")

    if args.sarif:
        sarif_path = Path(args.sarif)
        sarif_path.write_text(render_sarif_report(eg), encoding="utf-8")
        print(f"\033[92m  SARIF report written to: {sarif_path.resolve()}\033[0m")

    if args.serve:
        serve_report(eg, port=args.port, open_browser=True)

    try:
        from .git_utils import get_commit_info
        from .history import save_analysis
        commit_info = get_commit_info(str(Path(".").resolve()), "HEAD")
        if commit_info:
            save_analysis(str(Path(".").resolve()), commit_info, rules_report, eg)
    except Exception as e:
        pass

    fail_threshold = rules_report.overall_severity.__class__[args.fail_on]
    from .rules_engine import SEVERITY_ORDER
    try:
        if SEVERITY_ORDER.index(rules_report.overall_severity) <= SEVERITY_ORDER.index(fail_threshold):
            return 1
    except ValueError:
        pass
    return 0

def _run_scan(args: argparse.Namespace) -> int:
    """Run the analysis pipeline on git changes between base and head refs."""
    from .git_utils import (
        find_repo_root,
        changed_python_files,
        export_tree_to_tempdir,
        cleanup_tempdir,
        get_commit_info,
        GitError,
    )

    try:
        repo_root = find_repo_root(args.repo)
    except GitError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    print(f"\033[96m  Proofline\033[0m  analyzing git changes in repo: {repo_root}", file=sys.stderr)
    try:
        staged = getattr(args, 'staged_mode', False)
        changed_files = changed_python_files(repo_root, args.base, args.head, staged=staged)
    except GitError as e:
        print(f"Error resolving refs/diff: {e}", file=sys.stderr)
        return 2

    if not changed_files:
        print(f"No Python file changes detected between {args.base} and {args.head}.")
        return 0

    print(f"\033[2m  Comparing refs: {args.base} -> {args.head}\033[0m", file=sys.stderr)
    print(f"\033[2m  Changed files ({len(changed_files)}): {', '.join(changed_files)}\033[0m\n", file=sys.stderr)

    before_dir = None
    after_dir = None
    try:
        before_dir = export_tree_to_tempdir(repo_root, args.base, changed_files)
        after_dir = export_tree_to_tempdir(repo_root, args.head, changed_files)

        diff_result = compare_directories(before_dir, after_dir)
        call_graph, caller_results = build_call_graph(diff_result)
        affected_routes = detect_affected_routes(diff_result)
        test_associations = associate_tests(diff_result)
        test_warnings = check_test_resilience(diff_result)

        rules_report = run_rules_engine(
            diff_result, caller_results, affected_routes,
            test_associations, test_warnings,
        )

        eg = build_evidence_graph(
            diff_result, call_graph, caller_results,
            affected_routes, test_associations, test_warnings,
            rules_report,
        )

        no_color = args.no_color or not sys.stdout.isatty()
        if args.json:
            print(render_json_report(eg))
        elif getattr(args, 'summary', False):
            print(render_summary_report(eg))
        elif getattr(args, 'graph', False):
            print(render_graph_report(eg, no_color=no_color))
        elif getattr(args, 'diff', False):
            print(render_diff_report(eg, diff_result, no_color=no_color))
        else:
            cli_output = render_cli_report(eg, no_color=no_color, verbose=args.verbose)
            print(cli_output)
            if getattr(args, 'log_file', None):
                from .ansi_stripper import strip_ansi_codes
                stripped = strip_ansi_codes(cli_output)
                Path(args.log_file).write_text(stripped, encoding="utf-8")
                print(f"\033[92m  Clean log written to: {args.log_file}\033[0m")

        if args.html:
            html_path = Path(args.html)
            html_path.write_text(render_html_report(eg), encoding="utf-8")
            print(f"\033[92m  HTML report written to: {html_path.resolve()}\033[0m")

        if args.output:
            output_path = Path(args.output)
            output_path.write_text(render_json_report(eg), encoding="utf-8")
            print(f"\033[92m  JSON report written to: {output_path.resolve()}\033[0m")

        if args.sarif:
            sarif_path = Path(args.sarif)
            sarif_path.write_text(render_sarif_report(eg), encoding="utf-8")
            print(f"\033[92m  SARIF report written to: {sarif_path.resolve()}\033[0m")

        if args.serve:
            serve_report(eg, port=args.port, open_browser=True)

        if getattr(args, "github_comment", False):
            if not args.github_repo or not args.github_pr:
                print("\033[91m  Error: --github-repo and --github-pr are required when --github-comment is set.\033[0m")
            else:
                from .github_integration import post_github_pr_comment
                ok, msg = post_github_pr_comment(
                    repo=args.github_repo,
                    pr_number=args.github_pr,
                    eg=eg,
                    token=getattr(args, "github_token", None),
                )
                if ok:
                    print(f"\033[92m  [GitHub PR] {msg}\033[0m")
                else:
                    print(f"\033[93m  [GitHub PR Warning] {msg}\033[0m")
        return _handle_exit(args, eg, rules_report)

    finally:
        if before_dir:
            cleanup_tempdir(before_dir)
        if after_dir:
            cleanup_tempdir(after_dir)

def _run_install_hook(args: argparse.Namespace) -> int:
    """Install the git pre-commit hook."""
    from .git_utils import find_repo_root, install_pre_commit_hook, GitError
    try:
        repo_root = find_repo_root(args.repo)
        hook_path = install_pre_commit_hook(repo_root, args.fail_on)
        print(f"\033[92m  Successfully installed pre-commit hook to: {hook_path}\033[0m")
        return 0
    except GitError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2


def _run_pack_context(args) -> int:
    from .packer import generate_llm_context
    from .diff_engine import compare_directories
    from .caller_graph import build_call_graph
    from .route_detector import detect_affected_routes
    from .test_associator import associate_tests, check_test_resilience
    from .rules_engine import run_rules_engine
    from .evidence_graph import build_evidence_graph
    import sys
    
    print(f"\033[96m  Proofline  packing LLM context...\033[0m", file=sys.stderr)
    
    before_dir = str(Path(args.before).resolve())
    after_dir = str(Path(args.after).resolve())

    if not Path(before_dir).is_dir():
        print(f"Error: --before directory does not exist: {before_dir}", file=sys.stderr)
        return 2
    if not Path(after_dir).is_dir():
        print(f"Error: --after directory does not exist: {after_dir}", file=sys.stderr)
        return 2
        
    diff_result = compare_directories(before_dir, after_dir)
    call_graph, caller_results = build_call_graph(diff_result)
    affected_routes = detect_affected_routes(diff_result)
    test_associations = associate_tests(diff_result)
    test_warnings = check_test_resilience(diff_result)

    rules_report = run_rules_engine(
        diff_result, caller_results, affected_routes,
        test_associations, test_warnings,
        repo_root=str(Path(".").resolve()),
    )

    eg = build_evidence_graph(
        diff_result, call_graph, caller_results,
        affected_routes, test_associations, test_warnings,
        rules_report,
    )
    
    generate_llm_context(eg, after_dir, args.out)
    print(f"\033[92m  Successfully packed LLM context into: {args.out}\033[0m", file=sys.stderr)
    return 0

def _run_scaffold(args) -> int:
    from .scaffolder import generate_test_scaffold
    from .diff_engine import compare_directories
    from .caller_graph import build_call_graph
    from .route_detector import detect_affected_routes
    from .test_associator import associate_tests, check_test_resilience
    from .rules_engine import run_rules_engine
    from .evidence_graph import build_evidence_graph
    import sys
    print(f"\033[96m  Proofline[0m  scaffolding tests...", file=sys.stderr)
    
    before_dir = str(Path(args.before).resolve())
    after_dir = str(Path(args.after).resolve())

    if not Path(before_dir).is_dir():
        print(f"Error: --before directory does not exist: {before_dir}", file=sys.stderr)
        return 2
    if not Path(after_dir).is_dir():
        print(f"Error: --after directory does not exist: {after_dir}", file=sys.stderr)
        return 2
        
    diff_result = compare_directories(before_dir, after_dir)
    call_graph, caller_results = build_call_graph(diff_result)
    affected_routes = detect_affected_routes(diff_result)
    test_associations = associate_tests(diff_result)
    test_warnings = check_test_resilience(diff_result)

    rules_report = run_rules_engine(
        diff_result, caller_results, affected_routes,
        test_associations, test_warnings,
        repo_root=str(Path(".").resolve()),
    )

    eg = build_evidence_graph(
        diff_result, call_graph, caller_results,
        affected_routes, test_associations, test_warnings,
        rules_report,
    )
    
    scaffolded_files = generate_test_scaffold(eg, after_dir)
    if not scaffolded_files:
        print("  No tests needed scaffolding.")
    else:
        print(f"\033[92m  Scaffolded tests in:\033[0m")
        for f in scaffolded_files:
            print(f"    {f}")
            
    return 0

def _run_install_gha(args) -> int:
    from .git_utils import find_repo_root, install_github_actions, GitError
    import sys
    try:
        repo_root = find_repo_root(args.repo)
        wf_path = install_github_actions(repo_root, args.fail_on)
        print(f"\033[92m  Successfully generated GitHub Actions workflow: {wf_path}[0m")
        return 0
    except GitError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2


def _run_history(args) -> int:
    from .history import get_history
    import sys
    records = get_history(str(Path(".").resolve()), limit=args.limit)
    if not records:
        print("No history found. Run `proofline analyze` in a git repository first.")
        return 0
    print("  Proofline Historical Trend")
    print("  --------------------------")
    for r in records:
        print(f"  [{r['timestamp'][:10]}] {r['commit_hash'][:7]} | {r['overall_severity']:<8} | Rules: {r['rules_fired_count']}")
    
    print("\n  Symbols Changed Trend:")
    max_val = max(r['total_symbols_changed'] for r in records) if records else 1
    max_val = max(max_val, 1)
    for r in records:
        bar = "█" * int((r['total_symbols_changed'] / max_val) * 20)
        print(f"  {r['commit_hash'][:7]} | {bar} ({r['total_symbols_changed']})")
    
    return 0

def main(argv: list[str] | None = None) -> int:

    """Main entrypoint. Returns exit code."""
    from .env_parser import load_dotenv
    from .deps_enforcer import ensure_zero_deps
    import os
    
    # Load .env variables implicitly
    load_dotenv()
    
    # Enforce zero dependencies if requirements.txt exists
    ensure_zero_deps()

    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "analyze":
        return _run_analyze(args)
    elif args.command == "scan":
        return _run_scan(args)
    elif args.command == "install-hook":
        return _run_install_hook(args)
    elif args.command == "scaffold-tests":
        return _run_scaffold(args)
    elif args.command == "pack-context":
        return _run_pack_context(args)
    elif args.command == "install-gha":
        return _run_install_gha(args)
    elif args.command == "stdlib-notes":
        from . import stdlib_notes
        print(stdlib_notes.generate_stdlib_md())
        return 0
    elif args.command == "init":
        from .wizard import run_init_wizard
        run_init_wizard(repo_root=str(Path(".").resolve()))
        return 0
    elif args.command == "archive":
        return _run_archive(args)
    elif args.command == "serve":
        from .server import serve_api_server
        serve_api_server(port=args.port, host=args.host, open_browser=not args.no_browser)
        return 0
    else:
        parser.print_help()
        return 0

if __name__ == "__main__":
    sys.exit(main())