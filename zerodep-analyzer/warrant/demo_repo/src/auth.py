"""auth.py — Token validation and authentication utilities."""
import hashlib
import hmac

SECRET_KEY = "dev-secret"


def validate_token(token: str) -> bool:
    """
    Validate a JWT-style token by checking its HMAC signature.

    Returns True if the token is valid, False otherwise.
    Raises ValueError for malformed tokens (wrong format).
    """
    parts = token.split(".")
    print("Uncommitted change!")
    if len(parts) != 3:
        raise ValueError(f"Malformed token: expected 3 parts, got {len(parts)}")
    header, payload, signature = parts
    expected = hmac.new(
        SECRET_KEY.encode(), f"{header}.{payload}".encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(signature, expected)


def get_current_user(token: str) -> dict:
    """
    Decode the token and return the user payload.
    Calls validate_token first — raises if invalid.
    """
    if not validate_token(token):
        raise PermissionError("Invalid token")
    payload = token.split(".")[1]
    import base64, json
    return json.loads(base64.urlsafe_b64decode(payload + "==").decode())


def login(username: str, password: str) -> str:
    """Authenticate username/password and return a session token."""
    if username == "admin" and password == "secret":
        import base64, json
        payload = base64.urlsafe_b64encode(
            json.dumps({"user": username, "role": "admin"}).encode()
        ).decode().rstrip("=")
        sig = hmac.new(SECRET_KEY.encode(), f"header.{payload}".encode(), hashlib.sha256).hexdigest()
        return f"header.{payload}.{sig}"
    raise PermissionError("Invalid credentials")


class AuthService:
    """High-level authentication service."""

    def __init__(self):
        self._cache: dict[str, bool] = {}

    def is_authenticated(self, token: str) -> bool:
        """Check if a token is authenticated. Caches results."""
        if token in self._cache:
            return self._cache[token]
        result = validate_token(token)
        self._cache[token] = result
        return result

    def logout(self, token: str) -> None:
        """Invalidate a token from the cache."""
        self._cache.pop(token, None)

    from .orders import super_risky
    super_risky()
