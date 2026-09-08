import os
import time
from pathlib import Path
from .core import run_analysis
from .report import render_cli_report as generate_report

def _get_mtime_hash(directory: str) -> str:
    """Computes a quick aggregate hash of modification times for debounce."""
    mtimes = []
    for root, _, files in os.walk(directory):
        # Skip cache and git
        if ".proofline" in root or ".git" in root or "__pycache__" in root:
            continue
        for file in files:
            if file.endswith(".py"):
                try:
                    mtimes.append(str(os.stat(os.path.join(root, file)).st_mtime))
                except OSError:
                    pass
    return "|".join(mtimes)

def watch_repo(before_dir: str, after_dir: str):
    """
    Watches the after_dir for file changes.
    When a change is detected, re-runs the analysis.
    If HIGH severity is detected, triggers a terminal bell.
    """
    print(f"\033[94m[Watcher] Starting zero-dependency file watch on '{after_dir}'...\033[0m")
    print("Press Ctrl+C to stop.")
    
    last_hash = _get_mtime_hash(after_dir)
    
    try:
        while True:
            time.sleep(1.5)  # 1.5s polling loop
            
            current_hash = _get_mtime_hash(after_dir)
            if current_hash != last_hash:
                print("\n\033[93m[Watcher] File change detected! Re-running analysis...\033[0m")
                last_hash = current_hash
                
                # Debounce: wait a tiny bit to let multi-file saves finish
                time.sleep(0.5)
                # Re-calculate hash in case more files changed during the wait
                last_hash = _get_mtime_hash(after_dir)
                
                diff, cg, cr, routes, ta, tw, rr, eg = run_analysis(before_dir, after_dir)
                report = generate_report(rr, eg)
                
                with open("proofline_audit_report.html", "w", encoding="utf-8") as f:
                    f.write(report)
                    
                if rr.overall_severity.name == "HIGH":
                    # Play terminal bell!
                    print("\a\033[91m[Watcher] HIGH SEVERITY DETECTED! Terminal Bell Rung!\033[0m")
                else:
                    print(f"\033[92m[Watcher] Analysis complete. Severity: {rr.overall_severity.name}\033[0m")
                    
    except KeyboardInterrupt:
        print("\n\033[94m[Watcher] Shutting down gracefully.\033[0m")
        return True
