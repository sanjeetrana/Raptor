"""
single_file_bundler.py — Bundles all Proofline modules into a single standalone .py file.
No external dependencies. Pure standard library.
"""
from __future__ import annotations

import base64
import os
import sys
import zipfile
import io
from pathlib import Path

# Order of files matters for proper dependency loading
MODULE_FILES = [
    "symbol_map.py",
    "diff_engine.py",
    "caller_graph.py",
    "route_detector.py",
    "test_associator.py",
    "rules_engine.py",
    "evidence_graph.py",
    "risk_model.py",
    "svg_generator.py",
    "report.py",
    "git_utils.py",
    "deps_auditor.py",
    "deps_enforcer.py",
    "ignore_parser.py",
    "env_parser.py",
    "github_integration.py",
    "scaffolder.py",
    "history.py",
    "server.py",
    "core.py",
    "cli.py",
]


def bundle_to_single_file(output_path: str = "proofline_single.py") -> Path:
    """Bundle the proofline package into a single-file executable."""
    proofline_dir = Path(__file__).parent.resolve()
    root_dir = proofline_dir.parent

    # Create in-memory zip of the package
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname in MODULE_FILES:
            fpath = proofline_dir / fname
            if fpath.exists():
                zf.writestr(f"proofline/{fname}", fpath.read_text("utf-8"))
        
        # Add __init__.py and __main__.py
        zf.writestr("proofline/__init__.py", "__version__ = '12.0.0'\n")
        zf.writestr(
            "proofline/__main__.py",
            "import sys\nfrom proofline.cli import main\nsys.exit(main())\n",
        )

    zip_bytes = zip_buf.getvalue()
    b64_zip = base64.b64encode(zip_bytes).decode("ascii")

    # Construct bootstrap single-file script
    template = f'''#!/usr/bin/env python3
"""
Proofline Standalone Single-File Distribution (Zero Dependency 2026).
Verification gate for AI-generated code changes.
"""
import sys
import os
import io
import base64
import zipfile
import tempfile

_ZIP_PAYLOAD = """{b64_zip}"""

def _bootstrap_and_run():
    raw_zip = base64.b64decode(_ZIP_PAYLOAD.strip())
    # Extract to memory / zipimport or tempdir
    tmpdir = tempfile.mkdtemp(prefix="proofline_single_")
    zf = zipfile.ZipFile(io.BytesIO(raw_zip))
    zf.extractall(tmpdir)
    sys.path.insert(0, tmpdir)
    
    from proofline.cli import main
    sys.exit(main())

if __name__ == "__main__":
    _bootstrap_and_run()
'''

    out = Path(root_dir) / output_path
    out.write_text(template, encoding="utf-8")
    print(f"  [Single-File Packer] Successfully bundled to: {out} ({len(template.encode('utf-8'))} bytes)")
    return out


if __name__ == "__main__":
    bundle_to_single_file()
