import zipapp
import sys
from pathlib import Path

def create_archive():
    source_dir = Path(__file__).parent
    output_file = source_dir.parent / "warrant.pyz"
    
    import tempfile
    import shutil
    
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        for py_file in source_dir.rglob("*.py"):
            if "tests" in py_file.parts or "__pycache__" in py_file.parts or py_file.name in ("pack.py", "run_tests.py"):
                continue
            
            rel_path = py_file.relative_to(source_dir)
            dest = temp_path / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(py_file, dest)
            
        main_py = temp_path / "__main__.py"
        main_py.write_text("from cli import main\nif __name__ == '__main__':\n    main()\n", encoding="utf-8")
        
        zipapp.create_archive(temp_path, output_file, interpreter="/usr/bin/env python3")
        print(f"Created executable archive: {output_file}")
        
if __name__ == "__main__":
    create_archive()
