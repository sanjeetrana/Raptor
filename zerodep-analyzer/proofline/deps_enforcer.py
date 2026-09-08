from pathlib import Path
import sys

def ensure_zero_deps(repo_root: str = ".") -> None:
    """
    Enforces the zero-dependency hackathon rule natively.
    Reads requirements.txt and throws if third-party packages are present.
    """
    req_file = Path(repo_root) / "requirements.txt"
    if not req_file.is_file():
        return
        
    content = req_file.read_text(encoding="utf-8")
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
            
        # Ignore standard packaging tools
        if line.lower().startswith(("pip", "setuptools", "wheel")):
            continue
            
        # Found a third-party dependency
        print(f"\033[91m[ERROR] Zero-Dependency Violation Detected:\033[0m")
        print(f"Found external package in requirements.txt: {line}")
        print("Proofline is strict zero-dependency software.")
        sys.exit(1)
