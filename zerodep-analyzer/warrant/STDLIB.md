# Zero-Dependency Implementation

Warrant uses **zero third-party dependencies**. To prove it, here is how we replaced the 10 most common external dependencies with Python standard library equivalents.

| External Library | Warrant's Stdlib Solution | Why |
|------------------|---------------------------|-----|
| `networkx` | Raw `dict[str, set[str]]` and BFS | We only need simple directed edges for PageRank and blast radius traversals. `networkx` is overkill for graph basics. |
| `scipy` / `numpy` | `math` and list comprehensions | PageRank is implemented using a pure Python iterative sparse matrix solver (`pagerank.py`). |
| `pytest` | `unittest` | Python's built-in `unittest` handles all 80 of our tests seamlessly. |
| `scikit-learn` | Custom `BM25Index` | Scikit-learn's TF-IDF is large. We implemented a tuned BM25 index (`bm25.py`) using `collections.Counter` and `math.log`. |
| `pydantic` | `dataclasses` | We use `dataclasses` for structured types (`SymbolInfo`, `EvidenceBadge`, `Document`). |
| `click` / `typer` | `argparse` | Python's built-in `argparse` handles all our CLI subcommands (`search`, `impact`, `audit`, `index`). |
| `colorama` | Raw ANSI escape codes | We use a simple dictionary of ANSI codes for terminal colors, avoiding a cross-platform dependency. |
| `GitPython` | `subprocess` wrapping | We invoke `git log` and `git rev-parse` directly via `subprocess` for staleness checks (`git_utils.py`). |
| `tree-sitter` | `ast` | We use Python's built-in `ast` module to parse syntax trees and extract symbols, docstrings, and call graphs. |
| `PyYAML` | `json` | All persistent index data (`bm25.json`, `pagerank.json`, `badges.json`) is serialized using the built-in `json` module. |

*That's it. 10 substitutions. Real architecture, zero bloat.*
