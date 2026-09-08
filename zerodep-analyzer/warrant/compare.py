from pathlib import Path
import json

def _ansi_color(text: str, color_code: str) -> str:
    return f"\033[{color_code}m{text}\033[0m"

def _c(text: str, *styles: str) -> str:
    codes = {
        "bold": "1",
        "red": "31",
        "green": "32",
        "yellow": "33",
        "blue": "34",
    }
    for s in styles:
        text = _ansi_color(text, codes.get(s, "0"))
    return text

def compare_indexes(before_idx, after_idx) -> dict:
    """
    Compare two Warrant indexes and compute the severity delta.
    Returns a dictionary of statistics and a printable report.
    """
    before_audit = before_idx.audit()
    after_audit = after_idx.audit()
    
    before_risky = {x["qname"]: x for x in before_audit["risky_symbols"]}
    after_risky = {x["qname"]: x for x in after_audit["risky_symbols"]}
    
    resolved = set(before_risky.keys()) - set(after_risky.keys())
    new_risks = set(after_risky.keys()) - set(before_risky.keys())
    still_open = set(before_risky.keys()).intersection(set(after_risky.keys()))
    
    # Analyze doc rot transitions
    # A function might have become STALE (doc rot)
    doc_rot_new = []
    doc_rot_fixed = []
    for qname in after_idx.badges:
        b_before = before_idx.badges.get(qname)
        b_after = after_idx.badges.get(qname)
        
        if b_after and b_after.stale.is_stale:
            if not b_before or not b_before.stale.is_stale:
                doc_rot_new.append((qname, b_after.stale.reason))
        if b_before and b_before.stale.is_stale:
            if not b_after or not b_after.stale.is_stale:
                doc_rot_fixed.append(qname)
                
    return {
        "before_total_risky": len(before_risky),
        "after_total_risky": len(after_risky),
        "resolved": list(resolved),
        "new_risks": list(new_risks),
        "still_open": list(still_open),
        "doc_rot_new": doc_rot_new,
        "doc_rot_fixed": doc_rot_fixed,
        "before_breakdown": before_audit.get("badge_breakdown", {}),
        "after_breakdown": after_audit.get("badge_breakdown", {}),
    }

def print_compare_report(delta: dict):
    b_risky = delta["before_total_risky"]
    a_risky = delta["after_total_risky"]
    
    print(_c("\n  WARRANT  Compare Report", "bold"))
    print()
    
    if a_risky < b_risky:
        trend = _c("IMPROVING", "green", "bold")
    elif a_risky > b_risky:
        trend = _c("REGRESSING", "red", "bold")
    else:
        trend = _c("STAGNANT", "yellow", "bold")
        
    print(f"  Overall Trend:  {trend}  ({b_risky} -> {a_risky} risky functions)")
    print()
    
    if delta["resolved"]:
        print(_c("  Resolved Risks (Good job!):", "green"))
        for r in delta["resolved"]:
            print(f"    - {r}")
        print()
            
    if delta["new_risks"]:
        print(_c("  New Risks Introduced (Warning):", "red"))
        for r in delta["new_risks"]:
            print(f"    - {r}")
        print()
            
    if delta["still_open"]:
        print(_c("  Still Open (Load-bearing & Untested):", "yellow"))
        for r in delta["still_open"]:
            print(f"    - {r}")
        print()
        
    if delta["doc_rot_new"]:
        print(_c("  New Doc Rot Detected:", "red"))
        for r, reason in delta["doc_rot_new"]:
            print(f"    - {r} ({reason})")
        print()
        
    if delta["doc_rot_fixed"]:
        print(_c("  Doc Rot Fixed:", "green"))
        for r in delta["doc_rot_fixed"]:
            print(f"    - {r}")
        print()
    
    return
