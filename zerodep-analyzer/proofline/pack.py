import os
import zipfile
from pathlib import Path

def create_zip():
    project_dir = Path(__file__).parent.resolve()
    zip_path = project_dir.parent / "proofline_source.zip"
    
    print(f"Creating zip file at: {zip_path}")
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(project_dir):
            # Skip caches and git
            if '__pycache__' in root or '.git' in root:
                continue
                
            for file in files:
                if file.endswith('.pyc') or file == 'pack.py':
                    continue
                    
                file_path = Path(root) / file
                arcname = file_path.relative_to(project_dir.parent)
                
                print(f"Adding: {arcname}")
                zipf.write(file_path, arcname)
                
    print(f"\nDone! The project has been zipped to: {zip_path}")
    print("You can extract this zip to view all source files, test files, and demo fixtures.")

if __name__ == "__main__":
    create_zip()
