"""
route_detector.py — Framework route decorator pattern matching.

ALL detections are INFERRED, never PROVEN.

This module pattern-matches decorator names against known framework conventions.
It is explicitly NOT general Python analysis — it recognises one framework's
convention at a time. This is documented in STDLIB.md and README.md.

Supported frameworks (all INFERRED):
  - Flask: @app.route, @blueprint.route, @<name>.route
  - FastAPI: @router.get/post/put/delete/patch, @app.get/post/...

Package Killer: replaces lightweight route-extraction utilities that
some projects use (e.g. flask-route-analysis, fastapi inspection).

Stdlib: ast, dataclasses, re
"""
from __future__ import annotations

import ast
import dataclasses
import re
from typing import Optional

from .symbol_map import (
    SymbolTable,
    FunctionInfo,
    DecoratorInfo,
    Confidence,
    Location,
)
from .diff_engine import DiffResult, SymbolDiff


# ---------------------------------------------------------------------------
# Pattern definitions
# ---------------------------------------------------------------------------

# Regex patterns for route decorator detection.
# We match the decorator string (from _decorator_to_str) against these.
# All matches are INFERRED — pattern matching a convention, not AST proof.

_FLASK_PATTERNS: list[re.Pattern] = [
    re.compile(r"^(?:\w+\.)*route$"),          # @app.route, @bp.route
    re.compile(r"^(?:\w+\.)*add_url_rule$"),   # manual route registration
]

_FASTAPI_PATTERNS: list[re.Pattern] = [
    re.compile(r"^(?:\w+\.)*(?:get|post|put|delete|patch|options|head)$"),
    re.compile(r"^(?:\w+\.)*include_router$"),
]

# HTTP method extraction from decorator argument
_HTTP_METHODS = frozenset({"GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"})


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class RouteInfo:
    """
    A detected HTTP route.

    Confidence is always INFERRED — this is pattern matching a framework
    decorator convention, not a general proof from the language semantics.
    The CLI output always displays this label.
    """
    function_name: str          # qualified name
    framework: str              # "flask" | "fastapi" | "unknown"
    http_methods: list[str]     # ["GET", "POST"] or ["ANY"] if unresolved
    path_pattern: Optional[str] = None   # "/orders/{id}" or None
    confidence: Confidence = Confidence.INFERRED  # always INFERRED
    location: Optional[Location] = None
    decorator_text: str = ""    # raw decorator string for display

    def to_dict(self) -> dict:
        return {
            "function_name": self.function_name,
            "framework": self.framework,
            "http_methods": self.http_methods,
            "path_pattern": self.path_pattern,
            "confidence": self.confidence.value,
            "location": self.location.to_dict() if self.location else None,
            "decorator_text": self.decorator_text,
        }


# ---------------------------------------------------------------------------
# Decorator analysis helpers
# ---------------------------------------------------------------------------

def _extract_path_from_decorator(decorator_node: ast.expr) -> Optional[str]:
    """
    Try to extract the URL path string from a route decorator.

    @app.route("/orders") → "/orders"
    @router.get("/orders/{id}") → "/orders/{id}"
    Returns None if path is dynamic or unparseable.
    """
    if not isinstance(decorator_node, ast.Call):
        return None
    if not decorator_node.args:
        return None
    first_arg = decorator_node.args[0]
    if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
        return first_arg.value
    return None


def _extract_methods_from_decorator(decorator_node: ast.expr) -> list[str]:
    """
    Try to extract HTTP methods from a Flask @app.route(methods=[...]).
    FastAPI decorators encode the method in the decorator name itself.
    """
    if not isinstance(decorator_node, ast.Call):
        return []

    for kw in decorator_node.keywords:
        if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple)):
            methods = []
            for elt in kw.value.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    m = elt.value.upper()
                    if m in _HTTP_METHODS:
                        methods.append(m)
            return methods

    return []


def _decorator_name_only(decorator_node: ast.expr) -> str:
    """Get just the attribute/name portion of a decorator (not args)."""
    if isinstance(decorator_node, ast.Call):
        return _decorator_name_only(decorator_node.func)
    if isinstance(decorator_node, ast.Attribute):
        return decorator_node.attr
    if isinstance(decorator_node, ast.Name):
        return decorator_node.id
    return ""


def _decorator_full_str(decorator_node: ast.expr) -> str:
    """Full string representation of a decorator for display."""
    try:
        return ast.unparse(decorator_node)
    except Exception:
        return "<decorator>"


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def _detect_flask_route(
    decorator_text: str,
    decorator_node: ast.expr,
    func_info: FunctionInfo,
) -> Optional[RouteInfo]:
    """Check if a decorator is a Flask route. Returns RouteInfo or None."""
    for pattern in _FLASK_PATTERNS:
        # Strip the call suffix for matching
        base = decorator_text.split("(")[0]
        if pattern.match(base):
            path = _extract_path_from_decorator(decorator_node)
            methods = _extract_methods_from_decorator(decorator_node) or ["GET"]
            return RouteInfo(
                function_name=func_info.qualified_name,
                framework="flask",
                http_methods=methods,
                path_pattern=path,
                confidence=Confidence.INFERRED,
                location=func_info.location,
                decorator_text=decorator_text,
            )
    return None


def _detect_fastapi_route(
    decorator_text: str,
    decorator_node: ast.expr,
    func_info: FunctionInfo,
) -> Optional[RouteInfo]:
    """Check if a decorator is a FastAPI route. Returns RouteInfo or None."""
    base = decorator_text.split("(")[0]
    attr = base.split(".")[-1].lower() if "." in base else base.lower()

    if attr in {"get", "post", "put", "delete", "patch", "options", "head"}:
        # Verify the full pattern matches
        for pattern in _FASTAPI_PATTERNS:
            if pattern.match(base):
                path = _extract_path_from_decorator(decorator_node)
                return RouteInfo(
                    function_name=func_info.qualified_name,
                    framework="fastapi",
                    http_methods=[attr.upper()],
                    path_pattern=path,
                    confidence=Confidence.INFERRED,
                    location=func_info.location,
                    decorator_text=decorator_text,
                )

    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_routes_in_table(
    table: SymbolTable,
    source: Optional[str] = None,
) -> list[RouteInfo]:
    """
    Detect all route-decorated functions in a SymbolTable.

    Because DecoratorInfo only stores the name string (not the AST node),
    we re-parse the source to get the full decorator AST for path extraction.
    If source is not provided, we fall back to name-only matching.

    All results are INFERRED.
    """
    routes: list[RouteInfo] = []

    # Try to get AST for full path extraction
    decorator_nodes: dict[str, list[ast.expr]] = {}
    if source:
        try:
            tree = ast.parse(source, filename=table.file_path)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    decorator_nodes[node.name] = node.decorator_list
        except SyntaxError:
            pass

    for qname, func_info in table.functions.items():
        ast_decorators = decorator_nodes.get(func_info.name, [])

        for i, dec_info in enumerate(func_info.decorators):
            dec_text = dec_info.name
            ast_node = ast_decorators[i] if i < len(ast_decorators) else None

            # Try Flask
            if ast_node:
                route = _detect_flask_route(dec_text, ast_node, func_info)
                if route:
                    routes.append(route)
                    continue
                route = _detect_fastapi_route(dec_text, ast_node, func_info)
                if route:
                    routes.append(route)
                    continue
            else:
                # Name-only fallback
                base = dec_text.split("(")[0]
                last = base.split(".")[-1].lower()
                if last == "route":
                    routes.append(RouteInfo(
                        function_name=qname,
                        framework="flask",
                        http_methods=["GET"],
                        confidence=Confidence.INFERRED,
                        location=func_info.location,
                        decorator_text=dec_text,
                    ))
                elif last in {"get", "post", "put", "delete", "patch"}:
                    routes.append(RouteInfo(
                        function_name=qname,
                        framework="fastapi",
                        http_methods=[last.upper()],
                        confidence=Confidence.INFERRED,
                        location=func_info.location,
                        decorator_text=dec_text,
                    ))

    return routes


def detect_affected_routes(
    diff_result: DiffResult,
) -> list[RouteInfo]:
    """
    Find routes in the after-state that are affected by the change.

    A route is "affected" if:
      1. The route's function itself was changed, OR
      2. The route's function calls a changed symbol.

    All route detections are INFERRED — framework decorator pattern matching.
    """
    changed_names = set(diff_result.changed_symbol_names())
    changed_local_names = {n.split(".")[-1] for n in changed_names}

    affected: list[RouteInfo] = []
    seen: set[str] = set()

    for rel_path, table in diff_result.after_tables.items():
        # Read source for full AST path extraction
        source = None
        if table.file_path:
            try:
                from pathlib import Path
                source = Path(table.file_path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass

        routes = detect_routes_in_table(table, source=source)

        for route in routes:
            fn_name = route.function_name
            fn_local = fn_name.split(".")[-1]

            # Is the route function itself changed?
            is_directly_changed = (
                fn_name in changed_names or fn_local in changed_local_names
            )

            # Does the route function call a changed symbol?
            calls_changed = False
            fn_info = table.functions.get(fn_name)
            if fn_info:
                for call in fn_info.calls:
                    call_local = call.callee.split(".")[-1]
                    if call.callee in changed_names or call_local in changed_local_names:
                        calls_changed = True
                        break

            if is_directly_changed or calls_changed:
                key = f"{fn_name}:{route.path_pattern}"
                if key not in seen:
                    seen.add(key)
                    affected.append(route)

    return affected
