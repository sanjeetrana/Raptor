
import unittest
from src.engine import SearchEngine, index_page

class TestEngine(unittest.TestCase):
    def test_search(self):
        engine = SearchEngine()
        res = engine.search("hello")
        self.assertEqual(res, [])
        
    def test_index_page(self):
        index_page("http://example.com", "content")
