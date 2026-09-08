"""services.py — Fixed state (unchanged from baseline)."""
from auth import validate_token


class AuthService:
    def validate_token(self, token: str) -> int:
        return validate_token(token)

    def is_authenticated(self, token: str) -> bool:
        try:
            self.validate_token(token)
            return True
        except ValueError:
            return False


class OrderService(AuthService):
    def verify(self, token: str) -> int:
        return self.validate_token(token)

    def process_order(self, token: str, order_data: dict) -> dict:
        user_id = self.verify(token)
        return {"user_id": user_id, "status": "processed", **order_data}


class BackgroundJobService:
    def __init__(self, order_service: OrderService):
        self._service = order_service

    def run_job(self, token: str, payload: dict) -> None:
        self._service.verify(token)
