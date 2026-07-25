"""SQLite-backed project ownership operations."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

from database import get_db


class ProjectValidationError(ValueError):
    """Raised when project input does not satisfy the API contract."""


class ProjectOwnerForbiddenError(ProjectValidationError):
    """Raised when a request attempts to choose a project owner."""


class ProjectNotFoundError(LookupError):
    """Raised when a project ID does not exist."""


class ProjectAccessDeniedError(PermissionError):
    """Raised when a project belongs to a different user."""


PROJECT_FIELDS = """
    id,
    owner_id,
    name,
    description,
    game_type,
    status,
    created_at,
    updated_at
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validated_owner_id(owner_id: object) -> int:
    if isinstance(owner_id, bool) or not isinstance(owner_id, int) or owner_id <= 0:
        raise ProjectValidationError("owner_id 必须是有效的登录用户编号")
    return owner_id


def _validated_project_id(project_id: object) -> int:
    if isinstance(project_id, bool) or not isinstance(project_id, int) or project_id <= 0:
        raise ProjectValidationError("project_id 必须是正整数")
    return project_id


def _validated_name(name: object) -> str:
    if not isinstance(name, str):
        raise ProjectValidationError("name 必须是字符串")
    value = name.strip()
    if not 1 <= len(value) <= 100:
        raise ProjectValidationError("name 长度必须为 1 到 100 个字符")
    return value


def _validated_optional_text(
    value: object,
    field: str,
    maximum: int,
    *,
    strip: bool = False,
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ProjectValidationError(f"{field} 必须是字符串或 null")
    normalized = value.strip() if strip else value
    if len(normalized) > maximum:
        raise ProjectValidationError(f"{field} 长度不能超过 {maximum} 个字符")
    return normalized or None


def create_project(
    owner_id: int,
    name: object,
    description: object = None,
    game_type: object = None,
) -> dict[str, Any]:
    """Create an active project owned by the authenticated user."""
    validated_owner_id = _validated_owner_id(owner_id)
    validated_name = _validated_name(name)
    validated_description = _validated_optional_text(
        description,
        "description",
        1000,
    )
    validated_game_type = _validated_optional_text(
        game_type,
        "game_type",
        50,
        strip=True,
    )
    timestamp = _utc_now()
    connection = get_db()
    try:
        cursor = connection.execute(
            """
            INSERT INTO projects (
                owner_id,
                name,
                description,
                game_type,
                status,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, 'active', ?, ?)
            """,
            (
                validated_owner_id,
                validated_name,
                validated_description,
                validated_game_type,
                timestamp,
                timestamp,
            ),
        )
        connection.commit()
    except sqlite3.Error:
        connection.rollback()
        raise

    row = connection.execute(
        f"""
        SELECT {PROJECT_FIELDS}
        FROM projects
        WHERE id = ?
        """,
        (cursor.lastrowid,),
    ).fetchone()
    return dict(row)


def list_projects_for_owner(owner_id: int) -> list[dict[str, Any]]:
    """List only projects owned by one authenticated user."""
    rows = get_db().execute(
        f"""
        SELECT {PROJECT_FIELDS}
        FROM projects
        WHERE owner_id = ?
        ORDER BY created_at DESC, id DESC
        """,
        (_validated_owner_id(owner_id),),
    ).fetchall()
    return [dict(row) for row in rows]


def get_owned_project(project_id: int, owner_id: int) -> dict[str, Any]:
    """Return a project while distinguishing absence from denied access."""
    row = get_db().execute(
        f"""
        SELECT {PROJECT_FIELDS}
        FROM projects
        WHERE id = ?
        """,
        (_validated_project_id(project_id),),
    ).fetchone()
    if row is None:
        raise ProjectNotFoundError("项目不存在")
    if int(row["owner_id"]) != _validated_owner_id(owner_id):
        raise ProjectAccessDeniedError("无权访问该项目")
    return dict(row)
