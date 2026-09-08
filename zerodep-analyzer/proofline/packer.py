from pathlib import Path
from .evidence_graph import EvidenceGraph
from .rules_engine import SEVERITY_ORDER, Severity

def generate_llm_context(eg: EvidenceGraph, after_dir: str, output_path: str) -> None:
    """Generate a Markdown file to feed back into an LLM for fixing."""
    out = [
        "# Proofline Verification Failure Report",
        "",
        "The following code changes were blocked by the Proofline verification engine.",
        "Please fix the issues identified below.",
        ""
    ]
    
    after_path = Path(after_dir)
    processed_files = set()
    
    if not eg.rules_report:
        Path(output_path).write_text("No RulesReport found.", encoding="utf-8")
        return
        
    # Filter for HIGH or MEDIUM risks
    risks = [s for s in eg.rules_report.symbol_reports if SEVERITY_ORDER.index(Severity(s.severity)) <= SEVERITY_ORDER.index(Severity.MEDIUM)]
    
    if not risks:
        Path(output_path).write_text("No HIGH or MEDIUM risks found. Code is clean.", encoding="utf-8")
        return
        
    # We need file names. symbol_reports don't have file names directly, but we can look them up in change_summaries
    file_map = {cs.symbol_name: cs.file for cs in eg.change_summaries}
    
    for risk in risks:
        file_name = file_map.get(risk.symbol_name)
        if not file_name:
            continue
            
        if file_name in processed_files:
            continue
            
        processed_files.add(file_name)
        file_full_path = after_path / file_name
        
        out.append(f"## File: `{file_name}`")
        out.append("")
        
        # Find all risks for this file
        file_risks = [r for r in risks if file_map.get(r.symbol_name) == file_name]
        out.append("### Issues to Fix:")
        for fr in file_risks:
            out.append(f"- **{fr.symbol_name}** [{fr.severity}]")
            for rule in fr.rules_fired:
                out.append(f"  - {rule.rule_name}: {rule.evidence}")
        
        out.append("")
        out.append("### Current Source Code:")
        out.append("```python")
        try:
            source = file_full_path.read_text(encoding="utf-8", errors="replace")
            out.append(source)
        except Exception as e:
            out.append(f"# Error reading file: {e}")
        out.append("```")
        out.append("---")
        out.append("")
        
    Path(output_path).write_text("\n".join(out), encoding="utf-8")
