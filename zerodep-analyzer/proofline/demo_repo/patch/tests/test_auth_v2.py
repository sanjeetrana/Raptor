"""
test_auth_v2.py — RENAMED from test_auth.py in the patch.

ADVERSARIAL CASE (§8): The test file has been renamed from test_auth.py
to test_auth_v2.py. Proofline must:
  - NOT silently produce a wrong candidate count
  - Report the rename/deletion in its resilience check
  - Still associate these tests via import/name matching (from the new file name)
  - Emit a warning that test_auth.py was present in baseline but absent in patch

The tests themselves are UNCHANGED — behavior changed but tests did not.
This is what Rule 7 fires on.
"""
import sys
import json
import base64
import unittest

sys.path.insert(0, "..")
from auth import validate_token


def _make_token(payload: dict) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"HS256"}').rstrip(b"=").decode()
    body = base64.urlsafe_b64encode(
        json.dumps(payload).encode()
    ).rstrip(b"=").decode()
    return f"{header}.{body}.fakesig"


class TestValidateToken(unittest.TestCase):
    """Same tests as before — NOT updated to reflect the new None-return behavior."""

    def test_validate_token_valid(self):
        """Valid token returns the correct user_id."""
        token = _make_token({"user_id": 42})
        result = validate_token(token)
        self.assertEqual(result, 42)

    def test_validate_token_missing_user_id(self):
        """
        Token without user_id.

        Before patch: raises ValueError.
        After patch: returns None (silently!).
        This test is NOT updated — it will now pass for the wrong reason
        if it's checking for None instead of ValueError.
        """
        token = _make_token({"role": "admin"})
        # NOTE: after the patch, this returns None, not raises ValueError.
        # This test is unchanged — the behavior change is unverified.
        result = validate_token(token)
        # Old assertion (would have checked for ValueError)
        # Now just checking it "doesn't crash" — inadequate.
        self.assertIsNone(result)  # This "passes" but doesn't test the right thing


if __name__ == "__main__":
    unittest.main()
