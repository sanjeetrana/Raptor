"""
report.py — CLI terminal output and HTML report generation.

Stdlib used:
  - ANSI escape codes (replaces 'rich' / 'colorama')
  - http.server.HTTPServer (replaces Flask/FastAPI for local report viewer)
  - string formatting + manual table layout (replaces 'tabulate')
  - json (for data serialization)

The CLI report format matches the PRD §5.7 "Change Completeness" spec exactly.
"""
from __future__ import annotations

import json
import string
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Optional

from .evidence_graph import EvidenceGraph, ChangeSummary
from .rules_engine import RulesReport, SymbolRiskReport, Severity
from .symbol_map import Confidence
from .test_associator import TestAssociation


# ---------------------------------------------------------------------------
# ANSI helpers (replaces 'rich' / 'colorama')
# ---------------------------------------------------------------------------

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

RED = "\033[91m"
YELLOW = "\033[93m"
GREEN = "\033[92m"
CYAN = "\033[96m"
WHITE = "\033[97m"
GREY = "\033[37m"
BLUE = "\033[94m"
MAGENTA = "\033[95m"


def _color(text: str, *codes: str) -> str:
    return "".join(codes) + text + RESET


def _confidence_color(conf: Confidence) -> str:
    mapping = {
        Confidence.PROVEN: GREEN,
        Confidence.INFERRED: YELLOW,
        Confidence.UNKNOWN: GREY,
    }
    return mapping.get(conf, WHITE)


def _severity_color(sev: Severity) -> str:
    mapping = {
        Severity.HIGH: RED,
        Severity.MEDIUM: YELLOW,
        Severity.LOW: BLUE,
        Severity.INFO: GREY,
    }
    return mapping.get(sev, WHITE)


def _yes_no(value: bool, yes_color: str = GREEN, no_color: str = RED) -> str:
    if value:
        return _color("YES", yes_color, BOLD)
    return _color("NO", no_color)


def _hr(width: int = 60, char: str = "─") -> str:
    return char * width


# ---------------------------------------------------------------------------
# CLI Report
# ---------------------------------------------------------------------------

def _render_confidence_badge(conf: Confidence) -> str:
    color = _confidence_color(conf)
    return f"{color}[{conf.value}]{RESET}"


def _render_severity_badge(sev: Severity) -> str:
    color = _severity_color(sev)
    return f"{color}{BOLD}{sev.value}{RESET}"


def render_cli_report(
    eg: EvidenceGraph,
    *,
    no_color: bool = False,
    verbose: bool = False,
) -> str:
    """
    Render the full CLI report as a string.

    Matches the PRD §5.6 and §5.7 format exactly.
    """
    if no_color:
        # Strip ANSI codes for piped output
        import re
        _ansi_escape = re.compile(r"\033\[[0-9;]*m")

        def _strip(s: str) -> str:
            return _ansi_escape.sub("", s)
    else:
        def _strip(s: str) -> str:
            return s

    lines: list[str] = []

    def w(s: str = "") -> None:
        lines.append(_strip(s))

    # Header
    w()
    w(_color("  PROOFLINE", CYAN, BOLD) + _color("  Change Verification Report", WHITE))
    w(_color("  AI made code generation cheap. Verification didn't keep up.", DIM))
    w()
    w(_color(f"  Before: {eg.before_dir}", DIM))
    w(_color(f"  After:  {eg.after_dir}", DIM))
    w()

    if not eg.rules_report or not eg.rules_report.symbol_reports:
        w(_color("  No changed Python symbols detected.", GREY))
        w()
        return "\n".join(lines)

    rr = eg.rules_report
    overall_sev = rr.overall_severity
    overall_conf = rr.overall_confidence

    # Overall risk block
    w(_color("  " + _hr(58), DIM))
    w()
    w(f"  Severity:   {_render_severity_badge(overall_sev)}")
    score = rr.confidence_score if rr else 100
    w(f"  Confidence: {score}/100 {_render_confidence_badge(overall_conf)}")
    from .risk_model import calculate_risk_score
    risk_info = calculate_risk_score(eg)
    risk_badge = f"\033[91m[{risk_info.risk_level}]\033[0m" if risk_info.risk_level in ("CRITICAL", "HIGH") else f"\033[93m[{risk_info.risk_level}]\033[0m" if risk_info.risk_level == "MEDIUM" else f"\033[92m[{risk_info.risk_level}]\033[0m"
    w(f"  Risk Score: {risk_info.total_score}/100 {risk_badge}")
    w()

    # Severity reasons
    all_evidence: list[str] = []
    for sr in rr.symbol_reports:
        all_evidence.extend([r.evidence for r in sr.rules_fired if r.severity == overall_sev])
    if all_evidence:
        w(_color(f"  {overall_sev.value} because:", BOLD))
        for ev in all_evidence[:8]:  # cap at 8 for readability
            w(f"    {_color('•', YELLOW)} {ev}")
        w()

    # Confidence reasons
    conf_reasons: list[str] = []
    for sr in rr.symbol_reports:
        conf_reasons.extend(sr.confidence_reasons)
    conf_reasons = list(dict.fromkeys(conf_reasons))  # deduplicate preserving order
    if conf_reasons:
        w(_color(f"  {overall_conf.value} confidence because:", BOLD))
        for cr in conf_reasons[:5]:
            w(f"    {_color('•', GREY)} {cr}")
        w()

    # Per-symbol Change Completeness reports
    for i, summary in enumerate(eg.change_summaries):
        sr = rr.symbol_reports[i] if i < len(rr.symbol_reports) else None

        w(_color("  " + _hr(58), DIM))
        w()
        w(_color(f"  CHANGE COMPLETENESS  ", CYAN, BOLD) +
          _color(f"{summary.symbol_name}", WHITE, BOLD))
        w(_color("  " + _hr(58, "─"), DIM))
        w()

        # Table
        def row(label: str, value: str) -> None:
            w(f"  {label:<36} {value}")

        row("Implementation changed:", _yes_no(summary.implementation_changed))

        # Callers
        caller_total = summary.total_callers
        if caller_total:
            parts = []
            if summary.proven_callers:
                parts.append(_color(f"{summary.proven_callers} PROVEN", GREEN))
            if summary.inferred_callers:
                parts.append(_color(f"{summary.inferred_callers} INFERRED", YELLOW))
            if summary.unknown_callers:
                parts.append(_color(f"{summary.unknown_callers} UNKNOWN", GREY))
            caller_str = f"{caller_total}  ({' / '.join(parts)})"
        else:
            caller_str = _color("0  (none identified)", GREY)
        row("Direct callers identified:", caller_str)

        # Routes
        if summary.routes:
            route_parts = [
                f"{'+'.join(r.http_methods)} {r.path_pattern or '?'}"
                for r in summary.routes
            ]
            route_str = (
                f"{len(summary.routes)}  "
                + _color("(INFERRED — framework decorator match)", YELLOW)
            )
            row("Public routes affected:", route_str)
            for rp in route_parts:
                w(f"    {_color('→', CYAN)} {rp}")
        else:
            row("Public routes affected:", _color("0", GREY))

        # Tests
        test_changed_str = _yes_no(summary.tests_changed) if summary.test_count > 0 else _color("N/A", GREY)
        row("Relevant tests changed:", test_changed_str)
        test_found_str = (
            _color(f"{summary.test_count}  ", GREEN if summary.test_count > 0 else RED) +
            _color(TestAssociation.DISCLAIMER, GREY)
        )
        row("Relevant tests found:", test_found_str)

        # Docs
        row("Documentation references:", str(summary.doc_references) if summary.doc_references else _color("0", GREY))
        row("Documentation updated:", _yes_no(summary.docs_updated) if summary.doc_references > 0 else _color("N/A", GREY))

        w()

        # Unknown callers warning
        if summary.unknown_callers:
            w(_color(f"  ⚠ UNKNOWN", GREY, BOLD) + f"  {summary.unknown_callers} dynamic caller(s) — getattr/reflection, cannot enumerate")
            w()

        # Checklist
        if summary.checklist:
            w(_color("  Remaining verification:", BOLD))
            for item in summary.checklist:
                priority_badge = (
                    _color(f"[{item.priority}]", RED if item.priority == "HIGH" else YELLOW)
                )
                w(f"    {_color('[ ]', DIM)} {priority_badge} {item.action}")
            w()

        # Test warnings (renamed file etc.)
        if sr and sr.test_warnings:
            for warn in sr.test_warnings:
                w(_color(f"  ⚠ NOTE: {warn}", YELLOW))
            w()

    # Verbose: per-symbol detail
    if verbose:
        w(_color("  " + _hr(58), DIM))
        w(_color("  VERBOSE: Caller detail", BOLD, CYAN))
        w()
        for sr in rr.symbol_reports:
            if sr.caller_result and sr.caller_result.all_edges:
                w(_color(f"  {sr.symbol_name}", BOLD))
                for edge in sr.caller_result.proven_callers:
                    w(f"    {_color('[PROVEN]', GREEN)}   {edge.src}  @ {edge.location}")
                for edge in sr.caller_result.inferred_callers:
                    w(f"    {_color('[INFERRED]', YELLOW)} {edge.src}  @ {edge.location}")
                for edge in sr.caller_result.unknown_callers:
                    w(f"    {_color('[UNKNOWN]', GREY)}   {edge.src}  @ {edge.location}")
                w()

    # Footer
    w(_color("  " + _hr(58), DIM))
    w()
    w(_color("  Limits:", BOLD))
    w(_color("  • Static analysis only — runtime behavior not observed", DIM))
    w(_color("  • Test association = name/import heuristic, NOT runtime coverage", DIM))
    w(_color("  • Route detection = framework decorator pattern match (INFERRED)", DIM))
    w(_color("  • UNKNOWN edges cannot be resolved without runtime data", DIM))
    w(_color("  • Proofline never certifies 'safe to merge'", DIM))
    w()

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTML Report
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Proofline Report</title>
<style>
  :root {
    --bg: #0d1117;
    --bg2: #161b22;
    --bg3: #1c2128;
    --border: #30363d;
    --text: #c9d1d9;
    --text-dim: #8b949e;
    --green: #3fb950;
    --yellow: #d29922;
    --red: #f85149;
    --blue: #58a6ff;
    --cyan: #39d353;
    --proven: #3fb950;
    --inferred: #d29922;
    --unknown: #8b949e;
    --high: #f85149;
    --medium: #d29922;
    --low: #58a6ff;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', 'SF Mono', monospace;
    font-size: 14px;
    line-height: 1.6;
    padding: 2rem;
    max-width: 1100px;
    margin: 0 auto;
  }
  header {
    border-bottom: 1px solid var(--border);
    padding-bottom: 1.5rem;
    margin-bottom: 2rem;
  }
  header h1 {
    font-size: 1.8rem;
    color: var(--cyan);
    letter-spacing: -0.02em;
  }
  header p {
    color: var(--text-dim);
    font-size: 0.85rem;
    margin-top: 0.3rem;
  }
  .meta { color: var(--text-dim); font-size: 0.8rem; margin-top: 0.5rem; }
  .badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 0.75rem;
    font-weight: 700;
    letter-spacing: 0.05em;
    border: 1px solid transparent;
  }
  .badge-proven  { color: var(--proven);  border-color: var(--proven);  background: #1a2e1a; }
  .badge-inferred{ color: var(--inferred);border-color: var(--inferred);background: #2e2600; }
  .badge-unknown { color: var(--unknown); border-color: var(--unknown); background: #1c2128; }
  .severity-high   { color: var(--high);   font-weight: 700; }
  .severity-medium { color: var(--medium); font-weight: 700; }
  .severity-low    { color: var(--low);    font-weight: 700; }
  .severity-info   { color: var(--text-dim); }
  .card {
    background: var(--bg2);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 1.5rem;
    margin-bottom: 1.5rem;
  }
  .card-header {
    display: flex;
    align-items: center;
    gap: 1rem;
    margin-bottom: 1rem;
    padding-bottom: 0.75rem;
    border-bottom: 1px solid var(--border);
  }
  .card-title {
    font-size: 1rem;
    font-weight: 700;
    color: var(--blue);
    word-break: break-all;
  }
  .overview-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1rem;
    margin-bottom: 1rem;
  }
  .stat-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.4rem 0;
    border-bottom: 1px solid var(--border);
  }
  .stat-label { color: var(--text-dim); }
  .stat-value { font-weight: 600; }
  .yes { color: var(--green); }
  .no  { color: var(--red); }
  .na  { color: var(--text-dim); }
  .section-title {
    font-size: 0.7rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--text-dim);
    margin: 1rem 0 0.5rem;
  }
  .checklist { list-style: none; }
  .checklist li {
    padding: 0.4rem 0;
    display: flex;
    gap: 0.75rem;
    align-items: baseline;
    border-bottom: 1px solid var(--border);
  }
  .checklist li:last-child { border-bottom: none; }
  .checklist .checkbox { color: var(--text-dim); }
  .checklist .action { flex: 1; }
  .disclaimer {
    font-size: 0.75rem;
    color: var(--text-dim);
    font-style: italic;
    margin-top: 0.25rem;
  }
  .bullet { color: var(--cyan); margin-right: 0.5rem; }
  .evidence-list { list-style: none; }
  .evidence-list li {
    padding: 0.35rem 0;
    border-bottom: 1px solid var(--border);
    display: flex;
    gap: 0.75rem;
    align-items: baseline;
  }
  .evidence-list li:last-child { border-bottom: none; }
  .caller-item { font-size: 0.85rem; }
  .caller-loc { color: var(--text-dim); font-size: 0.75rem; margin-left: 0.5rem; }
  .overall-box {
    background: var(--bg3);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 1.5rem;
    margin-bottom: 2rem;
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1rem;
  }
  .big-label { font-size: 0.7rem; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.1em; }
  .big-value { font-size: 2rem; font-weight: 700; margin-top: 0.2rem; }
  details { margin-top: 0.5rem; }
  summary {
    cursor: pointer;
    color: var(--blue);
    font-size: 0.85rem;
    padding: 0.35rem 0;
    user-select: none;
  }
  summary:hover { color: var(--cyan); }
  details[open] summary { margin-bottom: 0.5rem; }
  .warn-box {
    background: #2e2000;
    border: 1px solid var(--yellow);
    border-radius: 4px;
    padding: 0.75rem 1rem;
    font-size: 0.8rem;
    color: var(--inferred);
    margin-top: 0.75rem;
  }
  footer {
    margin-top: 3rem;
    padding-top: 1rem;
    border-top: 1px solid var(--border);
    color: var(--text-dim);
    font-size: 0.75rem;
  }
  .limits-list { list-style: none; margin-top: 0.5rem; }
  .limits-list li { padding: 0.2rem 0; }
  .limits-list li::before { content: "• "; color: var(--text-dim); }
  /* Interactive checklist */
  .pl-check {
    appearance: none;
    -webkit-appearance: none;
    width: 18px;
    height: 18px;
    border: 2px solid var(--border);
    border-radius: 4px;
    background: var(--bg);
    cursor: pointer;
    flex-shrink: 0;
    margin-top: 2px;
    transition: all 0.15s ease;
  }
  .pl-check:checked {
    background: var(--green);
    border-color: var(--green);
    position: relative;
  }
  .pl-check:checked::after {
    content: "\2713";
    color: #000;
    font-size: 12px;
    font-weight: 700;
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
  }
  .pl-check:hover { border-color: var(--cyan); }
  .check-item { display: flex; gap: 0.75rem; align-items: flex-start; }
  .check-item label { cursor: pointer; flex: 1; }
  .check-item.done label { text-decoration: line-through; opacity: 0.5; }
  
  /* Progress bar */
  .progress-wrap {
    margin-top: 1rem;
    margin-bottom: 0.5rem;
  }
  .progress-info {
    display: flex;
    justify-content: space-between;
    font-size: 0.75rem;
    color: var(--text-dim);
    margin-bottom: 0.35rem;
  }
  .progress-bar {
    height: 6px;
    background: var(--bg3);
    border-radius: 3px;
    overflow: hidden;
    border: 1px solid var(--border);
  }
  .progress-fill {
    height: 100%;
    background: linear-gradient(90deg, var(--green), var(--cyan));
    border-radius: 3px;
    transition: width 0.3s ease;
    width: 0%;
  }
  .progress-complete .progress-fill {
    background: var(--green);
  }

  /* Enhanced card animations */
  .card {
    transition: border-color 0.2s ease, transform 0.15s ease;
  }
  .card:hover {
    border-color: var(--blue);
    transform: translateY(-1px);
  }

  /* Pulse animation for severity */
  @keyframes pulse-sev {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.7; }
  }
  .big-value.severity-high { animation: pulse-sev 2s ease-in-out infinite; }

  /* Header branding */
  .tagline {
    color: var(--text-dim);
    font-size: 0.8rem;
    font-style: italic;
    margin-top: 0.3rem;
  }
  .header-badge {
    display: inline-block;
    background: var(--bg3);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 0.7rem;
    color: var(--cyan);
    margin-top: 0.5rem;
  }

  @media (max-width: 700px) {
    .overview-grid, .overall-box { grid-template-columns: 1fr; }
    body { padding: 1rem; }
  }
</style>
</head>
<body>
<header>
  <h1>⬡ Proofline</h1>
  <p class="tagline">AI made code generation cheap. Verification didn't keep up.</p>
  <div class="meta">Before: <strong>${before_dir}</strong> &nbsp;|&nbsp; After: <strong>${after_dir}</strong></div>
  <span class="header-badge">Zero Dependencies · stdlib Python only</span>
</header>

<div style="margin-bottom: 2rem;">
  ${svg_heatmap}
</div>

<div class="overall-box">
  <div>
    <div class="big-label">Overall Severity</div>
    <div class="big-value ${severity_class}">${overall_severity}</div>
  </div>
  <div>
    <div class="big-label">Overall Confidence</div>
    <div class="big-value">${confidence_badge}</div>
  </div>
  <div>
    <div class="big-label">Quantitative Risk</div>
    <div class="big-value ${risk_class}">${risk_score}/100 <span class="badge ${risk_badge_class}">${risk_level}</span></div>
  </div>
</div>

<div id="pl-progress-wrap" class="progress-wrap">
  <div class="progress-info">
    <span>Verification Progress</span>
    <span id="pl-progress-info">0 of 0 verified (0%)</span>
  </div>
  <div class="progress-bar"><div id="pl-progress-fill" class="progress-fill"></div></div>
</div>

${symbol_sections}

<footer>
  <strong>Proofline Limits</strong>
  <ul class="limits-list">
    <li>Static analysis only — runtime behavior not observed.</li>
    <li>Test association = name/import heuristic, NOT runtime coverage.</li>
    <li>Route detection = framework decorator pattern match (INFERRED).</li>
    <li>UNKNOWN edges cannot be resolved without runtime data.</li>
    <li>Proofline never certifies "safe to merge."</li>
    <li>Zero third-party dependencies — stdlib Python only.</li>
  </ul>
</footer>

<script>
// Proofline Interactive Checklist — localStorage persistence, zero deps
(function() {
  'use strict';
  var STORAGE_KEY = 'proofline_checks_' + location.pathname;
  var checks = {};
  
  // Load saved state
  try {
    var saved = localStorage.getItem(STORAGE_KEY);
    if (saved) checks = JSON.parse(saved);
  } catch(e) {}
  
  // Apply saved state to checkboxes
  var boxes = document.querySelectorAll('.pl-check');
  boxes.forEach(function(box) {
    var id = box.id;
    if (checks[id]) {
      box.checked = true;
      box.closest('.check-item').classList.add('done');
    }
  });
  
  // Listen for changes
  document.addEventListener('change', function(e) {
    if (!e.target.classList.contains('pl-check')) return;
    var id = e.target.id;
    var item = e.target.closest('.check-item');
    if (e.target.checked) {
      checks[id] = true;
      item.classList.add('done');
    } else {
      delete checks[id];
      item.classList.remove('done');
    }
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(checks)); } catch(e) {}
    updateProgress();
  });
  
  // Progress bar
  function updateProgress() {
    var total = document.querySelectorAll('.pl-check').length;
    var done = document.querySelectorAll('.pl-check:checked').length;
    var pct = total > 0 ? Math.round((done / total) * 100) : 0;
    
    var info = document.getElementById('pl-progress-info');
    var fill = document.getElementById('pl-progress-fill');
    var wrap = document.getElementById('pl-progress-wrap');
    if (info) info.textContent = done + ' of ' + total + ' verified (' + pct + '%)';
    if (fill) fill.style.width = pct + '%';
    if (wrap) {
      if (pct === 100) wrap.classList.add('progress-complete');
      else wrap.classList.remove('progress-complete');
    }
  }
  
  updateProgress();
})();
</script>
</body>
</html>
"""


def _html_bool(value: bool, na: bool = False) -> str:
    if na:
        return '<span class="na">N/A</span>'
    return (
        '<span class="yes">YES</span>' if value
        else '<span class="no">NO</span>'
    )


def _html_confidence_badge(conf_str: str) -> str:
    css = conf_str.lower()
    return f'<span class="badge badge-{css}">{conf_str}</span>'


def _render_symbol_section(summary: ChangeSummary, sr: Optional[SymbolRiskReport]) -> str:
    """Render one card per changed symbol."""
    from .test_associator import TestAssociation as TA

    sev_class = f"severity-{summary.severity.lower()}"

    # Callers
    caller_html = []
    if sr and sr.caller_result:
        for edge in sr.caller_result.proven_callers:
            caller_html.append(
                f'<li class="caller-item">{_html_confidence_badge("PROVEN")} '
                f'{edge.src} <span class="caller-loc">@ {edge.location}</span></li>'
            )
        for edge in sr.caller_result.inferred_callers:
            caller_html.append(
                f'<li class="caller-item">{_html_confidence_badge("INFERRED")} '
                f'{edge.src} <span class="caller-loc">@ {edge.location}</span></li>'
            )
        for edge in sr.caller_result.unknown_callers:
            caller_html.append(
                f'<li class="caller-item">{_html_confidence_badge("UNKNOWN")} '
                f'{edge.src} <span class="caller-loc">@ {edge.location}</span></li>'
            )
    callers_detail = (
        f'<ul class="evidence-list">{"".join(caller_html)}</ul>'
        if caller_html else '<span class="na">none identified</span>'
    )

    # Routes
    route_rows = []
    for route in summary.routes:
        path = route.path_pattern or "?"
        methods = "+".join(route.http_methods)
        route_rows.append(
            f'<li>{_html_confidence_badge("INFERRED")} '
            f'{methods} <strong>{path}</strong> '
            f'<span class="caller-loc">({route.framework})</span></li>'
        )
    routes_html = (
        f'<ul class="evidence-list">{"".join(route_rows)}</ul>'
        if route_rows else '<span class="na">none</span>'
    )

    # Tests
    test_rows = []
    if sr and sr.test_assoc:
        for ct in sr.test_assoc.candidates:
            changed_note = " ✓ changed" if ct.changed_in_patch else ""
            test_rows.append(
                f'<li>{_html_confidence_badge("INFERRED")} '
                f'{ct.test_function_name} '
                f'<span class="caller-loc">({ct.association_method}){changed_note}</span></li>'
            )
    tests_html = (
        f'<ul class="evidence-list">{"".join(test_rows)}</ul>'
        f'<div class="disclaimer">{TA.DISCLAIMER}</div>'
        if test_rows
        else f'<span class="no">none found</span> <div class="disclaimer">{TA.DISCLAIMER}</div>'
    )

    # Rules fired
    rules_html = ""
    if sr and sr.rules_fired:
        rule_items = "".join(
            f'<li><span class="bullet">•</span>'
            f'<strong>R{r.rule_id}</strong> {r.evidence}</li>'
            for r in sr.rules_fired
        )
        rules_html = f'<ul class="evidence-list">{rule_items}</ul>'

    # Checklist
    checklist_html = ""
    if summary.checklist:
        items = "".join(
            f'<li class="check-item" data-id="{summary.symbol_name}-{idx}">'
            f'<input type="checkbox" class="pl-check" id="chk-{summary.symbol_name}-{idx}" />'
            f'<label for="chk-{summary.symbol_name}-{idx}" class="action">'
            f'<span class="severity-{item.priority.lower()}">[{item.priority}]</span> '
            f'{item.action}</label></li>'
            for idx, item in enumerate(summary.checklist)
        )
        checklist_html = f'<p class="section-title">Remaining Verification</p><ul class="checklist">{items}</ul>'

    # Warnings
    warnings_html = ""
    if sr and sr.test_warnings:
        for w in sr.test_warnings:
            warnings_html += f'<div class="warn-box">⚠ {w}</div>'

    conf_badge = _html_confidence_badge(summary.confidence)

    return f"""
<div class="card">
  <div class="card-header">
    <span class="card-title">{summary.symbol_name}</span>
    <span class="{sev_class}">{summary.severity}</span>
    {conf_badge}
    <span class="caller-loc">{summary.file}</span>
  </div>

  <div class="overview-grid">
    <div>
      <div class="stat-row">
        <span class="stat-label">Implementation changed</span>
        <span class="stat-value">{_html_bool(summary.implementation_changed)}</span>
      </div>
      <div class="stat-row">
        <span class="stat-label">Direct callers</span>
        <span class="stat-value">{summary.total_callers}
          ({summary.proven_callers} PROVEN /
           {summary.inferred_callers} INFERRED /
           {summary.unknown_callers} UNKNOWN)</span>
      </div>
      <div class="stat-row">
        <span class="stat-label">Routes affected</span>
        <span class="stat-value">{len(summary.routes)} {_html_confidence_badge("INFERRED") if summary.routes else ""}</span>
      </div>
    </div>
    <div>
      <div class="stat-row">
        <span class="stat-label">Tests changed</span>
        <span class="stat-value">{_html_bool(summary.tests_changed, na=summary.test_count == 0)}</span>
      </div>
      <div class="stat-row">
        <span class="stat-label">Test candidates</span>
        <span class="stat-value">{summary.test_count}</span>
      </div>
      <div class="stat-row">
        <span class="stat-label">Doc references</span>
        <span class="stat-value">{summary.doc_references}</span>
      </div>
    </div>
  </div>

  {rules_html}

  <details>
    <summary>▶ Show callers ({summary.total_callers})</summary>
    {callers_detail}
  </details>

  <details>
    <summary>▶ Show routes ({len(summary.routes)})</summary>
    {routes_html}
  </details>

  <details>
    <summary>▶ Show candidate tests ({summary.test_count})</summary>
    {tests_html}
  </details>

  {checklist_html}
  {warnings_html}
</div>
"""


def render_html_report(eg: EvidenceGraph) -> str:
    """Render a self-contained HTML report. No external resources."""
    rr = eg.rules_report

    overall_sev = rr.overall_severity.value if rr else "INFO"
    overall_conf = rr.overall_confidence.value if rr else "PROVEN"
    severity_class = f"severity-{overall_sev.lower()}"
    score = rr.confidence_score if rr else 100
    confidence_badge = f"{score}/100 " + _html_confidence_badge(overall_conf)

    # Build per-symbol sections
    symbol_sections = ""
    for i, summary in enumerate(eg.change_summaries):
        sr = rr.symbol_reports[i] if rr and i < len(rr.symbol_reports) else None
        symbol_sections += _render_symbol_section(summary, sr)

    if not symbol_sections:
        symbol_sections = '<div class="card"><p>No changed Python symbols detected.</p></div>'

    html = _HTML_TEMPLATE
    html = html.replace("${before_dir}", eg.before_dir)
    html = html.replace("${after_dir}", eg.after_dir)
    html = html.replace("${overall_severity}", overall_sev)
    html = html.replace("${severity_class}", severity_class)
    from .svg_generator import generate_svg_heatmap
    svg_heatmap = generate_svg_heatmap(eg)
    
    from .risk_model import calculate_risk_score
    risk_info = calculate_risk_score(eg)
    risk_class = f"severity-{risk_info.risk_level.lower()}"
    risk_badge_class = f"badge-{risk_info.risk_level.lower()}"
    html = html.replace("${risk_score}", str(risk_info.total_score))
    html = html.replace("${risk_level}", risk_info.risk_level)
    html = html.replace("${risk_class}", risk_class)
    html = html.replace("${risk_badge_class}", risk_badge_class)
    html = html.replace("${confidence_badge}", confidence_badge)
    html = html.replace("${symbol_sections}", symbol_sections)
    html = html.replace("${svg_heatmap}", svg_heatmap)

    return html


# ---------------------------------------------------------------------------
# JSON export
# ---------------------------------------------------------------------------

def render_json_report(eg: EvidenceGraph) -> str:
    """Export the evidence graph as JSON (stdlib json)."""
    return eg.to_json(indent=2)


# ---------------------------------------------------------------------------
# Local HTTP server (replaces Flask for report viewing)
# ---------------------------------------------------------------------------

class _ReportHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler that serves the HTML report. Stdlib http.server."""

    html_content: bytes = b""
    json_content: bytes = b""

    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(self.__class__.html_content)))
            self.end_headers()
            self.wfile.write(self.__class__.html_content)
        elif self.path == "/report.json":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(self.__class__.json_content)))
            self.end_headers()
            self.wfile.write(self.__class__.json_content)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass  # Suppress default access log


def serve_report(
    eg: EvidenceGraph,
    port: int = 8080,
    open_browser: bool = True,
) -> None:
    """
    Serve the HTML report on localhost via stdlib http.server.

    This replaces Flask/FastAPI for the local report viewer.
    Press Ctrl+C to stop.
    """
    html = render_html_report(eg).encode("utf-8")
    json_data = render_json_report(eg).encode("utf-8")

    _ReportHandler.html_content = html
    _ReportHandler.json_content = json_data

    server = HTTPServer(("127.0.0.1", port), _ReportHandler)
    url = f"http://localhost:{port}/"

    print(f"\n  {CYAN}Proofline report server{RESET}")
    print(f"  {GREEN}→{RESET} {url}")
    print(f"  {DIM}Press Ctrl+C to stop{RESET}\n")

    if open_browser:
        import webbrowser
        # Use threading to not block server startup
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print(f"\n  {DIM}Server stopped.{RESET}")
        server.server_close()





def render_diff_report(eg: EvidenceGraph, diff_result, *, no_color: bool = False) -> str:
    rr = eg.rules_report
    
    # Map rules by file
    rules_by_file = {}
    if rr:
        for sr in rr.symbol_reports:
            if not sr.rules_fired:
                continue
            path = sr.sym_diff.relative_path
            if path not in rules_by_file:
                rules_by_file[path] = []
            
            for rule in sr.rules_fired:
                rules_by_file[path].append(f"[{sr.symbol_name}] R{rule.rule_id} ({rule.severity.value}): {rule.evidence}")

    lines = []
    lines.append("")
    lines.append("  PROOFLINE  Annotated Diff")
    lines.append("  " + "─" * 58)
    lines.append("")

    for fc in diff_result.file_changes:
        if not fc.after_path: # deleted file
            continue
            
        diff_lines = fc.unified_diff if fc.unified_diff else []
        if not diff_lines:
            continue
            
        lines.append(f"diff --git a/{fc.relative_path} b/{fc.relative_path}")
        
        # Inject annotations at the file level
        if fc.relative_path in rules_by_file:
            lines.append("")
            for ann in rules_by_file[fc.relative_path]:
                if not no_color:
                    lines.append(f"\033[93m  ⚠ {ann}\033[0m")
                else:
                    lines.append(f"  ⚠ {ann}")
            lines.append("")
            
        for d in diff_lines:
            if not no_color:
                if d.startswith('+'):
                    lines.append(f"\033[32m{d}\033[0m")
                elif d.startswith('-'):
                    lines.append(f"\033[31m{d}\033[0m")
                elif d.startswith('@@'):
                    lines.append(f"\033[36m{d}\033[0m")
                else:
                    lines.append(d)
            else:
                lines.append(d)
        lines.append("")
        
    if not lines or len(lines) <= 5:
        return "  No differences found."
        
    return "\n".join(lines)
def render_summary_report(eg: EvidenceGraph) -> str:
    """Render a one-line summary for CI log output."""
    rr = eg.rules_report
    if not rr or not rr.symbol_reports:
        return "PROOFLINE: INFO — no changes detected"
    
    sr = rr.symbol_reports[0]  # Primary symbol
    sev = rr.overall_severity.value
    name = sr.symbol_name
    
    # Collect fired rule names
    rule_tags = []
    for r in sr.rules_fired:
        tag = {
            1: "sig_changed",
            2: "exc_changed",
            3: "broad_exception",
            4: "security",
            5: "route_changed",
            6: "no_tests",
            7: "tests_stale",
            8: "import_changed",
            9: "doc_rot",
        }.get(r.rule_id, f"R{r.rule_id}")
        rule_tags.append(tag)
    rules_str = "+".join(rule_tags) if rule_tags else "none"
    
    callers = sr.caller_result.total_callers if sr.caller_result else 0
    tests = sr.test_assoc.total_candidates if sr.test_assoc else 0
    
    return f"PROOFLINE: {sev} [{name}] {rules_str} | {callers} callers | {tests} tests"


def render_graph_report(eg: EvidenceGraph, *, no_color: bool = False) -> str:
    """Render a text-based impact graph using box-drawing characters."""
    rr = eg.rules_report
    if not rr or not rr.symbol_reports:
        return "  No changes to graph."
    
    lines = []
    lines.append("")
    lines.append("  PROOFLINE  Impact Graph")
    lines.append("  " + "\u2500" * 50)
    lines.append("")
    
    for sr in rr.symbol_reports:
        sev = sr.severity.value
        sym = sr.symbol_name
        
        # Color codes
        sev_color = {"HIGH": "\033[91m", "MEDIUM": "\033[93m", "LOW": "\033[94m"}.get(sev, "")
        reset = "\033[0m"
        dim = "\033[2m"
        cyan = "\033[96m"
        green = "\033[92m"
        yellow = "\033[93m"
        grey = "\033[90m"
        
        if no_color:
            sev_color = reset = dim = cyan = green = yellow = grey = ""
        
        lines.append(f"  {cyan}{sym}{reset} {dim}(MODIFIED \u2014 {sev_color}{sev}{reset}{dim}){reset}")
        
        # Callers
        all_callers = []
        if sr.caller_result:
            for e in sr.caller_result.proven_callers:
                all_callers.append((e.src, "PROVEN", e.location))
            for e in sr.caller_result.inferred_callers:
                all_callers.append((e.src, "INFERRED", e.location))
            for e in sr.caller_result.unknown_callers:
                all_callers.append((e.src, "UNKNOWN", e.location))
        
        # Routes
        routes = []
        for cs in eg.change_summaries:
            if cs.symbol_name == sr.symbol_name:
                routes = cs.routes
                break
        
        # Tests
        tests = []
        if sr.test_assoc:
            tests = sr.test_assoc.candidates
        
        # Checklist
        checklist = []
        for cs in eg.change_summaries:
            if cs.symbol_name == sr.symbol_name:
                checklist = cs.checklist
                break
        
        total_children = len(all_callers) + len(routes) + len(tests) + len(checklist)
        if total_children == 0:
            lines.append(f"  {dim}\u2514\u2500\u2500 (no callers, routes, or tests identified){reset}")
            lines.append("")
            continue
        
        idx = 0
        
        # Callers section
        for i, (name, conf, loc) in enumerate(all_callers):
            idx += 1
            is_last = idx == total_children
            branch = "\u2514" if is_last else "\u251c"
            conf_color = {"PROVEN": green, "INFERRED": yellow, "UNKNOWN": grey}.get(conf, "")
            lines.append(f"  {branch}\u2500\u2500 caller: {name} {conf_color}({conf}){reset} {dim}@ {loc}{reset}")
        
        # Routes section
        for route in routes:
            idx += 1
            is_last = idx == total_children
            branch = "\u2514" if is_last else "\u251c"
            path = route.path_pattern or "?"
            methods = "+".join(route.http_methods)
            lines.append(f"  {branch}\u2500\u2500 route: {methods} {path} {yellow}(INFERRED){reset}")
        
        # Tests section
        for ct in tests:
            idx += 1
            is_last = idx == total_children
            branch = "\u2514" if is_last else "\u251c"
            changed = f"{green}\u2713 changed{reset}" if ct.changed_in_patch else f"{sev_color}\u26a0 unchanged{reset}"
            lines.append(f"  {branch}\u2500\u2500 test: {ct.test_function_name} ({changed})")
        
        # Checklist items
        for item in checklist:
            idx += 1
            is_last = idx == total_children
            branch = "\u2514" if is_last else "\u251c"
            prio_color = {"HIGH": sev_color, "MEDIUM": yellow}.get(item.priority, "")
            lines.append(f"  {branch}\u2500\u2500 {prio_color}[{item.priority}]{reset} {item.action}")
        
        lines.append("")
    
    lines.append("  " + "\u2500" * 50)
    lines.append("")
    return "\n".join(lines)

def render_sarif_report(eg: EvidenceGraph) -> str:
    import json
    
    rules_metadata = [
        {"id": "PL001", "name": "Public signature changed", "shortDescription": {"text": "Public function signature changed"}},
        {"id": "PL002", "name": "Exception behavior changed", "shortDescription": {"text": "Exception handling changed inside function"}},
        {"id": "PL003", "name": "Broad exception handler added", "shortDescription": {"text": "Broad exception handler added (except Exception or bare except)"}},
        {"id": "PL004", "name": "Security-sensitive operation changed", "shortDescription": {"text": "Security-sensitive operation changed (auth, secret, key, password)"}},
        {"id": "PL005", "name": "Public route behavior changed", "shortDescription": {"text": "Public HTTP route changed or affected"}},
        {"id": "PL006", "name": "No statically associated test found", "shortDescription": {"text": "Changed function has no statically associated test"}},
        {"id": "PL007", "name": "Associated tests unchanged", "shortDescription": {"text": "Associated tests unchanged despite logic changes"}},
        {"id": "PL008", "name": "Import/dependency edge changed", "shortDescription": {"text": "Import/dependency edge changed in file"}},
        {"id": "PL009", "name": "Docstring not updated", "shortDescription": {"text": "Implementation logic changed but docstring was not updated (doc rot)"}},
    ]
    
    sarif_rules = []
    for r in rules_metadata:
        sarif_rules.append({
            "id": r["id"],
            "name": r["name"],
            "shortDescription": r["shortDescription"],
        })
        
    results = []
    for sr in eg.rules_report.symbol_reports:
        for rule in sr.rules_fired:
            rule_id_str = f"PL{rule.rule_id:03d}"
            
            level = "warning"
            if rule.severity.value == "HIGH":
                level = "error"
            elif rule.severity.value == "INFO":
                level = "note"
                
            loc = None
            fn = sr.sym_diff.after or sr.sym_diff.before
            if fn and fn.location:
                loc = fn.location
                
            start_line = loc.line if loc else 1
            start_col = (loc.col + 1) if loc else 1
            
            result = {
                "ruleId": rule_id_str,
                "level": level,
                "message": {
                    "text": f"[{sr.symbol_name}] {rule.evidence}"
                },
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {
                                "uri": sr.sym_diff.relative_path
                            },
                            "region": {
                                "startLine": start_line,
                                "startColumn": start_col
                            }
                        }
                    }
                ]
            }
            results.append(result)
            
    sarif = {
        "$schema": "https://schemastore.azurewebsites.net/schemas/json/sarif-2.1.0-rtm.5.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "Proofline",
                        "informationUri": "https://github.com/urjit-upadhyay/proofline",
                        "rules": sarif_rules
                    }
                },
                "results": results
            }
        ]
    }
    return json.dumps(sarif, indent=2)
