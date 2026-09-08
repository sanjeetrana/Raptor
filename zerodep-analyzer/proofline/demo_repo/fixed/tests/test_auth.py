"""test_auth.py — Fixed state with new tests for the narrow exception fix."""
import sys
import json
import base64
import unittest

sys.path.insert(0, "..")
from auth import validate_token


def _make_token(payload: dict) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"HS256"}').rstrip(b"=").decode()
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"{header}.{body}.fakesig"


class TestValidateToken(unittest.TestCase):

    def test_validate_token_valid(self):
        token = _make_token({"user_id": 42})
        self.assertEqual(validate_token(token), 42)

    def test_validate_token_missing_user_id(self):
        token = _make_token({"role": "admin"})
        with self.assertRaises(ValueError):
            validate_token(token)

    def test_validate_token_malformed(self):
        """NEW: Test malformed token raises ValueError (not silently returns None)."""
        with self.assertRaises(ValueError):
            validate_token("not.a.valid.token")

    def test_validate_token_empty(self):
        """NEW: Empty token raises ValueError."""
        with self.assertRaises(ValueError):
            validate_token("")


if __name__ == "__main__":
    unittest.main()
