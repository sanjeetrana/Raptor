"""
services.py — Baseline services with class hierarchy.

AuthService is the base. OrderService inherits from it.
OrderService.verify() calls self.validate_token() — this is an INFERRED
edge because class-hierarchy resolution is required.
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
            self.validate_token(token)  # INFERRED — self.method() call
            return True
        except ValueError:
            return False


class OrderService(AuthService):
    """Order processing service. Inherits auth from AuthService."""

    def verify(self, token: str) -> int:
        """
        Verify token before processing an order.

        This call to self.validate_token() is an INFERRED edge —
        it may be resolved by inheritance to AuthService.validate_token
        or overridden by a subclass. Proofline cannot prove which at
        parse time without runtime type information.
        """
        return self.validate_token(token)  # INFERRED — inheritance edge (§8 adversarial case)

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
