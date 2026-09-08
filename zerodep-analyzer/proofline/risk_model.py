"""
risk_model.py — Quantitative Risk Scoring Engine for Proofline.
Zero third-party dependencies. Python stdlib only.

Combines rule severities, caller graph blast radius, test coverage gaps,
security boundaries, and confidence levels into a standardized 0-100 Risk Score.
"""
from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .evidence_graph import EvidenceGraph


@dataclasses.dataclass
class RiskBreakdown:
    severity_score: float        # 0.0 - 100.0
    blast_radius_score: float    # 0.0 - 100.0
    test_gap_score: float        # 0.0 - 100.0
    security_score: float        # 0.0 - 100.0
    confidence_penalty: float    # 0.0 - 100.0
    total_score: int             # 0 - 100
    risk_level: str              # CRITICAL, HIGH, MEDIUM, LOW
    factors: list[str]


def calculate_risk_score(eg: "EvidenceGraph") -> RiskBreakdown:
    """
    Calculate an aggregate 0-100 Risk Score from an EvidenceGraph.
    
    Weights:
      • Severity Weight:    30%
      • Blast Radius:       25%
      • Test Gap:           20%
      • Security Impact:    15%
      • Confidence Penalty: 10%
    """
    factors: list[str] = []
    
    # 1. Severity Component (0-100)
    high_count = 0
    medium_count = 0
    low_count = 0
    
    if eg.rules_report:
        for sr in eg.rules_report.symbol_reports:
            for r in sr.rules_fired:
                sev = r.severity.value if hasattr(r.severity, "value") else str(r.severity)
                if sev == "HIGH":
                    high_count += 1
                elif sev == "MEDIUM":
                    medium_count += 1
                elif sev == "LOW":
                    low_count += 1
                    
        for gr in getattr(eg.rules_report, "global_rules", []):
            sev = gr.severity.value if hasattr(gr.severity, "value") else str(gr.severity)
            if sev == "HIGH":
                high_count += 1
            elif sev == "MEDIUM":
                medium_count += 1
            elif sev == "LOW":
                low_count += 1

    sev_raw = (high_count * 40.0) + (medium_count * 15.0) + (low_count * 5.0)
    if high_count > 0:
        sev_raw = max(sev_raw, 70.0)
    severity_score = min(100.0, sev_raw)
    if high_count > 0:
        factors.append(f"{high_count} HIGH severity rule(s) triggered")
    elif medium_count > 0:
        factors.append(f"{medium_count} MEDIUM severity rule(s) triggered")

    # 2. Blast Radius Component (0-100)
    total_callers = 0
    if hasattr(eg, "change_summaries") and eg.change_summaries:
        for cs in eg.change_summaries:
            total_callers += (getattr(cs, "proven_callers", 0) + getattr(cs, "inferred_callers", 0) + getattr(cs, "unknown_callers", 0))
    elif hasattr(eg, "caller_results") and eg.caller_results:
        for c_res in eg.caller_results.values():
            total_callers += len(getattr(c_res, "direct_callers", []))
            
    if total_callers == 0:
        blast_score = 0.0
    elif total_callers <= 2:
        blast_score = 25.0
    elif total_callers <= 5:
        blast_score = 55.0
    elif total_callers <= 10:
        blast_score = 80.0
    else:
        blast_score = 100.0
        
    if total_callers > 0:
        factors.append(f"Blast radius: {total_callers} caller(s) affected")

    # 3. Test Gap Component (0-100)
    changed_symbols = eg.rules_report.symbol_reports if eg.rules_report else []
    if not changed_symbols:
        test_gap_score = 0.0
    else:
        untested_count = 0
        for sr in changed_symbols:
            rule_ids = [r.rule_id for r in sr.rules_fired]
            if 6 in rule_ids or 7 in rule_ids:
                untested_count += 1
        test_gap_ratio = untested_count / len(changed_symbols)
        test_gap_score = min(100.0, test_gap_ratio * 100.0)
        if untested_count > 0:
            factors.append(f"Test coverage gap: {untested_count}/{len(changed_symbols)} changed symbol(s) missing/unupdated tests")

    # 4. Security Impact (0-100)
    sec_score = 0.0
    sec_rules_fired = 0
    if eg.rules_report:
        for sr in eg.rules_report.symbol_reports:
            for r in sr.rules_fired:
                if r.rule_id in (3, 4, 10):
                    sec_rules_fired += 1
                    if r.rule_id == 4:
                        sec_score = max(sec_score, 85.0)
                    elif r.rule_id == 3:
                        sec_score = max(sec_score, 75.0)
                    elif r.rule_id == 10:
                        sec_score = max(sec_score, 90.0)
    if sec_rules_fired > 0:
        sec_score = min(100.0, sec_score + (sec_rules_fired - 1) * 10.0)
        factors.append(f"Security sensitive operations modified ({sec_rules_fired} warning(s))")

    # 5. Confidence Penalty (0-100)
    conf_value = 100
    if eg.rules_report and hasattr(eg.rules_report, "confidence_score"):
        conf_value = eg.rules_report.confidence_score
    elif hasattr(eg, "confidence_score"):
        conf_value = eg.confidence_score
    conf_penalty = max(0.0, float(100 - conf_value))
    if conf_penalty > 30:
        factors.append(f"High static analysis uncertainty (confidence: {conf_value}/100)")

    # Weighted Sum
    total_float = (
        0.30 * severity_score +
        0.25 * blast_score +
        0.20 * test_gap_score +
        0.15 * sec_score +
        0.10 * conf_penalty
    )
    total_score = max(0, min(100, int(round(total_float))))
    
    if total_score >= 75:
        risk_level = "CRITICAL"
    elif total_score >= 50:
        risk_level = "HIGH"
    elif total_score >= 25:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"
        
    return RiskBreakdown(
        severity_score=round(severity_score, 1),
        blast_radius_score=round(blast_score, 1),
        test_gap_score=round(test_gap_score, 1),
        security_score=round(sec_score, 1),
        confidence_penalty=round(conf_penalty, 1),
        total_score=total_score,
        risk_level=risk_level,
        factors=factors,
    )
