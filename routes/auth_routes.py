"""Authentication routes for ReelFire."""

from __future__ import annotations

from flask import Blueprint, jsonify, request, session

from services.auth_service import (
    UsernameExistsError,
    authenticate_user,
    create_guest_user,
    create_user,
    get_user_by_id,
)


auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def _error(message: str, error_code: str, status: int):
    return jsonify(ok=False, error=message, error_code=error_code), status


@auth_bp.post("/register")
def register():
    data = request.get_json(silent=True)
    if (
        not isinstance(data, dict)
        or not data.get("username")
        or not data.get("password")
    ):
        return _error("请提供用户名和密码", "AUTH_INPUT_REQUIRED", 400)
    username = str(data["username"]).strip()
    password = str(data["password"])
    if len(username) < 2 or len(username) > 32:
        return _error(
            "用户名长度需在2-32字符之间",
            "AUTH_USERNAME_INVALID",
            400,
        )
    if len(password) < 6:
        return _error("密码长度至少6位", "AUTH_PASSWORD_WEAK", 400)
    try:
        user = create_user(username, password)
    except UsernameExistsError:
        return _error("用户名已存在", "AUTH_USERNAME_EXISTS", 409)
    session.pop("user", None)
    session["user_id"] = user["id"]
    return jsonify(ok=True, user=user), 201


@auth_bp.post("/login")
def login():
    data = request.get_json(silent=True)
    if (
        not isinstance(data, dict)
        or not data.get("username")
        or not data.get("password")
    ):
        return _error("请提供用户名和密码", "AUTH_INPUT_REQUIRED", 400)
    username = str(data["username"]).strip()
    password = str(data["password"])
    user = authenticate_user(username, password)
    if user is None:
        return _error(
            "用户名或密码错误",
            "AUTH_INVALID_CREDENTIALS",
            401,
        )
    session.pop("user", None)
    session["user_id"] = user["id"]
    return jsonify(ok=True, user=user)


@auth_bp.post("/guest")
def guest_login():
    user = create_guest_user()
    session.clear()
    session["user_id"] = user["id"]
    return jsonify(ok=True, user=user), 201


@auth_bp.post("/logout")
def logout():
    session.pop("user_id", None)
    session.pop("user", None)
    return jsonify(ok=True, message="已退出登录")


@auth_bp.get("/me")
def me():
    user = get_user_by_id(session.get("user_id"))
    if user is None or not user.pop("is_active"):
        session.pop("user_id", None)
        session.pop("user", None)
        return _error("未登录", "AUTH_REQUIRED", 401)
    return jsonify(ok=True, user=user)
