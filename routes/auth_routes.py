"""Authentication routes for ReelFire — SQLite-backed."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from flask import Blueprint, jsonify, request, session

from database import get_db

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def _iso_now() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def _user_row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "role": row["role"],
        "created_at": row["created_at"],
    }


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

    db = get_db()
    existing = db.execute(
        "SELECT id FROM users WHERE username = ? COLLATE NOCASE",
        (username,),
    ).fetchone()
    if existing is not None:
        return jsonify(ok=False, error="用户名已存在"), 409

    now = _iso_now()
    password_hash = _hash_password(password)
    cursor = db.execute(
        """
        INSERT INTO users (username, password_hash, role, is_active, created_at, updated_at)
        VALUES (?, ?, 'user', 1, ?, ?)
        """,
        (username, password_hash, now, now),
    )
    db.commit()
    session["user_id"] = cursor.lastrowid
    session["user"] = username
    return jsonify(ok=True, user={"username": username}), 201


@auth_bp.post("/login")
def login():
    data = request.get_json(silent=True)
    if not data or not data.get("username") or not data.get("password"):
        return jsonify(ok=False, error="请提供用户名和密码"), 400
    username = str(data["username"]).strip()
    password = str(data["password"])

    db = get_db()
    row = db.execute(
        "SELECT id, username, password_hash, is_active FROM users WHERE username = ? COLLATE NOCASE",
        (username,),
    ).fetchone()
    if row is None or row["password_hash"] != _hash_password(password):
        return jsonify(ok=False, error="用户名或密码错误"), 401
    if not row["is_active"]:
        return jsonify(ok=False, error="账号已被禁用"), 403

    now = _iso_now()
    db.execute(
        "UPDATE users SET last_login_at = ?, updated_at = ? WHERE id = ?",
        (now, now, row["id"]),
    )
    db.commit()
    session["user_id"] = row["id"]
    session["user"] = row["username"]
    return jsonify(ok=True, user={"username": row["username"]})


@auth_bp.post("/logout")
def logout():
    session.pop("user_id", None)
    session.pop("user", None)
    return jsonify(ok=True, message="已退出登录")


@auth_bp.get("/me")
def me():
    user_id = session.get("user_id")
    username = session.get("user")
    if not user_id or not username:
        return jsonify(ok=False, error="未登录"), 401

    db = get_db()
    row = db.execute(
        "SELECT id, username, display_name, role, created_at FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if row is None:
        session.clear()
        return jsonify(ok=False, error="用户不存在"), 401

    return jsonify(ok=True, user=_user_row_to_dict(row))
