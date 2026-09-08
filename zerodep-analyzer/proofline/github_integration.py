"""
github_integration.py — Zero-dependency GitHub PR Comment Poster.
Uses Python stdlib (urllib.request, json, os, ssl).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .evidence_graph import EvidenceGraph


def format_pr_comment_markdown(eg: "EvidenceGraph") -> str:
    """Format an EvidenceGraph into a rich GitHub PR comment in Markdown."""
    from .risk_model import calculate_risk_score

    risk = calculate_risk_score(eg)
    rr = eg.rules_report
    sev = rr.overall_severity.value if rr else "INFO"
    conf = rr.overall_confidence.value if rr else "PROVEN"
    conf_score = rr.confidence_score if rr else 100

    sev_emoji = {"HIGH": "🚨", "MEDIUM": "⚠️", "LOW": "ℹ️", "INFO": "✅"}.get(sev, "ℹ️")
    risk_emoji = {"CRITICAL": "🔥", "HIGH": "🚨", "MEDIUM": "⚠️", "LOW": "✅"}.get(risk.risk_level, "ℹ️")

    md = [
        "## ⬡ Proofline Verification Gate",
        "",
        f"**Risk Level:** {risk_emoji} **`{risk.risk_level}`** ({risk.total_score}/100) | **Severity:** {sev_emoji} `{sev}` | **Confidence:** `{conf}` ({conf_score}/100)",
        "",
    ]

    if risk.factors:
        md.append("### 🎯 Key Risk Factors")
        for f in risk.factors:
            md.append(f"- {f}")
        md.append("")

    # Symbol Table
    if eg.change_summaries:
        md.append("### 📊 Changed Symbols & Blast Radius")
        md.append("| Symbol | Severity | Callers Affected | Tests Associated | Routes |")
        md.append("|---|---|---|---|---|")
        for cs in eg.change_summaries:
            total_c = cs.proven_callers + cs.inferred_callers + cs.unknown_callers
            callers_count = f"{total_c} ({cs.confidence})"
            tests_count = f"{cs.test_count} {'(changed)' if cs.tests_changed else '(unchanged)'}"
            routes_count = len(cs.routes)
            md.append(f"| `{cs.symbol_name}` | **`{cs.severity}`** | {callers_count} | {tests_count} | {routes_count} |")
        md.append("")

    # Checklist
    all_checklists = []
    for cs in eg.change_summaries:
        for item in cs.checklist:
            all_checklists.append((item.priority, item.action, cs.symbol_name))

    if all_checklists:
        md.append("### 📋 Verification Checklist")
        for prio, action, sym in all_checklists[:10]:
            p_badge = "🔴" if prio == "HIGH" else "🟡"
            md.append(f"- [ ] {p_badge} `[{prio}]` {action} (`{sym}`)")
        md.append("")

    md.extend([
        "---",
        "<sub>🛡️ Verified by <b>Proofline</b> — Zero Dependencies · stdlib Python static analysis.</sub>",
    ])

    return "\n".join(md)


def post_github_pr_comment(
    repo: str,
    pr_number: int,
    eg: "EvidenceGraph",
    token: Optional[str] = None,
) -> tuple[bool, str]:
    """
    Post verification report directly as a GitHub PR comment using stdlib urllib.
    
    Args:
        repo: Repository slug e.g. "owner/repo"
        pr_number: Pull request number
        eg: The EvidenceGraph to format and post
        token: GitHub Personal Access Token or GITHUB_TOKEN. Defaults to env var.
        
    Returns:
        (success: bool, message: str)
    """
    auth_token = token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not auth_token:
        return False, "No GitHub token found. Set GITHUB_TOKEN environment variable or pass --github-token."

    # GitHub issues comments API works for both Issues and PRs
    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
    body_md = format_pr_comment_markdown(eg)
    payload = json.dumps({"body": body_md}).encode("utf-8")

    req = urllib.request.Request(
        url=url,
        data=payload,
        headers={
            "Authorization": f"Bearer {auth_token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "Proofline-ZeroDep-VerificationGate",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp_data = json.loads(resp.read().decode("utf-8"))
            html_url = resp_data.get("html_url", url)
            return True, f"Successfully posted comment to PR #{pr_number}: {html_url}"
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8") if e.fp else str(e)
        return False, f"GitHub API error ({e.code}): {err_msg}"
    except Exception as e:
        return False, f"Failed to connect to GitHub API: {str(e)}"
