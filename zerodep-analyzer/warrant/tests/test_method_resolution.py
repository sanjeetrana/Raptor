import unittest
from pathlib import Path
from symbol_extractor import extract_symbols_from_source

class TestMethodResolution(unittest.TestCase):
    def check_call(self, source: str, expected_callee: str, module_name="src.module"):
        syms = extract_symbols_from_source(source, "src/module.py", module_name)
        func = next(s for s in syms if s.name == "do_something")
        calls = [c.callee for c in func.calls]
        self.assertIn(expected_callee, calls)

    def test_local_instantiation(self):
        source = '''class SearchEngine:
    def search(self): pass

def do_something():
    engine = SearchEngine()
    engine.search()
'''
        self.check_call(source, "src.module.SearchEngine.search")

    def test_module_level_instantiation(self):
        source = '''class SearchEngine:
    def search(self): pass

engine = SearchEngine()

class Handler:
    def do_something(self):
        engine.search()
'''
        self.check_call(source, "src.module.SearchEngine.search")

    def test_imported_class(self):
        source = '''from src.engine import SearchEngine

engine = SearchEngine()

def do_something():
    engine.search()
'''
        self.check_call(source, "src.engine.SearchEngine.search")

    def test_aliased_import(self):
        source = '''from src.engine import SearchEngine as SE

engine = SE()

def do_something():
    engine.search()
'''
        self.check_call(source, "src.engine.SearchEngine.search")

    def test_self_attribute_instantiation(self):
        source = '''from src.engine import SearchEngine

class Handler:
    def __init__(self):
        self.engine = SearchEngine()
        
    def do_something(self):
        self.engine.search()
'''
        self.check_call(source, "src.engine.SearchEngine.search")

if __name__ == "__main__":
    unittest.main()
