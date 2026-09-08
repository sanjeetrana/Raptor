"""utils.py — General utility functions."""
import hashlib
import re


def hash_password(password: str) -> str:
    """Hash a password with SHA-256. Use bcrypt in production."""
    return hashlib.sha256(password.encode()).hexdigest()


def validate_email(email: str) -> bool:
    """
    Check that a string is a properly formatted email address.
    Uses a regex pattern matching the RFC 5322 simplified form.
    Does NOT perform DNS lookup or mailbox verification.
    Unrelated to authentication, tokens, or session management.
    """
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, email))


def slugify(text: str) -> str:
    """Convert text to URL-friendly slug."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def paginate(items: list, page: int, per_page: int = 20) -> dict:
    """Paginate a list and return page metadata."""
    start = (page - 1) * per_page
    end = start + per_page
    return {
        "items": items[start:end],
        "page": page,
        "per_page": per_page,
        "total": len(items),
        "pages": max(1, (len(items) + per_page - 1) // per_page),
    }
