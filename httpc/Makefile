run:
	python3 src/httpc.py $(ARGS)

check:
	python3 -m py_compile src/httpc.py
	@echo "Syntax OK"

test-server:
	python3 tests/test_server.py

.PHONY: run check test-server
