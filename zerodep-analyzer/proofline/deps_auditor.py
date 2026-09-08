import os
import re
from proofline.rules_engine import RuleResult, Severity, Confidence

def check_dependencies(before_dir: str, after_dir: str) -> list[RuleResult]:
    """
    Check if the attack surface increased due to new dependencies
    in requirements.txt or pyproject.toml.
    
    Returns a list of RuleResult objects (Rule 10).
    """
    results = []
    
    # Check requirements.txt
    req_before = os.path.join(before_dir, "requirements.txt")
    req_after = os.path.join(after_dir, "requirements.txt")
    
    deps_before = _parse_requirements(req_before)
    deps_after = _parse_requirements(req_after)
    
    added_reqs = deps_after - deps_before
    if added_reqs:
        results.append(
            RuleResult(
                rule_id=10,
                rule_name="Dependency Attack Surface Increased",
                severity=Severity.LOW,
                evidence=f"New dependencies added to requirements.txt: {', '.join(added_reqs)}. This increases the third-party attack surface.",
                confidence=Confidence.PROVEN,
                location_hint=os.path.join(after_dir, "requirements.txt")
            )
        )
        
    return results

def _parse_requirements(path: str) -> set[str]:
    """Extract package names from a requirements.txt file."""
    deps = set()
    if not os.path.exists(path):
        return deps
        
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            
            # Simple regex to extract package name before operators like ==, >=, etc.
            m = re.match(r"^([a-zA-Z0-9_\-]+)", line)
            if m:
                deps.add(m.group(1).lower())
                
    return deps
