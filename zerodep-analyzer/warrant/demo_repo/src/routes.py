"""routes.py — Flask route handlers."""
try:
    from flask import Flask, request, jsonify
    app = Flask(__name__)
    _flask_available = True
except ImportError:
    _flask_available = False
    app = None

from auth import validate_token, AuthService
from orders import create_order, list_orders

_svc = AuthService()


if _flask_available:
    @app.route("/api/orders", methods=["GET"])
    def get_orders():
        """GET /api/orders — List orders for authenticated user."""
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        if not _svc.is_authenticated(token):
            return jsonify({"error": "unauthorized"}), 401
        return jsonify(list_orders(token))

    @app.route("/api/orders", methods=["POST"])
    def post_order():
        """POST /api/orders — Create a new order."""
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        data = request.json or {}
        try:
            order = create_order(token, data.get("item", ""), data.get("qty", 0))
            return jsonify(order), 201
        except PermissionError as e:
            return jsonify({"error": str(e)}), 401
        except ValueError as e:
            return jsonify({"error": str(e)}), 400


def health_check() -> dict:
    """Liveness probe — always returns OK."""
    return {"status": "ok"}
