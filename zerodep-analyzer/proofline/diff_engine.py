"""
diff_engine.py — Directory-pair comparison and AST-level diffing.

Package Killer targets:
  - GitPython / dulwich: replaced by pathlib.Path.rglob + hashlib.sha256
  - difflib (stdlib) used instead of any external diff library

Stdlib used: ast, difflib, hashlib, pathlib, dataclasses

Design: walk two directory trees, fingerprint files with sha256, identify
changed/added/deleted .py files, then compare their SymbolTables to find
changed symbols. Every result carries a Location.
"""
from __future__ import annotations

import dataclasses
import difflib
import hashlib
from pathlib import Path
from typing import Optional

from .symbol_map import (
    SymbolTable,
    FunctionInfo,
    extract_symbols,
    extract_symbols_from_directory,
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class FileChange:
    """Records the before/after state of one changed file."""
    relative_path: str        # path relative to the root dir
    before_path: Optional[str] = None   # None if added
    after_path: Optional[str] = None    # None if deleted
    before_hash: Optional[str] = None
    after_hash: Optional[str] = None
    before_table: Optional[SymbolTable] = None
    after_table: Optional[SymbolTable] = None
    unified_diff: list[str] = dataclasses.field(default_factory=list)

    @property
    def is_added(self) -> bool:
        return self.before_path is None

    @property
    def is_deleted(self) -> bool:
        return self.after_path is None

    @property
    def is_modified(self) -> bool:
        return not self.is_added and not self.is_deleted


@dataclasses.dataclass
class SymbolDiff:
    """Records a single symbol-level change within a file."""
    file_change: FileChange
    symbol_name: str          # qualified name
    change_type: str          # "added" | "modified" | "deleted"
    before: Optional[FunctionInfo] = None
    after: Optional[FunctionInfo] = None

    # Semantic change flags
    signature_changed: bool = False
    exception_handling_changed: bool = False
    broad_exception_added: bool = False
    security_calls_changed: bool = False
    body_changed: bool = False         # non-signature line changes
    decorator_changed: bool = False
    docstring_changed: bool = False

    @property
    def relative_path(self) -> str:
        return self.file_change.relative_path


@dataclasses.dataclass
class DiffResult:
    """
    Complete result of comparing two directory trees.

    This is the primary output of diff_engine and the input to all
    downstream modules.
    """
    before_dir: str
    after_dir: str
    file_changes: list[FileChange] = dataclasses.field(default_factory=list)
    symbol_diffs: list[SymbolDiff] = dataclasses.field(default_factory=list)
    # All symbol tables from after-dir (for cross-file call graph building)
    after_tables: dict[str, SymbolTable] = dataclasses.field(default_factory=dict)
    before_tables: dict[str, SymbolTable] = dataclasses.field(default_factory=dict)

    @property
    def changed_files(self) -> list[FileChange]:
        return [fc for fc in self.file_changes if fc.is_modified]

    @property
    def added_files(self) -> list[FileChange]:
        return [fc for fc in self.file_changes if fc.is_added]

    @property
    def deleted_files(self) -> list[FileChange]:
        return [fc for fc in self.file_changes if fc.is_deleted]

    def changed_symbol_names(self) -> list[str]:
        return [sd.symbol_name for sd in self.symbol_diffs]


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------

def _hash_file(path: Path) -> str:
    """SHA-256 fingerprint of a file. Replaces file-watcher / inotify libs."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# Directory walking
# ---------------------------------------------------------------------------

def _index_directory(root: Path) -> dict[str, Path]:
    """
    Return {relative_posix_path: absolute_path} for all .py files under root.

    Replaces glob2 / pathspec / find-based file discovery.
    Stdlib: pathlib.Path.rglob (equivalent of recursive glob).
    """
    index: dict[str, Path] = {}
    for py_file in sorted(root.rglob("*.py")):
        rel = py_file.relative_to(root).as_posix()
        index[rel] = py_file
    return index


# ---------------------------------------------------------------------------
# Symbol-level diffing
# ---------------------------------------------------------------------------

def _args_signature(fi: FunctionInfo) -> tuple:
    """Canonical form of function signature for comparison."""
    return tuple(fi.args), fi.return_annotation


def _exception_signature(fi: FunctionInfo) -> list[tuple]:
    return [
        (h.is_bare, h.is_broad, tuple(sorted(h.exception_types)))
        for h in fi.exception_handlers
    ]


def _decorator_signature(fi: FunctionInfo) -> list[str]:
    return [d.name for d in fi.decorators]


def _diff_functions(
    file_change: FileChange,
    before_table: SymbolTable,
    after_table: SymbolTable,
) -> list[SymbolDiff]:
    """Compare function sets between two SymbolTables and emit SymbolDiffs."""
    diffs: list[SymbolDiff] = []

    before_fns = before_table.functions
    after_fns = after_table.functions

    # Strip module prefix for comparison — compare by local qualified name
    def _local(qname: str, module: str) -> str:
        if qname.startswith(module + "."):
            return qname[len(module) + 1:]
        return qname

    before_local = {
        _local(k, before_table.module_name): v
        for k, v in before_fns.items()
    }
    after_local = {
        _local(k, after_table.module_name): v
        for k, v in after_fns.items()
    }

    all_names = set(before_local) | set(after_local)

    for local_name in sorted(all_names):
        b_fn = before_local.get(local_name)
        a_fn = after_local.get(local_name)

        if b_fn is None and a_fn is not None:
            # Added symbol
            diffs.append(SymbolDiff(
                file_change=file_change,
                symbol_name=a_fn.qualified_name,
                change_type="added",
                after=a_fn,
            ))
        elif b_fn is not None and a_fn is None:
            # Deleted symbol
            diffs.append(SymbolDiff(
                file_change=file_change,
                symbol_name=b_fn.qualified_name,
                change_type="deleted",
                before=b_fn,
            ))
        else:
            # Both exist — check for modifications
            assert b_fn is not None and a_fn is not None

            sig_changed = _args_signature(b_fn) != _args_signature(a_fn)
            exc_before = _exception_signature(b_fn)
            exc_after = _exception_signature(a_fn)
            exc_changed = exc_before != exc_after
            broad_added = (
                not any(e[0] or e[1] for e in exc_before)
                and any(e[0] or e[1] for e in exc_after)
            )
            sec_changed = b_fn.has_security_calls != a_fn.has_security_calls
            dec_changed = _decorator_signature(b_fn) != _decorator_signature(a_fn)

            # Body change: compare source line ranges via unified_diff on the diff
            body_changed = (
                sig_changed or exc_changed or sec_changed
                or set(c.callee for c in b_fn.calls) != set(c.callee for c in a_fn.calls)
            )

            if any([sig_changed, exc_changed, sec_changed, dec_changed, body_changed]):
                diffs.append(SymbolDiff(
                    file_change=file_change,
                    symbol_name=a_fn.qualified_name,
                    change_type="modified",
                    before=b_fn,
                    after=a_fn,
                    signature_changed=sig_changed,
                    exception_handling_changed=exc_changed,
                    broad_exception_added=broad_added,
                    security_calls_changed=sec_changed,
                    body_changed=body_changed,
                    decorator_changed=dec_changed,
                    docstring_changed=(b_fn.docstring != a_fn.docstring),
                ))

    return diffs


# ---------------------------------------------------------------------------
# Unified diff generation
# ---------------------------------------------------------------------------

def _make_unified_diff(before_path: Path, after_path: Path) -> list[str]:
    """
    Generate a unified diff between two files.
    Stdlib: difflib.unified_diff (replaces any external diff library).
    """
    try:
        before_lines = before_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        after_lines = after_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    except OSError:
        return []

    return list(difflib.unified_diff(
        before_lines,
        after_lines,
        fromfile=str(before_path),
        tofile=str(after_path),
        n=3,
    ))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compare_directories(
    before_dir: str,
    after_dir: str,
) -> DiffResult:
    """
    Compare two directory trees and return a complete DiffResult.

    This is the main entrypoint for the diff engine. It:
    1. Walks both trees with pathlib.rglob (replaces glob2/find/GitPython)
    2. Fingerprints files with hashlib.sha256 to find changes
    3. Parses changed files with ast.parse (via symbol_map)
    4. Diffs SymbolTables to find changed symbols
    5. Generates unified diffs with difflib.unified_diff

    Args:
        before_dir: Path to the baseline directory.
        after_dir: Path to the patched directory.

    Returns:
        DiffResult with all file changes, symbol diffs, and symbol tables.
    """
    before_root = Path(before_dir)
    after_root = Path(after_dir)

    if not before_root.is_dir():
        raise NotADirectoryError(f"--before directory does not exist: {before_dir}")
    if not after_root.is_dir():
        raise NotADirectoryError(f"--after directory does not exist: {after_dir}")

    before_index = _index_directory(before_root)
    after_index = _index_directory(after_root)

    all_relative_paths = set(before_index) | set(after_index)

    # Build all symbol tables (we need after-tables for caller graph)
    before_tables: dict[str, SymbolTable] = {}
    after_tables: dict[str, SymbolTable] = {}

    for rel_path, abs_path in before_index.items():
        before_tables[rel_path] = extract_symbols(
            str(abs_path), root=str(before_root)
        )
    for rel_path, abs_path in after_index.items():
        after_tables[rel_path] = extract_symbols(
            str(abs_path), root=str(after_root)
        )

    result = DiffResult(
        before_dir=before_dir,
        after_dir=after_dir,
        before_tables=before_tables,
        after_tables=after_tables,
    )

    for rel_path in sorted(all_relative_paths):
        b_path = before_index.get(rel_path)
        a_path = after_index.get(rel_path)

        b_hash = _hash_file(b_path) if b_path else None
        a_hash = _hash_file(a_path) if a_path else None

        # Skip unchanged files
        if b_hash and a_hash and b_hash == a_hash:
            continue

        fc = FileChange(
            relative_path=rel_path,
            before_path=str(b_path) if b_path else None,
            after_path=str(a_path) if a_path else None,
            before_hash=b_hash,
            after_hash=a_hash,
            before_table=before_tables.get(rel_path),
            after_table=after_tables.get(rel_path),
        )

        # Generate unified diff for modified files
        if fc.is_modified and b_path and a_path:
            fc.unified_diff = _make_unified_diff(b_path, a_path)

        result.file_changes.append(fc)

        # Symbol-level diff for modified Python files
        if fc.is_modified and fc.before_table and fc.after_table:
            symbol_diffs = _diff_functions(fc, fc.before_table, fc.after_table)
            result.symbol_diffs.extend(symbol_diffs)
        elif fc.is_added and fc.after_table:
            for qname, fi in fc.after_table.functions.items():
                result.symbol_diffs.append(SymbolDiff(
                    file_change=fc,
                    symbol_name=qname,
                    change_type="added",
                    after=fi,
                ))
        elif fc.is_deleted and fc.before_table:
            for qname, fi in fc.before_table.functions.items():
                result.symbol_diffs.append(SymbolDiff(
                    file_change=fc,
                    symbol_name=qname,
                    change_type="deleted",
                    before=fi,
                ))

    return result
