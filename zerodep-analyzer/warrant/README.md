# Warrant

**A zero-dependency code search engine where every result carries proof of how trustworthy it is.**

> Grep tells you *where* a symbol is.  
> Warrant tells you *where* it is, *how central* it is to your system, and *whether you actually have evidence it's safe to touch*.

---

## The problem

Every code search tool ranks by text match.  
Every code analysis tool analyzes but doesn't search.  
Nobody combines "how important is this code, structurally" with "how much do we know about whether it's safe."

Warrant fills that gap. Every search result carries an evidence badge, and the score combines text relevance with PageRank centrality and test/caller evidence.

```
$ warrant search "token validation" --explain

  WARRANT  Search Results
  AI made code generation cheap. Warrant tells you what's safe to touch.

  Query: "token validation"
  --------------------------------------------------------

  1. [1.00] src.auth.validate_token  [PROVEN] PROVEN
     Score breakdown:
     +- Text match:   1.000 x 0.60 = 0.600  (name boosted 3x, BM25 relevance)
     +- Centrality:   1.000 x 0.20 = 0.200  (5 callers, PageRank blast radius)
     +- Evidence:     1.000 x 0.20 = 0.200  (PROVEN: 2 tests, 5 callers)
     = Total: 1.000
     src/auth.py:8

  2. [0.74] tests.test_auth.TestValidateToken.test_validate_token_wrong_parts  [INFERRED] INFERRED
     Score breakdown:
     +- Text match:   0.960 x 0.60 = 0.576  (name boosted 3x, BM25 relevance)
     +- Centrality:   0.167 x 0.20 = 0.033  (0 callers, PageRank blast radius)
     +- Evidence:     0.650 x 0.20 = 0.130  (INFERRED: 1 tests, 0 callers)
     = Total: 0.740
     tests/test_auth.py:16
```

---

## Powerful Analysis Tools

Beyond search, Warrant provides structural impact analysis:

```
$ warrant impact validate_token
```
Computes the blast radius of a symbol: direct callers, transitive callers, and whether any tests will catch regressions in the blast radius.

```
$ warrant audit
```
Whole-repo trust map: surfaces load-bearing code (many callers) that has zero test coverage.

---

## Architecture

```
BM25Index (text ranking)
    +
PageRank  (structural centrality via call graph)
    +
Evidence  (PROVEN / INFERRED / UNKNOWN + STALE orthogonal flag)
    =
Warrant blended score
```

All three engines are from-scratch Python stdlib implementations. **Zero third-party dependencies.**

---

## Quick Start

```bash
# Build the index for the repo
python run.py index path/to/repo

# Search it (shows explanation of scores)
python run.py search "token validation" --explain

# Show the blast radius of a function
python run.py impact validate_token

# Show whole-repo risk map
python run.py audit

# Run all tests
python run_tests.py
```

---

## Evidence Badges

Each symbol gets a confidence badge and an orthogonal staleness flag:

| Confidence | Meaning |
|-------|---------|
| 🟢 PROVEN | Direct callers found AND tests associated |
| 🟡 INFERRED | Tests OR callers, but not both (heuristic evidence) |
| 🔴 UNKNOWN | No evidence - isolated function or dynamic dispatch gaps |

| Flag | Meaning |
|-------|---------|
| 🟠 STALE | Symbol modified recently but tests weren't updated |

---

## Zero Dependency Proof

```
python -m pip list
```

All analysis uses pure Python standard libraries: `ast`, `re`, `math`, `json`, `collections`, `dataclasses`, `pathlib`, `argparse`, `sys`.
See [STDLIB.md](STDLIB.md) for the exact breakdown of how we avoided external dependencies.

---

## Limits

- Static analysis only - runtime behaviour not observed
- Test association = name/import heuristic, NOT runtime coverage
- Python only - no JS, Go, etc.
- Warrant never certifies "safe to merge"
