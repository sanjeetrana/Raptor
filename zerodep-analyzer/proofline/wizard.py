import os
from pathlib import Path
import sys

def run_init_wizard(repo_root: str = ".") -> None:
    """Interactive zero-dependency setup wizard for Proofline."""
    print("\033[96m" + "="*50 + "\033[0m")
    print("\033[1m\033[96m  Welcome to the Proofline Setup Wizard\033[0m")
    print("\033[96m" + "="*50 + "\033[0m\n")
    
    root = Path(repo_root)
    env_file = root / ".env"
    ignore_file = root / ".prooflineignore"
    
    # 1. Configure Port
    print("Proofline hosts a local server for reports.")
    port = input("What port should the server use? [default: 8080]: ").strip()
    if not port:
        port = "8080"
        
    # 2. Configure Color
    no_color = input("Disable ANSI colors in CLI? (y/N): ").strip().lower() == "y"
    
    # 3. Write .env
    env_content = f"PROOF_PORT={port}\n"
    if no_color:
        env_content += "PROOF_NO_COLOR=1\n"
        
    env_file.write_text(env_content, encoding="utf-8")
    print(f"\n\033[92m[+] Created {env_file.name}\033[0m")
    
    # 4. Configure ignores
    print("\nProofline can ignore specific directories or files.")
    ignore_tests = input("Ignore test files (*test*.py)? (y/N): ").strip().lower() == "y"
    ignore_venv = input("Ignore virtual environments (venv/, .env/)? (Y/n): ").strip().lower() != "n"
    
    ignore_lines = []
    if ignore_tests:
        ignore_lines.append("*test*.py")
        ignore_lines.append("tests/*")
    if ignore_venv:
        ignore_lines.append("venv/*")
        ignore_lines.append(".env/*")
        ignore_lines.append(".venv/*")
        
    if ignore_lines:
        ignore_file.write_text("\n".join(ignore_lines) + "\n", encoding="utf-8")
        print(f"\033[92m[+] Created {ignore_file.name}\033[0m")
    else:
        print(f"\033[90m[-] Skipped {ignore_file.name}\033[0m")
        
    print("\n\033[96mSetup complete! You can now run `proofline analyze`\033[0m")
