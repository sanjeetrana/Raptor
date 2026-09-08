import os
from pathlib import Path

def load_dotenv(filepath: str = ".env") -> bool:
    """Zero-dependency .env parser replacing python-dotenv."""
    path = Path(filepath)
    if not path.is_file():
        return False
        
    try:
        content = path.read_text(encoding="utf-8")
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
                
            # Split on first equals sign
            key, _, val = line.partition("=")
            if not _:
                continue
                
            key = key.strip()
            # Handle inline comments naïvely (assuming # means comment)
            val = val.split(" #")[0].strip()
            
            # Strip surrounding quotes if present
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
                val = val[1:-1]
                
            os.environ[key] = val
        return True
    except Exception:
        return False
