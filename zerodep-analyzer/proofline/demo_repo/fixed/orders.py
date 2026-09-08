"""orders.py — Fixed state (same as baseline, callers unchanged)."""
from flask import Flask, request, jsonify
from auth import validate_token

app = Flask(__name__)


@app.route("/orders", methods=["GET"])
def get_orders():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user_id = validate_token(token)
    return jsonify({"user_id": user_id, "orders": []})


@app.route("/orders/<int:order_id>", methods=["GET"])
def get_order(order_id: int):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user_id = validate_token(token)
    return jsonify({"user_id": user_id, "order_id": order_id})


@app.route("/orders", methods=["POST"])
def create_order():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user_id = validate_token(token)
    data = request.get_json()
    return jsonify({"user_id": user_id, "created": True, "data": data}), 201


def cancel_order(order_id: int, token: str) -> bool:
    user_id = validate_token(token)
    return True


def _internal_process(token: str) -> dict:
    user_id = validate_token(token)
    return {"processed": user_id}
