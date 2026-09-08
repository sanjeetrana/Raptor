"""
symbol_map.py — Per-file symbol table extraction via stdlib ast.

Package Killer target: pyan3 (symbol/call extraction), ast-based parsing libs.
Stdlib used: ast, dataclasses, pathlib, enum

Every symbol extracted carries a source Location (file + line). No claim is
made without a source location attached.
"""
from __future__ import annotations

import hashlib
import pickle
import os
from pathlib import Path

_CACHE_DIR = Path(".proofline/cache")

def _get_cache_path(code: str, file_path: str) -> Path:
    code_hash = hashlib.sha256((file_path + "|" + code).encode("utf-8")).hexdigest()
    return _CACHE_DIR / f"{code_hash}.pkl"

import ast
import dataclasses
import enum
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Constants — Security-sensitive call pattern matching
# ---------------------------------------------------------------------------

# Bare names that flag a security-sensitive call site.
# These are pattern-matched against callee names (case-insensitive substring).
SECURITY_NAMES: frozenset[str] = frozenset({
    # subprocess / shell execution
    "subprocess", "popen", "system", "execv", "execve", "execl",
    # network
    "socket", "connect", "urlopen", "urlretrieve", "urlparse",
    "httpconnection", "httpsconnection",
    # filesystem destructive
    "remove", "unlink", "rmdir", "rmtree",
    # auth / secrets (name heuristic — always INFERRED confidence)
    "auth", "authenticate", "authorize", "login", "logout",
    "token", "password", "credential", "secret",
    "encrypt", "decrypt", "hash", "verify", "validate_token",
    "sign", "unsign",
})

AUTH_NAMES: frozenset[str] = frozenset({
    "auth", "authenticate", "authorize", "login", "logout",
    "token", "password", "credential", "secret", "verify", "validate",
    "sign", "unsign", "jwt", "oauth", "session",
})


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

class Confidence(enum.Enum):
    """
    Confidence labels for every relationship Proofline reports.

    PROVEN  — Direct, unambiguous static relationship resolvable at parse time.
    INFERRED — Likely relationship, not certain (class hierarchy, framework
               decorator, name heuristic).
    UNKNOWN — Cannot be statically resolved (getattr, dynamic import,
               reflection, dependency injection).
    """
    PROVEN = "PROVEN"
    INFERRED = "INFERRED"
    UNKNOWN = "UNKNOWN"

    def badge(self) -> str:
        """ANSI-colored badge for terminal output."""
        colors = {
            "PROVEN": "\033[32m",    # green
            "INFERRED": "\033[33m",  # yellow
            "UNKNOWN": "\033[37m",   # white/grey
        }
        reset = "\033[0m"
        return f"{colors[self.value]}[{self.value}]{reset}"

    def html_badge(self) -> str:
        css_class = self.value.lower()
        return f'<span class="badge badge-{css_class}">{self.value}</span>'


@dataclasses.dataclass(frozen=True)
class Location:
    """Source location — every claim has one."""
    file: str
    line: int
    col: int = 0

    def __str__(self) -> str:
        return f"{self.file}:{self.line}"

    def to_dict(self) -> dict:
        return {"file": self.file, "line": self.line, "col": self.col}


@dataclasses.dataclass
class ImportInfo:
    """One import statement extracted from a source file."""
    module: str                    # the module being imported
    name: Optional[str] = None     # specific name (from X import Y → Y)
    alias: Optional[str] = None    # as-alias
    location: Optional[Location] = None

    @property
    def qualified(self) -> str:
        if self.name:
            return f"{self.module}.{self.name}"
        return self.module


@dataclasses.dataclass
class CallInfo:
    """A function/method call site."""
    callee: str                        # best-effort qualified name
    is_method_call: bool = False       # True if receiver.method()
    receiver: Optional[str] = None     # "self", variable name, or None
    confidence: Confidence = Confidence.PROVEN
    location: Optional[Location] = None

    def is_dynamic(self) -> bool:
        return self.confidence == Confidence.UNKNOWN


@dataclasses.dataclass
class ExceptionHandlerInfo:
    """One except clause in a try block."""
    is_bare: bool = False             # bare except: (catches everything)
    is_broad: bool = False            # except Exception: (broad catch)
    exception_types: list[str] = dataclasses.field(default_factory=list)
    location: Optional[Location] = None

    def severity_label(self) -> str:
        if self.is_bare:
            return "BARE_EXCEPT"
        if self.is_broad:
            return "BROAD_EXCEPT"
        return "SPECIFIC_EXCEPT"


@dataclasses.dataclass
class DecoratorInfo:
    """A decorator applied to a function or class."""
    name: str             # full decorator expression as string
    location: Optional[Location] = None


@dataclasses.dataclass
class FunctionInfo:
    """Complete metadata for one function or method."""
    name: str
    qualified_name: str          # module.Class.method or module.function
    is_method: bool = False
    is_async: bool = False
    is_public: bool = True       # False if name starts with _
    is_test: bool = False        # name starts with test_
    class_name: Optional[str] = None
    decorators: list[DecoratorInfo] = dataclasses.field(default_factory=list)
    calls: list[CallInfo] = dataclasses.field(default_factory=list)
    exception_handlers: list[ExceptionHandlerInfo] = dataclasses.field(default_factory=list)
    args: list[str] = dataclasses.field(default_factory=list)
    return_annotation: Optional[str] = None
    docstring: Optional[str] = None
    location: Optional[Location] = None
    end_line: int = 0
    has_security_calls: bool = False
    is_auth_related: bool = False    # name heuristic
    is_fully_typed: bool = False
    complexity_score: int = 1

    def has_broad_exception(self) -> bool:
        return any(h.is_broad or h.is_bare for h in self.exception_handlers)


@dataclasses.dataclass
class ClassInfo:
    """Metadata for one class definition."""
    name: str
    qualified_name: str
    bases: list[str] = dataclasses.field(default_factory=list)
    method_names: list[str] = dataclasses.field(default_factory=list)
    location: Optional[Location] = None


@dataclasses.dataclass
class SymbolTable:
    """
    Complete symbol table for a single Python source file.

    This is the fundamental data unit Proofline passes between modules.
    """
    file_path: str
    module_name: str             # dot-separated, derived from path
    imports: list[ImportInfo] = dataclasses.field(default_factory=list)
    functions: dict[str, FunctionInfo] = dataclasses.field(default_factory=dict)
    classes: dict[str, ClassInfo] = dataclasses.field(default_factory=dict)
    is_test_file: bool = False
    parse_error: Optional[str] = None   # set if ast.parse failed

    def all_calls(self) -> list[tuple[str, CallInfo]]:
        """Yield (caller_qualified_name, CallInfo) pairs across all functions."""
        result = []
        for fname, finfo in self.functions.items():
            for call in finfo.calls:
                result.append((fname, call))
        return result

    def public_functions(self) -> dict[str, FunctionInfo]:
        return {k: v for k, v in self.functions.items() if v.is_public}

    def has_parse_error(self) -> bool:
        return self.parse_error is not None


# ---------------------------------------------------------------------------
# AST Visitor
# ---------------------------------------------------------------------------

def _decorator_to_str(node: ast.expr) -> str:
    """Convert a decorator AST node to a best-effort string representation."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_decorator_to_str(node.value)}.{node.attr}"
    if isinstance(node, ast.Call):
        return _decorator_to_str(node.func)
    return "<complex_decorator>"


def _annotation_to_str(node: Optional[ast.expr]) -> Optional[str]:
    """Stringify a type annotation node."""
    if node is None:
        return None
    try:
        return ast.unparse(node)
    except Exception:
        return "<annotation>"


def _call_to_str(node: ast.Call) -> tuple[str, bool, Optional[str]]:
    """
    Extract (callee_name, is_method_call, receiver) from a Call node.

    Returns:
        callee: best-effort string name
        is_method_call: True for obj.method() calls
        receiver: receiver variable name if method call
    """
    func = node.func
    if isinstance(func, ast.Name):
        return func.id, False, None
    if isinstance(func, ast.Attribute):
        if isinstance(func.value, ast.Name):
            return f"{func.value.id}.{func.attr}", True, func.value.id
        # Deeper chain: a.b.c() — use attribute as callee
        return func.attr, True, "<complex>"
    # Dynamic: getattr(obj, name)() or similar
    return "<dynamic>", False, None


def _is_security_call(callee: str) -> bool:
    lower = callee.lower()
    return any(pattern in lower for pattern in SECURITY_NAMES)


def _is_auth_related_name(name: str) -> bool:
    lower = name.lower()
    return any(pattern in lower for pattern in AUTH_NAMES)


class _SymbolVisitor(ast.NodeVisitor):
    """
    Single-pass AST visitor that populates a SymbolTable.

    Design note: We use a class_stack to track nested class context so
    methods are correctly attributed to their containing class.
    """

    def __init__(self, file_path: str, module_name: str):
        self._file = file_path
        self._module = module_name
        self._class_stack: list[str] = []
        self._function_stack: list[str] = []

        self.imports: list[ImportInfo] = []
        self.functions: dict[str, FunctionInfo] = {}
        self.classes: dict[str, ClassInfo] = {}

    def _loc(self, node: ast.AST) -> Location:
        return Location(
            file=self._file,
            line=getattr(node, "lineno", 0),
            col=getattr(node, "col_offset", 0),
        )

    def _qualified(self, name: str) -> str:
        parts = [self._module] + self._class_stack + [name]
        return ".".join(parts)

    # --- Imports ---

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports.append(ImportInfo(
                module=alias.name,
                alias=alias.asname,
                location=self._loc(node),
            ))
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        for alias in node.names:
            self.imports.append(ImportInfo(
                module=module,
                name=alias.name,
                alias=alias.asname,
                location=self._loc(node),
            ))
        self.generic_visit(node)

    # --- Classes ---

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        qname = self._qualified(node.name)
        bases = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                bases.append(base.id)
            elif isinstance(base, ast.Attribute):
                bases.append(f"{_decorator_to_str(base.value)}.{base.attr}")
            else:
                bases.append("<dynamic_base>")

        ci = ClassInfo(
            name=node.name,
            qualified_name=qname,
            bases=bases,
            location=self._loc(node),
        )
        self.classes[qname] = ci

        self._class_stack.append(node.name)
        self.generic_visit(node)
        self._class_stack.pop()

        # Populate method_names after visiting children
        for method_name in list(self.functions.keys()):
            # Methods in this class have qualified names prefixed with qname
            if method_name.startswith(qname + "."):
                ci.method_names.append(method_name)

    # --- Functions ---

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        qname = self._qualified(node.name)
        is_method = bool(self._class_stack)

        # Args (skip 'self'/'cls' for methods)
        raw_args = [a.arg for a in node.args.args]
        if is_method and raw_args and raw_args[0] in ("self", "cls"):
            args = raw_args[1:]
        else:
            args = raw_args
        # Also include posonlyargs, kwonlyargs
        args += [a.arg for a in node.args.posonlyargs]
        args += [a.arg for a in node.args.kwonlyargs]

        # Check type hint coverage
        all_args_annotated = True
        
        args_to_check = []
        if is_method and node.args.args and node.args.args[0].arg in ("self", "cls"):
            args_to_check.extend(node.args.args[1:])
        else:
            args_to_check.extend(node.args.args)
            
        args_to_check.extend(node.args.posonlyargs)
        args_to_check.extend(node.args.kwonlyargs)
        
        for a in args_to_check:
            if not getattr(a, "annotation", None):
                all_args_annotated = False
                break
                
        is_fully_typed = all_args_annotated and getattr(node, "returns", None) is not None

        # Calculate Cyclomatic Complexity
        complexity = 1
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.For, ast.While, ast.AsyncFor, ast.ExceptHandler, ast.comprehension)):
                complexity += 1
            elif isinstance(child, ast.BoolOp):
                complexity += len(child.values) - 1

        decorators = [
            DecoratorInfo(name=_decorator_to_str(d), location=self._loc(d))
            for d in node.decorator_list
        ]

        docstring = ast.get_docstring(node)
        fi = FunctionInfo(
            docstring=docstring,
            name=node.name,
            qualified_name=qname,
            is_method=is_method,
            is_async=isinstance(node, ast.AsyncFunctionDef),
            is_public=not node.name.startswith("_"),
            is_test=node.name.startswith("test_"),
            class_name=self._class_stack[-1] if self._class_stack else None,
            decorators=decorators,
            args=args,
            return_annotation=_annotation_to_str(node.returns),
            location=self._loc(node),
            end_line=getattr(node, "end_lineno", 0),
            is_auth_related=_is_auth_related_name(node.name),
            is_fully_typed=is_fully_typed,
            complexity_score=complexity,
        )

        # Visit body for calls and exception handlers
        self._function_stack.append(qname)
        _CallAndExceptVisitor(fi, self._file).visit(node)
        self._function_stack.pop()

        fi.has_security_calls = any(
            _is_security_call(c.callee) for c in fi.calls
        )

        self.functions[qname] = fi

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)
        # Do NOT call generic_visit — _CallAndExceptVisitor handles the body
        # But we still need to visit nested classes/functions
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                self.visit(child)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                self.visit(child)


class _CallAndExceptVisitor(ast.NodeVisitor):
    """
    Secondary visitor scoped to one function body.
    Extracts CallInfo and ExceptionHandlerInfo.
    """

    def __init__(self, func_info: FunctionInfo, file_path: str):
        self._fi = func_info
        self._file = file_path

    def _loc(self, node: ast.AST) -> Location:
        return Location(
            file=self._file,
            line=getattr(node, "lineno", 0),
            col=getattr(node, "col_offset", 0),
        )

    def visit_Call(self, node: ast.Call) -> None:
        callee, is_method, receiver = _call_to_str(node)

        if callee == "<dynamic>":
            confidence = Confidence.UNKNOWN
        elif is_method and receiver in ("self", "cls"):
            # self.foo() — requires class hierarchy resolution
            confidence = Confidence.INFERRED
        elif is_method:
            # obj.foo() where obj is a local variable
            confidence = Confidence.INFERRED
        else:
            # Direct bare call: foo()
            confidence = Confidence.PROVEN

        # getattr() calls are always UNKNOWN
        if callee in ("getattr", "setattr", "__import__"):
            confidence = Confidence.UNKNOWN

        ci = CallInfo(
            callee=callee,
            is_method_call=is_method,
            receiver=receiver,
            confidence=confidence,
            location=self._loc(node),
        )
        self._fi.calls.append(ci)
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        is_bare = node.type is None
        exception_types = []
        is_broad = False

        if node.type is not None:
            if isinstance(node.type, ast.Name):
                exception_types = [node.type.id]
                is_broad = node.type.id == "Exception"
            elif isinstance(node.type, ast.Tuple):
                exception_types = [
                    e.id if isinstance(e, ast.Name) else "<complex>"
                    for e in node.type.elts
                ]
                is_broad = "Exception" in exception_types
        else:
            is_bare = True

        ehi = ExceptionHandlerInfo(
            is_bare=is_bare,
            is_broad=is_broad,
            exception_types=exception_types,
            location=self._loc(node),
        )
        self._fi.exception_handlers.append(ehi)
        self.generic_visit(node)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _derive_module_name(file_path: str, root: Optional[str] = None) -> str:
    """Convert a file path to a dot-separated module name."""
    p = Path(file_path)
    if root:
        try:
            p = p.relative_to(root)
        except ValueError:
            pass
    parts = list(p.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else p.stem


def extract_symbols(file_path: str, source: Optional[str] = None,
                    root: Optional[str] = None) -> SymbolTable:
    """
    Parse a Python source file and return its complete SymbolTable.

    Args:
        file_path: Absolute or relative path to the .py file.
        source: Source code string (if already read). Reads file if None.
        root: Project root for module name derivation.

    Returns:
        SymbolTable with parse_error set if the file could not be parsed.
    """
    module_name = _derive_module_name(file_path, root)
    is_test = (
        Path(file_path).name.startswith("test_")
        or Path(file_path).name.endswith("_test.py")
    )

    if source is None:
        try:
            source = Path(file_path).read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return SymbolTable(
                file_path=file_path,
                module_name=module_name,
                is_test_file=is_test,
                parse_error=f"Could not read file: {e}",
            )

    if os.environ.get("PROOF_NO_CACHE") != "1":
        cache_path = _get_cache_path(source, file_path)
        if cache_path.is_file():
            try:
                with open(cache_path, "rb") as f:
                    return pickle.load(f)
            except Exception:
                pass

    try:
        tree = ast.parse(source, filename=file_path)
    except SyntaxError as e:
        return SymbolTable(
            file_path=file_path,
            module_name=module_name,
            is_test_file=is_test,
            parse_error=f"SyntaxError at line {e.lineno}: {e.msg}",
        )

    visitor = _SymbolVisitor(file_path=file_path, module_name=module_name)
    visitor.visit(tree)

    table = SymbolTable(
        file_path=file_path,
        module_name=module_name,
        imports=visitor.imports,
        functions=visitor.functions,
        classes=visitor.classes,
        is_test_file=is_test,
    )
    


    if os.environ.get("PROOF_NO_CACHE") != "1":
        cache_path = _get_cache_path(source, file_path)
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            with open(cache_path, "wb") as f:
                pickle.dump(table, f)
        except Exception:
            pass

    return table


def _parse_worker(args):
    py_file, root_dir = args
    return str(Path(py_file).relative_to(Path(root_dir))), extract_symbols(py_file, root=root_dir)

def extract_symbols_from_directory(
    root_dir: str,
    glob_pattern: str = "**/*.py",
) -> dict[str, SymbolTable]:
    """
    Walk a directory and extract SymbolTable for every Python file.
    Runs in parallel using ProcessPoolExecutor for massive performance gains.

    Returns:
        dict mapping relative path -> SymbolTable
    """
    root_path = Path(root_dir)
    
    if glob_pattern == "**/*.py":
        py_files = list(root_path.rglob("*.py"))
    else:
        py_files = list(root_path.glob(glob_pattern))
        
    args_list = [(str(p), root_dir) for p in py_files]
    results = {}

    import os
    if os.environ.get("PROOF_NO_PARALLEL") == "1":
        for args in args_list:
            rel_path, table = _parse_worker(args)
            results[rel_path] = table
        return results

    try:
        import concurrent.futures
        with concurrent.futures.ProcessPoolExecutor() as executor:
            for rel_path, table in executor.map(_parse_worker, args_list):
                results[rel_path] = table
    except Exception:
        # Graceful fallback to sequential on platforms without multiprocessing
        results = {}
        for args in args_list:
            rel_path, table = _parse_worker(args)
            results[rel_path] = table

    return results
