from pathlib import Path
import fnmatch

class IgnoreConfig:
    def __init__(self):
        self.rules: list[tuple[str, str]] = [] # (file_pattern, rule_pattern)

    def should_ignore(self, file_path: str, rule_name: str) -> bool:
        # Normalize paths
        file_path = file_path.replace("\\", "/")
        for file_pat, rule_pat in self.rules:
            if fnmatch.fnmatch(file_path, file_pat) or fnmatch.fnmatch(file_path.split("/")[-1], file_pat):
                if rule_pat == "*" or rule_pat == rule_name:
                    return True
        return False

def parse_ignore_file(repo_root: str) -> IgnoreConfig:
    config = IgnoreConfig()
    ignore_path = Path(repo_root) / ".prooflineignore"
    
    if not ignore_path.is_file():
        return config
        
    for line in ignore_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
            
        parts = line.split(":", 1)
        file_pat = parts[0].strip()
        rule_pat = parts[1].strip() if len(parts) > 1 else "*"
        
        # normalize path pattern
        file_pat = file_pat.replace("\\", "/")
        config.rules.append((file_pat, rule_pat))
        
    return config
