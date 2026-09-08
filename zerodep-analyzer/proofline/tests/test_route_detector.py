"""
test_route_detector.py — Tests for route_detector.py

Key test: all route detections must be INFERRED, never PROVEN.
"""
import ast
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from proofline.symbol_map import (
    FunctionInfo, DecoratorInfo, Location, Confidence, extract_symbols
)
from proofline.route_detector import detect_routes_in_table, RouteInfo


class TestRouteDetector(unittest.TestCase):

    def _make_func(self, name: str, decorator_name: str) -> FunctionInfo:
        return FunctionInfo(
            name=name,
            qualified_name=f"module.{name}",
            decorators=[DecoratorInfo(
                name=decorator_name,
                location=Location(file="app.py", line=10),
            )],
            location=Location(file="app.py", line=11),
        )

    def test_flask_route_detected(self):
        source = (
            "from flask import Flask\n"
            "app = Flask(__name__)\n"
            "@app.route('/orders', methods=['GET'])\n"
            "def get_orders():\n"
            "    pass\n"
        )
        import tempfile, os
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write(source)
            fname = f.name
        try:
            table = extract_symbols(fname, source=source)
            routes = detect_routes_in_table(table, source=source)
            flask_routes = [r for r in routes if r.framework == "flask"]
            self.assertTrue(len(flask_routes) >= 1)
        finally:
            os.unlink(fname)

    def test_all_routes_are_inferred(self):
        """Hard rule: route detection is always INFERRED."""
        source = (
            "from flask import Flask\n"
            "app = Flask(__name__)\n"
            "@app.route('/test')\n"
            "def view():\n"
            "    pass\n"
        )
        import tempfile, os
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write(source)
            fname = f.name
        try:
            table = extract_symbols(fname, source=source)
            routes = detect_routes_in_table(table, source=source)
            for route in routes:
                self.assertEqual(
                    route.confidence, Confidence.INFERRED,
                    f"Route {route.function_name} has confidence {route.confidence.value} — must be INFERRED"
                )
        finally:
            os.unlink(fname)

    def test_fastapi_route_detected(self):
        source = (
            "from fastapi import APIRouter\n"
            "router = APIRouter()\n"
            "@router.get('/items/{id}')\n"
            "def get_item(id: int):\n"
            "    pass\n"
        )
        import tempfile, os
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write(source)
            fname = f.name
        try:
            table = extract_symbols(fname, source=source)
            routes = detect_routes_in_table(table, source=source)
            fastapi_routes = [r for r in routes if r.framework == "fastapi"]
            self.assertTrue(len(fastapi_routes) >= 1)
        finally:
            os.unlink(fname)

    def test_non_route_decorator_not_detected(self):
        source = (
            "@property\n"
            "def foo(self):\n"
            "    return self._foo\n"
        )
        import tempfile, os
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write(source)
            fname = f.name
        try:
            table = extract_symbols(fname, source=source)
            routes = detect_routes_in_table(table, source=source)
            self.assertEqual(len(routes), 0, "Property decorator should not be detected as route")
        finally:
            os.unlink(fname)

    def test_route_info_to_dict(self):
        route = RouteInfo(
            function_name="get_orders",
            framework="flask",
            http_methods=["GET"],
            path_pattern="/orders",
            confidence=Confidence.INFERRED,
            location=Location(file="app.py", line=5),
        )
        d = route.to_dict()
        self.assertEqual(d["framework"], "flask")
        self.assertEqual(d["confidence"], "INFERRED")
        self.assertEqual(d["path_pattern"], "/orders")


if __name__ == "__main__":
    unittest.main()
