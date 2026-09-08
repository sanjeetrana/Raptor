
import unittest
from src.storage import Storage

class TestStorage(unittest.TestCase):
    def test_insert(self):
        s = Storage()
        s.insert("id1", "data")
        self.assertIn("id1", s.db)
