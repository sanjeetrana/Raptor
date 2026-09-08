"""
test_auth.py — Tests for auth.validate_token (baseline state).

These tests cover: valid token, missing user_id.
Note: test_malformed_token is intentionally MISSING in the baseline
(adversarial demo — the AI-generated patch adds a broad exception
handler but adds no new tests).
"""
import sys
import json
import base64
import unittest

# Add parent to path for import in demo context
sys.path.insert(0, "..")
from auth import validate_token, hash_password, verify_password


def _make_token(payload: dict) -> str:
    """Create a minimal fake JWT for testing."""
    header = base64.urlsafe_b64encode(b'{"alg":"HS256"}').rstrip(b"=").decode()
    body = base64.urlsafe_b64encode(
        json.dumps(payload).encode()
    ).rstrip(b"=").decode()
    return f"{header}.{body}.fakesig"


class TestValidateToken(unittest.TestCase):

    def test_validate_token_valid(self):
        """Valid token returns the correct user_id."""
        token = _make_token({"user_id": 42, "role": "admin"})
        result = validate_token(token)
        self.assertEqual(result, 42)

    def test_validate_token_missing_user_id(self):
        """Token without user_id raises ValueError."""
        token = _make_token({"role": "admin"})
        with self.assertRaises(ValueError):
            validate_token(token)

    # NOTE: test_validate_token_malformed is MISSING here.
    # The patch adds `except Exception: return None` which silently
    # handles this case — but no test covers it. This is the adversarial
    # scenario: behavior changes, but tests do not change.


class TestHashPassword(unittest.TestCase):

    def test_hash_is_deterministic(self):
        h1 = hash_password("secret", "salt123")
        h2 = hash_password("secret", "salt123")
        self.assertEqual(h1, h2)

    def test_different_passwords_produce_different_hashes(self):
        h1 = hash_password("secret1", "salt")
        h2 = hash_password("secret2", "salt")
        self.assertNotEqual(h1, h2)

    def test_verify_password_correct(self):
        h = hash_password("mypassword", "mysalt")
        self.assertTrue(verify_password("mypassword", "mysalt", h))

    def test_verify_password_wrong(self):
        h = hash_password("mypassword", "mysalt")
        self.assertFalse(verify_password("wrongpassword", "mysalt", h))


if __name__ == "__main__":
    unittest.main()
