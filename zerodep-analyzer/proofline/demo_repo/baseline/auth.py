"""
auth.py — Baseline authentication module.

This is the BEFORE state in the adversarial demo repo (§8).
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


def validate_token(token: str) -> int:
    """
    Validate an authentication token and return the user_id.

    Raises:
        ValueError: if the token is malformed or missing user_id.
        TokenExpiredError: if the token has expired.
    """
    payload = decode(token)
    if "user_id" not in payload:
        raise ValueError("Token payload missing user_id field")
    return payload["user_id"]


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
