# STDLIB.md: Zero Dependency Substitutions

To adhere strictly to the **Zero Dependency 2026** constraints while building an enterprise-grade static analysis verification gate, Proofline required completely eliminating third-party libraries. 

Here is the log of 11 significant substitutions made across the codebase to achieve a 100% standard library implementation.

### 1. `argparse` instead of `click` / `typer`
*   **Location:** `cli.py`
*   **Rationale:** We needed a complex multi-command CLI (e.g., `proofline analyze`, `proofline scan`). Instead of installing `click` or `typer` which bring thousands of lines of dependency footprint, we manually crafted standard `argparse._SubParsersAction` hooks and formatted the output using `argparse.RawDescriptionHelpFormatter`.

### 2. `ast` instead of `parso` / `libcst`
*   **Location:** `symbol_map.py`, `caller_graph.py`
*   **Rationale:** Parsing and traversing Python source code is typically outsourced to `libcst` or `parso` for robust round-trip capabilities. Since we only need read-only traversal to build the Symbol Map and Caller Graph, we relied purely on the built-in `ast.NodeVisitor`, saving millions of weekly third-party downloads.

### 3. `dataclasses` instead of `pydantic`
*   **Location:** `rules_engine.py`, `evidence_graph.py`, `symbol_map.py`
*   **Rationale:** Proofline passes around highly structured data (Rules, Reports, Locations). Instead of validating schemas with `pydantic`, we strictly type-hinted standard `dataclasses`.

### 4. `unittest` instead of `pytest`
*   **Location:** `tests/` directory (140+ tests)
*   **Rationale:** Modern Python testing defaults to `pytest` for fixtures and concise assertions. We restricted our 140-test adversarial test suite entirely to `unittest.TestCase`, proving you can have rigorous testing without importing a third-party framework.

### 5. `subprocess` instead of `GitPython`
*   **Location:** `git_utils.py`
*   **Rationale:** The `scan` and `install-hook` commands require deep Git repository introspection (finding diffs, resolving refs, parsing hashes). Instead of bundling `GitPython`, we carefully constructed shell-safe `subprocess.run` calls directly against the local `git` binary, capturing `stdout` and parsing it manually.

### 6. `http.server` instead of `flask` / `fastapi`
*   **Location:** `report.py` (`serve_report`)
*   **Rationale:** To allow users to visually browse the HTML impact graph locally via `--serve`, we needed a local HTTP daemon. Rather than pulling in `flask`, we spun up `http.server.SimpleHTTPRequestHandler` in a background thread, serving an auto-generated HTML payload directly from memory.

### 7. `json` instead of `ujson` / `orjson`
*   **Location:** `sarif_formatter.py`, `evidence_graph.py`
*   **Rationale:** Serializing the Evidence Graph and exporting GitHub-compatible SARIF files requires fast JSON encoding. We opted to stick to the stdlib `json` module, avoiding the compilation overhead of C-based serializers.

### 8. `re` instead of `python-dotenv`
*   **Location:** `env_parser.py`, `rules_engine.py`
*   **Rationale:** We allow users to inject configuration via `.env` files and suppress rules using inline `# proofline-disable: rule-X` comments. Rather than relying on `python-dotenv`, we built a lightweight regex-based lexer to safely extract key-value pairs and directives.

### 9. `html` instead of `Jinja2`
*   **Location:** `report.py`
*   **Rationale:** Generating the standalone Visual Dashboard required templating. Instead of bundling the massive `Jinja2` library, we leveraged vanilla Python f-strings and the `html.escape` module to safely inject sanitized dynamic data into our frontend template.

### 10. `pathlib` instead of external globbing libraries
*   **Location:** `diff_engine.py`
*   **Rationale:** Discovering changed files across deep directory trees was implemented completely using `pathlib.Path.rglob()`, which perfectly replicates external glob tools while remaining entirely within the standard library.

### 11. `hashlib` instead of `watchdog`
*   **Location:** `cli.py` (`_run_analyze_watch`)
*   **Rationale:** For our `--watch` live-reload feature, relying on `watchdog` or OS-level file event bindings would violate the zero-dep rule. Instead, we implemented a lightweight polling mechanism using `hashlib.sha256()` to checksum `st_mtime` stats on the file tree, triggering a re-analysis when the hash changes.
