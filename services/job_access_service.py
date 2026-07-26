"""Ownership checks shared by job APIs, pages, and output delivery."""

from __future__ import annotations

from typing import Any

from database import get_db
from services.session_service import (
    AuthenticationRequiredError,
    require_authenticated_user_id,
)


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
    """Allow legacy jobs or require ownership of an indexed project job."""
    context = get_job_access_context(public_job_id)
    if context["is_legacy"]:
        return context

    user_id = require_authenticated_user_id()
    if context["owner_id"] != user_id:
        raise JobAccessDeniedError("无权访问该任务")
    context["user_id"] = user_id
    return context


def get_job_list_visibility() -> tuple[set[str], set[str]]:
    """Return all indexed IDs and those owned by the current active user."""
    try:
        user_id = require_authenticated_user_id()
    except AuthenticationRequiredError:
        user_id = None

    rows = get_db().execute(
        """
        SELECT jobs.public_job_id, projects.owner_id
        FROM jobs
        LEFT JOIN projects ON projects.id = jobs.project_id
        """
    ).fetchall()
    indexed_ids = {str(row["public_job_id"]) for row in rows}
    owned_ids = {
        str(row["public_job_id"])
        for row in rows
        if user_id is not None and row["owner_id"] == user_id
    }
    return indexed_ids, owned_ids
