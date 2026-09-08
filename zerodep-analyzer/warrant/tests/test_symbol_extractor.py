"""Tests for AST symbol extractor."""
import sys, textwrap, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import unittest
from symbol_extractor import extract_symbols, extract_repo


def _write(content: str, tmp: Path, name: str = "test_mod.py") -> Path:
    p = tmp / name
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


class TestExtractSymbols(unittest.TestCase):
    def test_simple_function(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            f = _write("""
                def hello(name: str) -> str:
                    return f"Hello, {name}"
            """, tmp)
            syms = extract_symbols(f, tmp)
        self.assertEqual(len(syms), 1)
        s = syms[0]
        self.assertEqual(s.name, "hello")
        self.assertEqual(s.args, ["name"])
        self.assertEqual(s.return_annotation, "str")
        self.assertTrue(s.is_public)

    def test_private_function(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            f = _write("def _helper(): pass", tmp)
            syms = extract_symbols(f, tmp)
        self.assertFalse(syms[0].is_public)

    def test_test_function_detected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            f = _write("def test_validate_token(): pass", tmp)
            syms = extract_symbols(f, tmp)
        self.assertTrue(syms[0].is_test)

    def test_docstring_extracted(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            f = _write("""
                def greet():
                    \'\'\'Say hello to the world.\'\'\'
                    pass
            """, tmp)
            syms = extract_symbols(f, tmp)
        self.assertIsNotNone(syms[0].docstring)
        self.assertIn("hello", syms[0].docstring)

    def test_method_in_class(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            f = _write("""
                class Auth:
                    def validate(self, token: str) -> bool:
                        return True
            """, tmp)
            syms = extract_symbols(f, tmp)
        self.assertEqual(syms[0].class_name, "Auth")
        self.assertEqual(syms[0].args, ["token"])   # self stripped
        self.assertTrue(syms[0].is_method)

    def test_broad_except_detected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            f = _write("""
                def risky():
                    try:
                        pass
                    except Exception:
                        pass
            """, tmp)
            syms = extract_symbols(f, tmp)
        self.assertTrue(syms[0].has_broad_except)

    def test_auth_related_heuristic(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            f = _write("def validate_token(t): pass", tmp)
            syms = extract_symbols(f, tmp)
        self.assertTrue(syms[0].is_auth_related)

    def test_non_auth_function(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            f = _write("def slugify(text: str) -> str: return text", tmp)
            syms = extract_symbols(f, tmp)
        self.assertFalse(syms[0].is_auth_related)

    def test_async_function(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            f = _write("async def fetch(url: str): pass", tmp)
            syms = extract_symbols(f, tmp)
        self.assertTrue(syms[0].is_async)

    def test_syntax_error_handled(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            f = _write("def bad_syntax(:", tmp)
            syms = extract_symbols(f, tmp)
        self.assertEqual(syms, [])

    def test_call_confidence_bare(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            f = _write("""
                def caller():
                    validate_token("x")
            """, tmp)
            syms = extract_symbols(f, tmp)
        calls = syms[0].calls
        proven = [c for c in calls if c.confidence == "PROVEN" and c.callee == "validate_token"]
        self.assertTrue(len(proven) > 0)

    def test_call_confidence_self(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            f = _write("""
                class X:
                    def caller(self):
                        self.helper()
            """, tmp)
            syms = extract_symbols(f, tmp)
        calls = syms[0].calls
        inferred = [c for c in calls if c.confidence == "INFERRED"]
        self.assertTrue(len(inferred) > 0)

    def test_getattr_is_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            f = _write("""
                def dispatcher(obj, name):
                    getattr(obj, name)()
            """, tmp)
            syms = extract_symbols(f, tmp)
        calls = syms[0].calls
        unknown = [c for c in calls if c.confidence == "UNKNOWN"]
        self.assertTrue(len(unknown) > 0)

    def test_index_body_contains_name(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            f = _write("""
                def validate_token(token: str) -> bool:
                    \'\'\'Check token signature.\'\'\'
                    return True
            """, tmp)
            syms = extract_symbols(f, tmp)
        body = syms[0].index_body()
        self.assertIn("validate", body)
        self.assertIn("token", body)

    def test_extract_repo(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "mod_a.py").write_text("def foo(): pass", encoding="utf-8")
            (tmp / "mod_b.py").write_text("def bar(): pass", encoding="utf-8")
            syms = extract_repo(tmp)
        names = [s.name for s in syms]
        self.assertIn("foo", names)
        self.assertIn("bar", names)


if __name__ == "__main__":
    unittest.main()
