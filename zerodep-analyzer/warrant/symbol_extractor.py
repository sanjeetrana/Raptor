"""
symbol_extractor.py — AST-based Python symbol extractor for Warrant.

Extracts functions and classes from a Python source file and returns
rich SymbolInfo objects suitable for indexing in BM25Index and for
building a call graph for PageRank.

Zero third-party dependencies.
"""
from __future__ import annotations

import ast
import dataclasses
import re
import hashlib
import copy
from pathlib import Path
from typing import Optional


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclasses.dataclass
class CallRef:
    """A function call found inside a symbol's body."""
    callee: str             # best-effort name: "validate_token", "self.foo", "jwt.decode"
    confidence: str         # PROVEN | INFERRED | UNKNOWN


@dataclasses.dataclass
class SymbolInfo:
    """Complete metadata for one function or method in a Python file."""
    # Identity
    name: str               # short name: "validate_token"
    qualified_name: str     # module.Class.method: "auth.validate_token"
    file_path: str          # relative to repo root
    line: int

    # Signature
    args: list[str]
    return_annotation: Optional[str]
    is_public: bool         # False if starts with _
    is_async: bool
    is_method: bool
    is_test: bool           # name starts with test_

    # Documentation
    docstring: Optional[str]

    # Callers / callees
    calls: list[CallRef] = dataclasses.field(default_factory=list)

    # Structural
    class_name: Optional[str] = None
    decorators: list[str] = dataclasses.field(default_factory=list)

    # Security / auth heuristics
    is_auth_related: bool = False
    has_broad_except: bool = False

    # AST hash (logic only, excluding docstring)
    ast_hash: str = ""

    def index_body(self) -> str:
        """
        Text body for BM25 indexing.
        Combines name, signature, and docstring — the richest signal for search.
        """
        # Boost name 3x: name match should outweigh a coincidental docstring term
        parts = [self.name, self.name, self.name, self.qualified_name]
        if self.args:
            parts.append(" ".join(self.args))
        if self.return_annotation:
            parts.append(self.return_annotation)
        if self.docstring:
            parts.append(self.docstring)
        if self.class_name:
            parts.append(self.class_name)
        return " ".join(parts)


# ── Auth heuristic ────────────────────────────────────────────────────────────

_AUTH_KEYWORDS = re.compile(
    r"(auth|login|logout|token|jwt|session|password|credential|permission|"
    r"role|admin|user|verify|validate|decode|encrypt|hash|secret|key|"
    r"oauth|saml|bearer|access|refresh|grant|scope|acl|rbac)",
    re.IGNORECASE,
)

def _is_auth_related(name: str, docstring: Optional[str]) -> bool:
    text = name + " " + (docstring or "")
    return bool(_AUTH_KEYWORDS.search(text))


# ── Call confidence ────────────────────────────────────────────────────────────

def _call_confidence(call_node: ast.expr) -> str:
    """
    Classify call confidence from AST:
      foo()           → PROVEN   (direct bare call)
      self.foo()      → INFERRED (method on self — needs class resolution)
      obj.foo()       → INFERRED (attribute call — needs type resolution)
      getattr(x, ...) → UNKNOWN  (dynamic dispatch)
    """
    if isinstance(call_node, ast.Name):
        return "PROVEN"
    if isinstance(call_node, ast.Attribute):
        if isinstance(call_node.value, ast.Name) and call_node.value.id == "self":
            return "INFERRED"
        return "INFERRED"
    return "UNKNOWN"


def _call_name(call_node: ast.expr) -> str:
    if isinstance(call_node, ast.Name):
        return call_node.id
    if isinstance(call_node, ast.Attribute):
        val = call_node.value
        if isinstance(val, ast.Name):
            return f"{val.id}.{call_node.attr}"
        return f"?.{call_node.attr}"
    return "?"


# ── Main extractor ────────────────────────────────────────────────────────────

def extract_symbols(
    file_path: Path,
    repo_root: Path,
    module_name: Optional[str] = None,
) -> list[SymbolInfo]:
    try:
        source = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    rel_path = str(file_path.relative_to(repo_root)).replace("\\", "/").replace("\\\\", "/")
    return extract_symbols_from_source(source, rel_path, module_name)

def extract_symbols_from_source(
    source: str,
    rel_path: str,
    module_name: Optional[str] = None,
) -> list[SymbolInfo]:
    try:
        tree = ast.parse(source, filename=rel_path)
    except SyntaxError:
        return []

    if module_name is None:
        parts = Path(rel_path).with_suffix("").parts
        module_name = ".".join(parts)

    local_aliases: dict[str, str] = {}
    for child in ast.iter_child_nodes(tree):
        if isinstance(child, ast.ClassDef):
            local_aliases[child.name] = f"{module_name}.{child.name}"

    for child in ast.walk(tree):
        if isinstance(child, ast.ImportFrom):
            mod = child.module or ""
            if child.level > 0:
                parts = module_name.split('.')
                base = ".".join(parts[:-child.level]) if child.level <= len(parts) else ""
                if base:
                    mod = f"{base}.{mod}" if mod else base
            for alias in child.names:
                name = alias.name
                asname = alias.asname or name
                local_aliases[asname] = f"{mod}.{name}" if mod else name
        elif isinstance(child, ast.Import):
            for alias in child.names:
                local_aliases[alias.asname or alias.name] = alias.name

    var_types: dict[str, str] = {}
    for child in ast.walk(tree):
        if isinstance(child, ast.Assign):
            if isinstance(child.value, ast.Call) and isinstance(child.value.func, ast.Name):
                class_name = child.value.func.id
                resolved_class = local_aliases.get(class_name, class_name)
                for target in child.targets:
                    if isinstance(target, ast.Name):
                        var_types[target.id] = resolved_class
                    elif isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self":
                        var_types[f"self.{target.attr}"] = resolved_class

    symbols: list[SymbolInfo] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self):
            self._class_stack: list[str] = []

        def visit_ClassDef(self, node: ast.ClassDef):
            self._class_stack.append(node.name)
            self.generic_visit(node)
            self._class_stack.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef):
            class_name = self._class_stack[-1] if self._class_stack else None

            # Qualified name
            if class_name:
                qname = f"{module_name}.{class_name}.{node.name}"
            else:
                qname = f"{module_name}.{node.name}"

            # Args
            args = [a.arg for a in node.args.args]
            if args and args[0] in ("self", "cls"):
                args = args[1:]

            # Return annotation
            ret = None
            if node.returns:
                try:
                    ret = ast.unparse(node.returns)
                except Exception:
                    ret = None

            # Docstring
            docstring = None
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                docstring = node.body[0].value.value.strip()

            # Decorators
            decorators = []
            for d in node.decorator_list:
                try:
                    decorators.append(ast.unparse(d))
                except Exception:
                    pass

            def _call_name_local(call_node: ast.expr) -> str:
                if isinstance(call_node, ast.Name):
                    return call_node.id
                if isinstance(call_node, ast.Attribute):
                    val = call_node.value
                    if isinstance(val, ast.Name):
                        var_name = val.id
                        if var_name == "self":
                            # It's self.method()
                            class_name = self._class_stack[-1] if self._class_stack else None
                            if class_name:
                                return f"{module_name}.{class_name}.{call_node.attr}"
                        if var_name in var_types:
                            return f"{var_types[var_name]}.{call_node.attr}"
                        if var_name in local_aliases:
                            return f"{local_aliases[var_name]}.{call_node.attr}"
                        return f"{var_name}.{call_node.attr}"
                    elif isinstance(val, ast.Attribute):
                        if isinstance(val.value, ast.Name) and val.value.id == "self":
                            attr_key = f"self.{val.attr}"
                            if attr_key in var_types:
                                return f"{var_types[attr_key]}.{call_node.attr}"
                    return f"?.{call_node.attr}"
                return "?"

            # Calls inside this function
            calls: list[CallRef] = []
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    conf = _call_confidence(child.func)
                    cname = _call_name_local(child.func)
                    # Detect getattr dynamic dispatch
                    if (isinstance(child.func, ast.Name)
                            and child.func.id == "getattr"):
                        conf = "UNKNOWN"
                        cname = "getattr(...)"
                    calls.append(CallRef(callee=cname, confidence=conf))

            # Broad except
            has_broad = False
            for child in ast.walk(node):
                if isinstance(child, ast.ExceptHandler):
                    if child.type is None:
                        has_broad = True  # bare except
                    elif (isinstance(child.type, ast.Name)
                          and child.type.id == "Exception"):
                        has_broad = True

            # Compute AST hash excluding docstring
            node_copy = copy.deepcopy(node)
            if (node_copy.body and isinstance(node_copy.body[0], ast.Expr)
                    and isinstance(node_copy.body[0].value, ast.Constant)
                    and isinstance(node_copy.body[0].value.value, str)):
                node_copy.body.pop(0)
            try:
                logic_source = ast.unparse(node_copy)
                ast_hash = hashlib.sha1(logic_source.encode("utf-8")).hexdigest()
            except Exception:
                ast_hash = ""

            sym = SymbolInfo(
                name=node.name,
                qualified_name=qname,
                file_path=rel_path,
                line=node.lineno,
                args=args,
                return_annotation=ret,
                is_public=not node.name.startswith("_"),
                is_async=isinstance(node, ast.AsyncFunctionDef),
                is_method=bool(class_name),
                is_test=node.name.startswith("test_"),
                docstring=docstring,
                calls=calls,
                class_name=class_name,
                decorators=decorators,
                is_auth_related=_is_auth_related(node.name, docstring),
                has_broad_except=has_broad,
                ast_hash=ast_hash,
            )
            symbols.append(sym)

            # Still descend into nested functions
            self.generic_visit(node)

        visit_AsyncFunctionDef = visit_FunctionDef

    Visitor().visit(tree)
    return symbols


def extract_repo(repo_root: Path) -> list[SymbolInfo]:
    """Walk all .py files under repo_root and extract symbols."""
    all_symbols: list[SymbolInfo] = []
    for py_file in sorted(repo_root.rglob("*.py")):
        # Skip __pycache__, hidden dirs
        if any(part.startswith(".") or part == "__pycache__"
               for part in py_file.parts):
            continue
        all_symbols.extend(extract_symbols(py_file, repo_root))
    return all_symbols
