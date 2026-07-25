"""Authentication routes for ReelFire."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify, request, session

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")
USERS_FILE = Path("users.db")


def _load_users() -> dict[str, dict[str, Any]]:
    try:
        with USERS_FILE.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
            return value if isinstance(value, dict) else {}
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
        return {}


def _save_users(users: dict[str, dict[str, Any]]) -> None:
    with USERS_FILE.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(users, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


@auth_bp.post("/register")
def register():
    data = request.get_json(silent=True)
    if not data or not data.get("username") or not data.get("password"):
        return jsonify(ok=False, error="请提供用户名和密码"), 400
    username = str(data["username"]).strip()
    password = str(data["password"])
    if len(username) < 2 or len(username) > 32:
        return jsonify(ok=False, error="用户名长度需在2-32字符之间"), 400
    if len(password) < 6:
        return jsonify(ok=False, error="密码长度至少6位"), 400
    users = _load_users()
    if username in users:
        return jsonify(ok=False, error="用户名已存在"), 409
    users[username] = {
        "password": _hash_password(password),
        "created_at": __import__("datetime").datetime.now().isoformat(),
    }
    _save_users(users)
    session["user"] = username
    return jsonify(ok=True, user={"username": username}), 201


@auth_bp.post("/login")
def login():
    data = request.get_json(silent=True)
    if not data or not data.get("username") or not data.get("password"):
        return jsonify(ok=False, error="请提供用户名和密码"), 400
    username = str(data["username"]).strip()
    password = str(data["password"])
    users = _load_users()
    if username not in users or users[username]["password"] != _hash_password(password):
        return jsonify(ok=False, error="用户名或密码错误"), 401
    session["user"] = username
    return jsonify(ok=True, user={"username": username})


@auth_bp.post("/logout")
def logout():
    session.pop("user", None)
    return jsonify(ok=True, message="已退出登录")


@auth_bp.get("/me")
def me():
    username = session.get("user")
    if not username:
        return jsonify(ok=False, error="未登录"), 401
    return jsonify(ok=True, user={"username": username})
