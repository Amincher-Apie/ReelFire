"""Ownership checks shared by job APIs, pages, and output delivery."""

from __future__ import annotations

from typing import Any

from flask import current_app

from database import get_db
from services.session_service import require_authenticated_user


class JobAccessDeniedError(PermissionError):
    """Raised when an indexed job belongs to another user."""


def get_job_access_context(public_job_id: str) -> dict[str, Any]:
    """Return ownership context without exposing SQLite internal job IDs."""
    row = get_db().execute(
        """
        SELECT
            jobs.public_job_id,
            jobs.project_id,
            projects.owner_id
        FROM jobs
        LEFT JOIN projects ON projects.id = jobs.project_id
        WHERE jobs.public_job_id = ?
        """,
        (public_job_id,),
    ).fetchone()
    if row is None:
        return {
            "is_legacy": True,
            "public_job_id": public_job_id,
        }
    return {
        "is_legacy": False,
        "public_job_id": row["public_job_id"],
        "project_id": int(row["project_id"]),
        "owner_id": (
            int(row["owner_id"])
            if row["owner_id"] is not None
            else None
        ),
    }


def require_job_access(public_job_id: str) -> dict[str, Any]:
    """Require an authenticated owner for every accessible job."""
    user = require_authenticated_user()
    context = get_job_access_context(public_job_id)
    if context["is_legacy"]:
        current_app.extensions["job_service"].get_job(public_job_id)
        raise JobAccessDeniedError("历史测试任务未关联当前用户，不能通过账户界面访问")

    user_id = int(user["id"])
    if context["owner_id"] != user_id:
        raise JobAccessDeniedError("无权访问该任务")
    context["user_id"] = user_id
    return context


def get_visible_job_ids() -> set[str]:
    """Return indexed jobs owned by the user; guests have no history."""
    user = require_authenticated_user()
    if user["is_guest"]:
        return set()

    rows = get_db().execute(
        """
        SELECT jobs.public_job_id
        FROM jobs
        JOIN projects ON projects.id = jobs.project_id
        WHERE projects.owner_id = ?
        """,
        (int(user["id"]),),
    ).fetchall()
    return {str(row["public_job_id"]) for row in rows}
