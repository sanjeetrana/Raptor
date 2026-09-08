"""orders.py — Order processing with auth checks."""
from auth import validate_token, AuthService

_service = AuthService()


def create_order(token: str, item: str, qty: int) -> dict:
    """
    Create a new order. Validates token before processing.

    Args:
        token: User auth token
        item:  Product identifier
        qty:   Quantity to order

    Returns:
        Order dict with id, item, qty, status.
    """
    if not _service.is_authenticated(token):
        raise PermissionError("Not authenticated")
    if qty <= 0:
        raise ValueError("Quantity must be positive")
    return {"id": "ord-001", "item": item, "qty": qty, "status": "pending"}


def cancel_order(token: str, order_id: str) -> bool:
    """Cancel an existing order by ID. Requires valid auth token."""
    if not validate_token(token):
        raise PermissionError("Not authenticated")
    return True


def list_orders(token: str) -> list:
    """Return all orders for the authenticated user."""
    if not _service.is_authenticated(token):
        raise PermissionError("Not authenticated")
    return []


def _internal_helper(data: dict) -> dict:
    """Internal helper — not public API."""
    return {k: str(v) for k, v in data.items()}

def super_risky():
    pass
