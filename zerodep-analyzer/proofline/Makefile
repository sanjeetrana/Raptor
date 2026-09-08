# Proofline — Makefile
# Zero Dependency Hackathon submission
# All targets use Python stdlib only. No pip install required.
# Run from: c:\...\New folder\proofline\

PYTHON := python
MODULE := proofline
DEMO_BEFORE := demo_repo/baseline
DEMO_AFTER := demo_repo/patch
DEMO_FIXED := demo_repo/fixed
TESTS := tests

.PHONY: help run run2 test html serve json deps-proof stdlib-notes clean

help:
	@echo ""
	@echo "  Proofline — Change-centered Python code verification"
	@echo "  Zero Dependency Hackathon submission"
	@echo ""
	@echo "  Run these from: New folder\proofline\"
	@echo ""
	@echo "  Usage:"
	@echo "    make run          Run the killer demo (baseline → patch, Run 1)"
	@echo "    make run2         Run the risk-reduction demo (baseline → fixed, Run 2)"
	@echo "    make html         Generate HTML report → report.html"
	@echo "    make serve        Serve HTML report on localhost:8080"
	@echo "    make json         Output JSON report to stdout"
	@echo "    make test         Run stdlib unittest suite (79 tests)"
	@echo "    make deps-proof   Print zero-dependency proof"
	@echo "    make stdlib-notes Print STDLIB.md content"
	@echo ""

run:
	$(PYTHON) run.py analyze \
		--before $(DEMO_BEFORE) \
		--after $(DEMO_AFTER)

run2:
	$(PYTHON) run.py analyze \
		--before $(DEMO_BEFORE) \
		--after $(DEMO_FIXED)

html:
	$(PYTHON) run.py analyze \
		--before $(DEMO_BEFORE) \
		--after $(DEMO_AFTER) \
		--html report.html
	@echo "HTML report: report.html"

serve:
	$(PYTHON) run.py analyze \
		--before $(DEMO_BEFORE) \
		--after $(DEMO_AFTER) \
		--serve

json:
	$(PYTHON) run.py analyze \
		--before $(DEMO_BEFORE) \
		--after $(DEMO_AFTER) \
		--json

verbose:
	$(PYTHON) run.py analyze \
		--before $(DEMO_BEFORE) \
		--after $(DEMO_AFTER) \
		--verbose

test:
	$(PYTHON) -m unittest discover -s tests -v

deps-proof:
	@echo "# Zero-dependency proof"
	@echo "# pip list shows only pip/setuptools — no third-party runtime deps"
	$(PYTHON) -m pip list
	@echo ""
	@echo "# requirements.txt content:"
	@cat requirements.txt

stdlib-notes:
	$(PYTHON) run.py stdlib-notes

clean:
	find . -name "*.pyc" -delete
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	rm -f report.html report.json

