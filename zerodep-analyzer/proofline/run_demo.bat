@echo off
echo ============================================================
echo Proofline Killer Demo (PRD 8)
echo Adversarial AI patch (auth.py) verification
echo ============================================================
echo.
echo Running: python run.py analyze --before demo_repo/baseline --after demo_repo/patch
echo.

python run.py analyze --before demo_repo/baseline --after demo_repo/patch

echo.
echo ============================================================
echo Notice how Proofline identified the vulnerability as HIGH severity:
echo   1. Signature changed
echo   2. Broad exception handler added
echo   3. Security boundary (auth) modified
echo   4. Inherited caller properly resolved as INFERRED
echo ============================================================
echo.
echo Now, running the fixed version (risk reduced to MEDIUM):
echo Running: python run.py analyze --before demo_repo/baseline --after demo_repo/fixed
echo.

python run.py analyze --before demo_repo/baseline --after demo_repo/fixed

echo.
echo ============================================================
echo Demo complete.
echo ============================================================

echo.
echo ========================================================
echo PRD 4.3 Feature Demonstrations
echo ========================================================
echo.
echo 1. Generating HTML report with SVG Blast Radius Heatmap...
python run.py analyze --before demo_repo/baseline --after demo_repo/patch --html report.html

echo.
echo 2. Scaffolding Tests for unverified changes...
python run.py scaffold-tests --before demo_repo/baseline --after demo_repo/patch
