"""
test_associator.py — Name/import-based candidate test matching.

HARD RULE (enforced in all output):
  Proofline never claims "this code is tested" or "this code is untested."
  It only ever says:
    - "no statically associated test found"
    - "N candidate tests found (name/import association only — not runtime coverage)"

  Association is NOT coverage. This module says so on every result it produces.

Package Killer: replaces test-discovery / coverage-mapping libraries.
Stdlib: pathlib, dataclasses
"""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Optional

from .symbol_map import SymbolTable, FunctionInfo, Confidence, Location
from .diff_engine import DiffResult, SymbolDiff


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class CandidateTest:
    """
    A test function that may be associated with a changed symbol.

    'Candidate' is the deliberate word — this is a static association,
    not a runtime coverage claim.
    """
    test_function_name: str       # qualified name of the test function
    test_file: str                # file containing the test
    association_method: str       # "name_match" | "import_match" | "both"
    confidence: Confidence = Confidence.INFERRED
    location: Optional[Location] = None
    changed_in_patch: bool = False   # True if the test file was also changed


@dataclasses.dataclass
class TestAssociation:
    """
    All candidate tests for a specific changed symbol.

    The disclaimer string is the canonical Proofline output — it is shown
    every time a count appears, not just in docs.
    """
    symbol_name: str
    candidates: list[CandidateTest] = dataclasses.field(default_factory=list)

    # Hard rule: always attach this disclaimer to any count display
    DISCLAIMER = "(name/import association only — not runtime coverage)"

    @property
    def count(self) -> int:
        return len(self.candidates)

    @property
    def has_candidates(self) -> bool:
        return bool(self.candidates)

    @property
    def any_changed(self) -> bool:
        return any(c.changed_in_patch for c in self.candidates)

    def count_str(self) -> str:
        """Always produces the canonical disclaimer-bearing count string."""
        if not self.candidates:
            return f"0 candidate tests found {self.DISCLAIMER}"
        return f"{self.count} candidate test(s) found {self.DISCLAIMER}"

    def changed_count_str(self) -> str:
        changed = sum(1 for c in self.candidates if c.changed_in_patch)
        return f"{changed} of {self.count} candidate test(s) changed {self.DISCLAIMER}"


# ---------------------------------------------------------------------------
# Name matching helpers
# ---------------------------------------------------------------------------

def _function_base_name(qualified: str) -> str:
    """Extract the bare function name from a qualified name."""
    return qualified.split(".")[-1]


def _test_names_for(func_name: str) -> list[str]:
    """
    Generate candidate test function names for a given function name.

    Convention: test_<func_name>, test_<func_name>_*, <func_name>_test
    """
    return [
        f"test_{func_name}",
        f"{func_name}_test",
    ]


def _name_matches(test_name: str, func_name: str) -> bool:
    """
    Check if a test function name is associated with func_name by naming convention.

    test_validate_token → validate_token  (exact prefix match)
    test_validate_token_expired → validate_token  (prefix with suffix)
    validate_token_test → validate_token  (suffix convention)
    """
    if not func_name:
        return False

    lower_test = test_name.lower()
    lower_func = func_name.lower()

    # test_<func_name> or test_<func_name>_*
    if lower_test == f"test_{lower_func}":
        return True
    if lower_test.startswith(f"test_{lower_func}_"):
        return True
    if lower_test.startswith(f"test_{lower_func}"):
        return True
    # <func_name>_test
    if lower_test == f"{lower_func}_test":
        return True

    return False



def _import_matches(test_table: SymbolTable, changed_table: SymbolTable) -> bool:
    """
    Check if a test file imports from the changed file's module.

    This is an import-level association — the test file references the
    module, but we cannot prove it exercises the specific changed function.
    """
    changed_module = changed_table.module_name
    for imp in test_table.imports:
        if imp.module == changed_module:
            return True
        # from changed_module import X
        if imp.module.startswith(changed_module):
            return True
        # from . import something (relative import in same package)
        if changed_module.endswith(imp.module) and imp.module:
            return True
    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def associate_tests(
    diff_result: DiffResult,
) -> dict[str, TestAssociation]:
    """
    For each changed symbol, find candidate tests by name and import association.

    Two-pass algorithm:
      Pass 1: Name match — test function name contains the changed function name
      Pass 2: Import match — test file imports the changed file's module

    Returns:
        dict mapping changed_symbol_qualified_name → TestAssociation
    """
    # Collect all test tables from after-state
    test_tables: list[SymbolTable] = [
        t for t in diff_result.after_tables.values()
        if t.is_test_file and not t.has_parse_error()
    ]
    # Also check before-state test tables (to detect renamed/deleted tests)
    before_test_tables: list[SymbolTable] = [
        t for t in diff_result.before_tables.values()
        if t.is_test_file and not t.has_parse_error()
    ]

    # Track which test files were changed in the patch
    changed_test_files: set[str] = set()
    for fc in diff_result.file_changes:
        if fc.after_table and fc.after_table.is_test_file:
            changed_test_files.add(fc.after_table.file_path)
        # Also note: deleted test files (before_table exists, after_table doesn't)
        if fc.is_deleted and fc.before_table and fc.before_table.is_test_file:
            changed_test_files.add(fc.before_table.file_path)

    # Track which files contain changed symbols
    changed_tables: dict[str, SymbolTable] = {}
    for sd in diff_result.symbol_diffs:
        table = diff_result.after_tables.get(sd.relative_path)
        if table:
            changed_tables[sd.symbol_name] = table

    associations: dict[str, TestAssociation] = {}

    for sym_diff in diff_result.symbol_diffs:
        sym_name = sym_diff.symbol_name
        func_name = _function_base_name(sym_name)

        # Get the module table for this symbol
        changed_table = changed_tables.get(sym_name)

        assoc = TestAssociation(symbol_name=sym_name)
        seen_test_fns: set[str] = set()

        for test_table in test_tables:
            name_match = False
            import_match = False

            # Pass 2: import match
            if changed_table:
                import_match = _import_matches(test_table, changed_table)

            # Pass 1: name match per test function
            for test_qname, test_fn in test_table.functions.items():
                if not test_fn.is_test:
                    continue
                if test_qname in seen_test_fns:
                    continue

                fn_name_match = _name_matches(test_fn.name, func_name)
                if fn_name_match:
                    name_match = True

                if fn_name_match or import_match:
                    method = []
                    if fn_name_match:
                        method.append("name_match")
                    if import_match:
                        method.append("import_match")

                    ct = CandidateTest(
                        test_function_name=test_qname,
                        test_file=test_table.file_path,
                        association_method="+".join(method),
                        confidence=Confidence.INFERRED,
                        location=test_fn.location,
                        changed_in_patch=test_table.file_path in changed_test_files,
                    )
                    assoc.candidates.append(ct)
                    seen_test_fns.add(test_qname)

            # If import matches but no name match found specific test, add a
            # module-level association for the test file itself
            if import_match and not name_match:
                # Add at most one per test file for module-level import match
                key = f"<module:{test_table.module_name}>"
                if key not in seen_test_fns:
                    # Find any test function in this file
                    for test_qname, test_fn in test_table.functions.items():
                        if test_fn.is_test and test_qname not in seen_test_fns:
                            ct = CandidateTest(
                                test_function_name=test_qname,
                                test_file=test_table.file_path,
                                association_method="import_match",
                                confidence=Confidence.INFERRED,
                                location=test_fn.location,
                                changed_in_patch=test_table.file_path in changed_test_files,
                            )
                            assoc.candidates.append(ct)
                            seen_test_fns.add(test_qname)
                    seen_test_fns.add(key)

        associations[sym_name] = assoc

    return associations


def check_test_resilience(
    diff_result: DiffResult,
) -> dict[str, list[str]]:
    """
    Check for tests that existed before but are absent/renamed after.

    This detects the "renamed test file" adversarial case from §8:
    if test_auth.py → test_auth_v2.py, the association count changes
    and we must not silently produce a wrong count.

    Returns:
        dict mapping symbol_name → list of "possibly renamed/deleted test" notes
    """
    warnings: dict[str, list[str]] = {}

    before_test_files = {
        Path(t.file_path).name
        for t in diff_result.before_tables.values()
        if t.is_test_file
    }
    after_test_files = {
        Path(t.file_path).name
        for t in diff_result.after_tables.values()
        if t.is_test_file
    }

    missing_test_files = before_test_files - after_test_files

    if missing_test_files:
        # Precision fix: Only warn on symbols whose specific tests were in the missing file
        for sym_diff in diff_result.symbol_diffs:
            # Find candidate tests from the 'before' state for this symbol
            candidates_in_missing = []
            fc = sym_diff.file_change
            if fc and fc.before_table:
                # We need all candidate tests for this symbol across the entire before-state.
                # The symbol's tests might be in any test file.
                for bt in diff_result.before_tables.values():
                    if bt.is_test_file and Path(bt.file_path).name in missing_test_files:
                        # Does this test file have a test for this symbol?
                        sym_name = sym_diff.symbol_name
                        local_name = sym_name.split(".")[-1]
                        for fn in bt.functions.values():
                            # Basic name match logic to see if this function tested our symbol
                            if fn.name.startswith(f"test_{local_name}"):
                                candidates_in_missing.append(Path(bt.file_path).name)
                                break
                                
            if candidates_in_missing:
                # Deduplicate
                candidates_in_missing = sorted(list(set(candidates_in_missing)))
                note = (
                    f"Test file(s) containing candidates for this symbol were deleted/renamed: "
                    f"{', '.join(candidates_in_missing)} "
                    f"(candidate test count may be lower than baseline)"
                )
                warnings.setdefault(sym_diff.symbol_name, []).append(note)

    return warnings
