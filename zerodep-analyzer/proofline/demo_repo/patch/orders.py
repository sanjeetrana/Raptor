"""
orders.py — Patch state (unchanged from baseline).

The callers of validate_token are unchanged — they still call it and
expect it to either return a user_id or raise an exception. They do NOT
handle None returns. This is the blast radius of the auth.py change.
"""
from flask import Flask, request, jsonify
from auth import validate_token

app = Flask(__name__)


@app.route("/orders", methods=["GET"])
def get_orders():
    """List all orders for the authenticated user."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user_id = validate_token(token)  # PROVEN caller — still expects int or exception
    # BUG: if validate_token now returns None, this will silently pass
    return jsonify({"user_id": user_id, "orders": []})


@app.route("/orders/<int:order_id>", methods=["GET"])
def get_order(order_id: int):
    """Get a specific order."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user_id = validate_token(token)  # PROVEN caller
    return jsonify({"user_id": user_id, "order_id": order_id})


@app.route("/orders", methods=["POST"])
def create_order():
    """Create a new order."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user_id = validate_token(token)  # PROVEN caller
    data = request.get_json()
    return jsonify({"user_id": user_id, "created": True, "data": data}), 201


def cancel_order(order_id: int, token: str) -> bool:
    """Cancel an order (non-route caller)."""
    user_id = validate_token(token)  # PROVEN caller
    return True


def _internal_process(token: str) -> dict:
    """Private function — not part of public API."""
    user_id = validate_token(token)
    return {"processed": user_id}
