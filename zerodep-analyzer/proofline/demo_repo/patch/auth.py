"""
auth.py — AI-generated patch to validate_token.

This is the AFTER state in the adversarial demo repo (§8).

The AI-generated change:
  1. Adds a broad `except Exception: return None` handler
  2. Changes the return behavior (was: raise ValueError / return int,
     now: returns int or None)
  3. Is auth-related (all rules 3, 4 fire)
  4. No new tests are added

This is the "killer demo" from PRD §9.
"""
import hashlib
import hmac


SECRET_KEY = "super-secret-key-change-in-production"


def decode(token: str) -> dict:
    """Decode a JWT-like token. Raises ValueError on invalid input."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError(f"Invalid token format: expected 3 parts, got {len(parts)}")
    import base64
    try:
        payload_bytes = base64.urlsafe_b64decode(parts[1] + "==")
        import json
        return json.loads(payload_bytes)
    except Exception as e:
        raise ValueError(f"Could not decode token payload: {e}") from e


def validate_token(token: str):
    """
    Validate an authentication token and return the user_id.

    AI-generated change: wrapped in broad exception handler.
    Now returns None on any error instead of raising.

    NOTE: This is the adversarial change Proofline is designed to catch.
    """
    try:
        return decode(token)["user_id"]
    except Exception:          # <-- broad exception handler added
        return None            # <-- return behavior changed: was raise, now None


def hash_password(password: str, salt: str) -> str:
    """Hash a password with a salt using PBKDF2-HMAC-SHA256."""
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations=100000,
    )
    return dk.hex()


def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    """Constant-time password verification."""
    actual = hash_password(password, salt)
    return hmac.compare_digest(actual, expected_hash)
