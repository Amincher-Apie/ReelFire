"""Reusable authentication checks for session-protected API operations."""

from __future__ import annotations

from flask import session

from services.auth_service import get_user_by_id


class AuthenticationRequiredError(PermissionError):
    """Raised when a request does not have an active database user."""


def _clear_authentication_session() -> None:
    session.pop("user_id", None)
    session.pop("user", None)


def require_authenticated_user_id() -> int:
    """Return the active SQLite user ID or reject the current session."""
    user_id = session.get("user_id")
    if isinstance(user_id, bool) or not isinstance(user_id, int):
        _clear_authentication_session()
        raise AuthenticationRequiredError("请先登录")

    user = get_user_by_id(user_id)
    if user is None or not user["is_active"]:
        _clear_authentication_session()
        raise AuthenticationRequiredError("请先登录")
    return int(user["id"])
