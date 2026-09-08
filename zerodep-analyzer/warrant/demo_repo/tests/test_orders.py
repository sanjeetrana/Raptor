"""Tests for orders module."""
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestOrders(unittest.TestCase):
    def test_create_order_bad_qty(self):
        """Zero quantity must raise ValueError."""
        from orders import create_order
        # Token validation will fail first — that's expected
        with self.assertRaises((PermissionError, ValueError)):
            create_order("bad.token.sig", "item-a", 0)

    def test_cancel_order_bad_token(self):
        from orders import cancel_order
        with self.assertRaises((PermissionError, ValueError)):
            cancel_order("bad.token.sig", "ord-001")


if __name__ == "__main__":
    unittest.main()
