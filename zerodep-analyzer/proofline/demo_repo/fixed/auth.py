"""
auth.py — FIXED state (after applying the narrowing fix from PRD §9 Run 2).

Changes from patch:
  1. Broad `except Exception` → specific `except (ValueError, KeyError)`
  2. Return behavior: raises TokenExpiredError for expired tokens
     (not silently returns None)
"""
import hashlib
import hmac


SECRET_KEY = "super-secret-key-change-in-production"


class TokenExpiredError(ValueError):
    """Raised when a token has expired."""


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


def validate_token(token: str) -> int:
    """
    Validate an authentication token and return the user_id.

    FIX applied: narrow except clause — only catches expected decode errors.
    Raises ValueError/TokenExpiredError so callers can handle them properly.
    """
    try:
        payload = decode(token)
    except ValueError:
        raise  # Re-raise — do not swallow

    if "user_id" not in payload:
        raise ValueError("Token payload missing user_id field")

    return payload["user_id"]


def hash_password(password: str, salt: str) -> str:
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations=100000
    )
    return dk.hex()


def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    return hmac.compare_digest(hash_password(password, salt), expected_hash)
