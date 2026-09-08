"""
test_symbol_map.py — Tests for symbol_map.py

Stdlib: unittest
"""
import ast
import sys
import unittest
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from proofline.symbol_map import (
    extract_symbols,
    Confidence,
    FunctionInfo,
    ClassInfo,
    ImportInfo,
)


class TestExtractSymbols(unittest.TestCase):

    def _extract(self, source: str, filename: str = "test_file.py") -> object:
        """Helper: extract symbols from a source string."""
        import tempfile, os
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write(source)
            fname = f.name
        try:
            return extract_symbols(fname, source=source)
        finally:
            os.unlink(fname)

    def test_extracts_simple_function(self):
        source = "def foo():\n    pass\n"
        table = self._extract(source)
        self.assertFalse(table.has_parse_error())
        fn_names = [fn.name for fn in table.functions.values()]
        self.assertIn("foo", fn_names)

    def test_public_private_distinction(self):
        source = "def public_fn():\n    pass\ndef _private_fn():\n    pass\n"
        table = self._extract(source)
        fns = {fn.name: fn for fn in table.functions.values()}
        self.assertTrue(fns["public_fn"].is_public)
        self.assertFalse(fns["_private_fn"].is_public)

    def test_detects_broad_exception(self):
        source = (
            "def risky():\n"
            "    try:\n"
            "        x = 1\n"
            "    except Exception:\n"
            "        pass\n"
        )
        table = self._extract(source)
        fns = {fn.name: fn for fn in table.functions.values()}
        self.assertIn("risky", fns)
        self.assertTrue(fns["risky"].has_broad_exception())

    def test_detects_bare_except(self):
        source = (
            "def bare():\n"
            "    try:\n"
            "        x = 1\n"
            "    except:\n"
            "        pass\n"
        )
        table = self._extract(source)
        fns = {fn.name: fn for fn in table.functions.values()}
        self.assertIn("bare", fns)
        handlers = fns["bare"].exception_handlers
        self.assertTrue(any(h.is_bare for h in handlers))

    def test_extracts_class_and_methods(self):
        source = (
            "class Foo:\n"
            "    def bar(self):\n"
            "        pass\n"
            "    def baz(self, x: int):\n"
            "        pass\n"
        )
        table = self._extract(source)
        class_names = [c.name for c in table.classes.values()]
        self.assertIn("Foo", class_names)
        fn_names = [fn.name for fn in table.functions.values()]
        self.assertIn("bar", fn_names)
        self.assertIn("baz", fn_names)

    def test_extracts_imports(self):
        source = (
            "import os\n"
            "from pathlib import Path\n"
        )
        table = self._extract(source)
        modules = [i.module for i in table.imports]
        self.assertIn("os", modules)
        self.assertIn("pathlib", modules)

    def test_extracts_decorators(self):
        source = (
            "def route(*a, **kw):\n"
            "    def decorator(f): return f\n"
            "    return decorator\n"
            "app = type('App', (), {'route': route})()\n"
            "@app.route('/test')\n"
            "def view():\n"
            "    pass\n"
        )
        table = self._extract(source)
        fns = {fn.name: fn for fn in table.functions.values()}
        self.assertIn("view", fns)
        dec_names = [d.name for d in fns["view"].decorators]
        self.assertTrue(any("route" in d for d in dec_names))

    def test_detects_test_function(self):
        source = "def test_something():\n    pass\n"
        table = self._extract(source)
        fns = {fn.name: fn for fn in table.functions.values()}
        self.assertIn("test_something", fns)
        self.assertTrue(fns["test_something"].is_test)

    def test_detects_auth_related_name(self):
        source = "def validate_token(t):\n    pass\n"
        table = self._extract(source)
        fns = {fn.name: fn for fn in table.functions.values()}
        self.assertTrue(fns["validate_token"].is_auth_related)

    def test_parse_error_handled_gracefully(self):
        source = "def broken(:\n    pass\n"
        table = self._extract(source)
        self.assertTrue(table.has_parse_error())
        self.assertIsNotNone(table.parse_error)

    def test_call_confidence_bare_call(self):
        """Direct bare call foo() should be PROVEN."""
        source = "def a():\n    pass\ndef b():\n    a()\n"
        table = self._extract(source)
        fns = {fn.name: fn for fn in table.functions.values()}
        calls = fns["b"].calls
        bare_calls = [c for c in calls if c.callee == "a"]
        self.assertTrue(any(c.confidence == Confidence.PROVEN for c in bare_calls))

    def test_call_confidence_self_method(self):
        """self.foo() call should be INFERRED."""
        source = (
            "class C:\n"
            "    def foo(self):\n"
            "        pass\n"
            "    def bar(self):\n"
            "        self.foo()\n"
        )
        table = self._extract(source)
        fns = {fn.name: fn for fn in table.functions.values()}
        calls = fns["bar"].calls
        self.assertTrue(any(c.confidence == Confidence.INFERRED for c in calls))

    def test_call_confidence_getattr_unknown(self):
        """getattr(obj, name)() should be UNKNOWN."""
        source = (
            "def dynamic(obj, name):\n"
            "    getattr(obj, name)()\n"
        )
        table = self._extract(source)
        fns = {fn.name: fn for fn in table.functions.values()}
        calls = fns["dynamic"].calls
        self.assertTrue(any(c.confidence == Confidence.UNKNOWN for c in calls))

    def test_class_inheritance_extracted(self):
        source = (
            "class Base:\n"
            "    pass\n"
            "class Child(Base):\n"
            "    pass\n"
        )
        table = self._extract(source)
        classes = {c.name: c for c in table.classes.values()}
        self.assertIn("Base", classes["Child"].bases)

    def test_is_test_file_detection(self):
        import tempfile, os
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", prefix="test_", delete=False
        ) as f:
            f.write("def test_foo(): pass\n")
            fname = f.name
        try:
            table = extract_symbols(fname)
            self.assertTrue(table.is_test_file)
        finally:
            os.unlink(fname)


if __name__ == "__main__":
    unittest.main()
