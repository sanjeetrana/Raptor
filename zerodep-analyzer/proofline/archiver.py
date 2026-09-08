import zipfile
from pathlib import Path
from datetime import datetime
import sys

def create_archive(repo_root: str, report_files: list[str], out_zip: str = None) -> str:
    """Zero-dependency zip packager for Proofline audits."""
    if not out_zip:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_zip = f"proofline_audit_{timestamp}.zip"
        
    root = Path(repo_root).resolve()
    out_path = Path(out_zip).resolve()
    
    print(f"\033[96m  Proofline  packaging audit archive...\033[0m", file=sys.stderr)
    
    with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        # Add generated reports
        for report in report_files:
            rp = Path(report)
            if rp.is_file():
                zf.write(rp, arcname=f"reports/{rp.name}")
                
        # Add configuration files if they exist
        for cfg in [".env", ".prooflineignore", "requirements.txt", ".zero-dep.toml"]:
            cp = root / cfg
            if cp.is_file():
                zf.write(cp, arcname=f"config/{cfg}")
                
        # We don't zip the entire repo to save space, just the proofline artifacts and configs
                
    return str(out_path)
