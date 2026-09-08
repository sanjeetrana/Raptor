"""
services.py — Patch state (OrderService.verify now calls self.validate_token).

This creates the INFERRED inheritance edge adversarial case from §8:
OrderService inherits from AuthService which wraps the changed validate_token.
The call self.validate_token(token) requires class-hierarchy resolution
to determine it reaches auth.validate_token — correctly labeled INFERRED.
"""
from auth import validate_token


class AuthService:
    """Base authentication service."""

    def validate_token(self, token: str) -> int:
        """Delegate to module-level validate_token."""
        return validate_token(token)  # PROVEN — direct call

    def is_authenticated(self, token: str) -> bool:
        """Check if a token is valid."""
        try:
            self.validate_token(token)  # INFERRED — self.method()
            return True
        except (ValueError, TypeError):
            return False


class OrderService(AuthService):
    """Order processing service. Inherits auth from AuthService."""

    def verify(self, token: str) -> int:
        """
        Verify token before processing an order.

        ADVERSARIAL CASE: This self.validate_token() call is INFERRED.
        In the patch, validate_token now returns None instead of raising
        on bad tokens. OrderService.verify() does not handle this —
        it will silently propagate None as a user_id.
        """
        return self.validate_token(token)  # INFERRED — inheritance, must not be upgraded to PROVEN

    def process_order(self, token: str, order_data: dict) -> dict:
        """Process an order after verifying the token."""
        user_id = self.verify(token)  # INFERRED — self.method()
        return {"user_id": user_id, "status": "processed", **order_data}


class BackgroundJobService:
    """Background job processor."""

    def __init__(self, order_service: OrderService):
        self._service = order_service

    def run_job(self, token: str, payload: dict) -> None:
        """Background job that calls validate_token indirectly."""
        self._service.verify(token)  # INFERRED — obj.method()
        # ... process job
