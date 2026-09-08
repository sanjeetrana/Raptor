import json
import os
from typing import Dict, Any, List
from proofline.rules_engine import RulesReport, Severity

def _severity_to_sarif_level(severity: Severity) -> str:
    """Map Proofline severities to SARIF levels."""
    if severity == Severity.HIGH:
        return "error"
    elif severity == Severity.MEDIUM:
        return "warning"
    else:
        return "note"

def generate_sarif(report: RulesReport) -> Dict[str, Any]:
    """
    Generate a SARIF v2.1.0 compliant dictionary from a RulesReport.
    """
    sarif: Dict[str, Any] = {
        "version": "2.1.0",
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "Proofline",
                        "informationUri": "https://github.com/proofline/proofline",
                        "rules": []
                    }
                },
                "results": []
            }
        ]
    }

    rules_seen = set()
    driver_rules = sarif["runs"][0]["tool"]["driver"]["rules"]
    results = sarif["runs"][0]["results"]

    def _add_rule(rule_id: int, rule_name: str):
        rule_key = f"proofline-{rule_id}"
        if rule_key not in rules_seen:
            rules_seen.add(rule_key)
            driver_rules.append({
                "id": rule_key,
                "name": rule_name.replace(" ", ""),
                "shortDescription": {
                    "text": rule_name
                }
            })
        return rule_key

    # Process global rules
    global_rules = getattr(report, "global_rules", [])
    for gr in global_rules:
        rule_key = _add_rule(gr.rule_id, gr.rule_name)
        
        # Try to parse location_hint
        uri = "unknown"
        if gr.location_hint:
            uri = gr.location_hint.replace("\\", "/")
            
        res = {
            "ruleId": rule_key,
            "level": _severity_to_sarif_level(gr.severity),
            "message": {
                "text": f"[{gr.confidence.name}] {gr.evidence}"
            },
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {
                            "uri": uri
                        }
                    }
                }
            ]
        }
        results.append(res)

    # Process symbol reports
    for sr in report.symbol_reports:
        for r in sr.rules_fired:
            rule_key = _add_rule(r.rule_id, r.rule_name)
            
            uri = "unknown"
            start_line = 1
            if r.location_hint:
                # Expecting format: filepath:line
                parts = r.location_hint.rsplit(":", 1)
                if len(parts) == 2 and parts[1].isdigit():
                    uri = parts[0].replace("\\", "/")
                    start_line = int(parts[1])
                else:
                    uri = r.location_hint.replace("\\", "/")
                    
            res = {
                "ruleId": rule_key,
                "level": _severity_to_sarif_level(r.severity),
                "message": {
                    "text": f"[{r.confidence.name}] {r.evidence}"
                },
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {
                                "uri": uri
                            },
                            "region": {
                                "startLine": start_line
                            }
                        }
                    }
                ]
            }
            results.append(res)

    return sarif

def write_sarif(report: RulesReport, output_path: str):
    """Write the SARIF report to a file."""
    sarif_data = generate_sarif(report)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(sarif_data, f, indent=2)
