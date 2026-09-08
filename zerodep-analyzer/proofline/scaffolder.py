import os
from pathlib import Path
from .evidence_graph import EvidenceGraph

def generate_test_scaffold(eg: EvidenceGraph, project_root: str) -> list[str]:
    """
    Generate boilerplate unittest files for changed functions that fired rules.
    Returns a list of created file paths.
    """
    if not eg.rules_report:
        return []

    project_root_path = Path(project_root)
    tests_dir = project_root_path / "tests"
    tests_dir.mkdir(exist_ok=True)
    
    scaffolded_files = []

    for sr in eg.rules_report.symbol_reports:
        if not sr.rules_fired:
            continue
            
        sym_file = Path(sr.sym_diff.relative_path)
        test_file_name = f"test_{sym_file.stem}.py"
        test_file_path = tests_dir / test_file_name
        
        module_name = sym_file.with_suffix("").as_posix().replace("/", ".")
        symbol_name = sr.symbol_name.split(".")[-1]
        
        lines = []
        if not test_file_path.exists():
            lines.append(f'"""Tests for {module_name} (Auto-scaffolded by Proofline)"""')
            lines.append("import unittest")
            lines.append(f"from {module_name} import {symbol_name}")
            lines.append("")
            lines.append(f"class Test{symbol_name.capitalize()}(unittest.TestCase):")
        else:
            lines.append("")
            lines.append(f"class Test{symbol_name.capitalize()}_Scaffold(unittest.TestCase):")
            
        for rule in sr.rules_fired:
            lines.append(f"    def test_scaffold_rule_{rule.rule_id}(self):")
            lines.append(f"        \"\"\"")
            lines.append(f"        TODO: Proofline detected a risk here.")
            lines.append(f"        Rule {rule.rule_id} ({rule.severity.value}): {rule.evidence}")
            lines.append(f"        \"\"\"")
            lines.append(f"        # Implement test logic for {symbol_name} to verify this behavior")
            lines.append(f"        self.fail('Test scaffolding incomplete for Rule {rule.rule_id}')")
            lines.append("")
            
        with open(test_file_path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
            
        if str(test_file_path) not in scaffolded_files:
            scaffolded_files.append(str(test_file_path))
            
    return scaffolded_files
