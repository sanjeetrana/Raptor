"""Tests for auth module."""
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from auth import validate_token, login, AuthService


class TestValidateToken(unittest.TestCase):
    def test_validate_token_malformed(self):
        """Malformed tokens must raise ValueError."""
        with self.assertRaises(ValueError):
            validate_token("bad-token")

    def test_validate_token_wrong_parts(self):
        with self.assertRaises(ValueError):
            validate_token("a.b")

    def test_login_valid(self):
        token = login("admin", "secret")
        self.assertIsInstance(token, str)
        self.assertEqual(token.count("."), 2)

    def test_login_invalid(self):
        with self.assertRaises(PermissionError):
            login("wrong", "creds")

    def test_auth_service_caches(self):
        svc = AuthService()
        # Invalid token — validate_token will raise for malformed
        with self.assertRaises(ValueError):
            svc.is_authenticated("bad")


if __name__ == "__main__":
    unittest.main()
