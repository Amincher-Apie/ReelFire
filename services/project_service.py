"""SQLite-backed project ownership operations."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
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


class ProjectStateConflictError(RuntimeError):
    """Raised when project state forbids the requested operation."""


class ProjectArchivedError(ProjectStateConflictError):
    """Raised when a new task targets an archived project."""


class ProjectNotEmptyError(ProjectStateConflictError):
    """Raised when deleting a project that still contains jobs."""


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
PROJECT_UPDATE_FIELDS = frozenset(
    {"name", "description", "game_type", "status"}
)
PROJECT_STATUSES = frozenset({"active", "archived"})
JOB_STATUSES = (
    "created",
    "queued",
    "running",
    "completed",
    "failed",
)


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
    empty_as_none: bool = True,
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ProjectValidationError(f"{field} 必须是字符串或 null")
    normalized = value.strip() if strip else value
    if len(normalized) > maximum:
        raise ProjectValidationError(f"{field} 长度不能超过 {maximum} 个字符")
    if empty_as_none and not normalized:
        return None
    return normalized


def _validated_status(status: object) -> str:
    if not isinstance(status, str) or status not in PROJECT_STATUSES:
        raise ProjectValidationError("status 仅支持 active 或 archived")
    return status


def _public_project(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        field: row[field]
        for field in (
            "id",
            "name",
            "description",
            "game_type",
            "status",
            "created_at",
            "updated_at",
        )
    }


def _owned_project_row(
    connection: sqlite3.Connection,
    project_id: int,
    owner_id: int,
):
    row = connection.execute(
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
    return row


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
    row = _owned_project_row(get_db(), project_id, owner_id)
    return dict(row)


def get_project_detail(project_id: int, owner_id: int) -> dict[str, Any]:
    """Return one owned project with fixed lifecycle status statistics."""

    connection = get_db()
    row = _owned_project_row(connection, project_id, owner_id)
    counts = connection.execute(
        """
        SELECT status, COUNT(*) AS count
        FROM jobs
        WHERE project_id = ?
        GROUP BY status
        """,
        (int(row["id"]),),
    ).fetchall()
    jobs_by_status = {status: 0 for status in JOB_STATUSES}
    for count_row in counts:
        jobs_by_status[str(count_row["status"])] = int(count_row["count"])
    project = _public_project(row)
    project["job_count"] = sum(jobs_by_status.values())
    project["jobs_by_status"] = jobs_by_status
    return project


def update_project(
    project_id: int,
    owner_id: int,
    changes: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate and transactionally update editable project fields."""

    if not isinstance(changes, Mapping):
        raise ProjectValidationError("请求体必须是合法的 JSON 对象")
    unexpected = set(changes) - PROJECT_UPDATE_FIELDS
    if unexpected:
        raise ProjectValidationError(
            f"不支持的项目字段：{', '.join(sorted(unexpected))}"
        )
    if not changes:
        raise ProjectValidationError("至少需要提交一个可更新字段")

    normalized: dict[str, Any] = {}
    if "name" in changes:
        normalized["name"] = _validated_name(changes["name"])
    if "description" in changes:
        normalized["description"] = _validated_optional_text(
            changes["description"],
            "description",
            1000,
            empty_as_none=False,
        )
    if "game_type" in changes:
        normalized["game_type"] = _validated_optional_text(
            changes["game_type"],
            "game_type",
            50,
            empty_as_none=False,
        )
    if "status" in changes:
        normalized["status"] = _validated_status(changes["status"])

    connection = get_db()
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = _owned_project_row(connection, project_id, owner_id)
        assignments = ", ".join(f"{field} = ?" for field in normalized)
        timestamp = _utc_now()
        connection.execute(
            f"""
            UPDATE projects
            SET {assignments}, updated_at = ?
            WHERE id = ?
            """,
            (
                *normalized.values(),
                timestamp,
                int(row["id"]),
            ),
        )
        updated = connection.execute(
            f"""
            SELECT {PROJECT_FIELDS}
            FROM projects
            WHERE id = ?
            """,
            (int(row["id"]),),
        ).fetchone()
        connection.commit()
    except (
        sqlite3.Error,
        ProjectValidationError,
        ProjectNotFoundError,
        ProjectAccessDeniedError,
    ):
        if connection.in_transaction:
            connection.rollback()
        raise
    return _public_project(updated)


def list_project_jobs(
    project_id: int,
    owner_id: int,
    *,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """List SQLite job summaries for one owned project."""

    if status is not None and status not in JOB_STATUSES:
        raise ProjectValidationError("status 不是合法的任务状态")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ProjectValidationError("limit 必须是 1 到 100 的整数")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ProjectValidationError("offset 必须是大于或等于 0 的整数")

    connection = get_db()
    project = _owned_project_row(connection, project_id, owner_id)
    parameters: list[Any] = [int(project["id"])]
    status_clause = ""
    if status is not None:
        status_clause = " AND status = ?"
        parameters.append(status)
    total_row = connection.execute(
        f"""
        SELECT COUNT(*) AS count
        FROM jobs
        WHERE project_id = ?{status_clause}
        """,
        parameters,
    ).fetchone()
    rows = connection.execute(
        f"""
        SELECT
            public_job_id,
            status,
            created_at,
            updated_at,
            started_at,
            completed_at,
            error_code,
            error_message,
            report_json_path,
            rough_cut_path
        FROM jobs
        WHERE project_id = ?{status_clause}
        ORDER BY created_at DESC, id DESC
        LIMIT ? OFFSET ?
        """,
        (*parameters, limit, offset),
    ).fetchall()
    jobs = [
        {
            "job_id": row["public_job_id"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "error_code": row["error_code"],
            "error_message": row["error_message"],
            "report_available": bool(row["report_json_path"]),
            "rough_cut_available": bool(row["rough_cut_path"]),
        }
        for row in rows
    ]
    return jobs, int(total_row["count"])


def delete_empty_project(project_id: int, owner_id: int) -> None:
    """Delete one owned project only after checking jobs inside the transaction."""

    connection = get_db()
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = _owned_project_row(connection, project_id, owner_id)
        count_row = connection.execute(
            "SELECT COUNT(*) AS count FROM jobs WHERE project_id = ?",
            (int(row["id"]),),
        ).fetchone()
        if int(count_row["count"]) != 0:
            raise ProjectNotEmptyError(
                "项目仍包含任务，请先逐个删除项目中的任务"
            )
        cursor = connection.execute(
            "DELETE FROM projects WHERE id = ?",
            (int(row["id"]),),
        )
        if cursor.rowcount != 1:
            raise ProjectStateConflictError("项目状态已变化，请刷新后重试")
        connection.commit()
    except (
        sqlite3.Error,
        ProjectValidationError,
        ProjectNotFoundError,
        ProjectAccessDeniedError,
        ProjectStateConflictError,
    ):
        if connection.in_transaction:
            connection.rollback()
        raise
