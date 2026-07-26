"""SQLite lookup helpers for public and internal job identifiers."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

from database import get_db


class InvalidPublicJobIdError(ValueError):
    """Raised when a public job identifier is not a non-empty string."""


class JobIndexNotFoundError(LookupError):
    """Raised when no SQLite job row matches a public identifier."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validated_public_job_id(public_job_id: object) -> str:
    if (
        isinstance(public_job_id, bool)
        or not isinstance(public_job_id, str)
        or not public_job_id.strip()
    ):
        raise InvalidPublicJobIdError(
            "public_job_id must be a non-empty string"
        )
    return public_job_id


def _find_job_index(public_job_id: object):
    validated = _validated_public_job_id(public_job_id)
    row = get_db().execute(
        """
        SELECT
            id,
            public_job_id,
            project_id,
            asset_id,
            created_by,
            status,
            job_json_path,
            report_json_path,
            rough_cut_path
        FROM jobs
        WHERE public_job_id = ?
        """,
        (validated,),
    ).fetchone()
    if row is None:
        raise JobIndexNotFoundError(
            f"No job index exists for public_job_id {validated!r}"
        )
    return row


def resolve_job_row_id(public_job_id: str) -> int:
    """Resolve a public string identifier to the SQLite jobs.id value."""
    return int(_find_job_index(public_job_id)["id"])


def get_job_index_by_public_id(public_job_id: str) -> dict[str, Any]:
    """Return the SQLite job index fields for a public identifier."""
    return dict(_find_job_index(public_job_id))


def create_asset_and_job_index(
    *,
    project_id: int,
    created_by: int,
    public_job_id: str,
    original_name: str,
    stored_path: str,
    mime_type: str | None,
    size_bytes: int,
    job_json_path: str,
    status: str,
) -> dict[str, Any]:
    """Atomically persist an uploaded asset and its filesystem job index."""
    validated_public_job_id = _validated_public_job_id(public_job_id)
    timestamp = _utc_now()
    connection = get_db()
    try:
        asset_cursor = connection.execute(
            """
            INSERT INTO assets (
                project_id,
                original_name,
                stored_path,
                media_type,
                mime_type,
                size_bytes,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, 'video', ?, ?, ?, ?)
            """,
            (
                project_id,
                original_name,
                stored_path,
                mime_type,
                size_bytes,
                timestamp,
                timestamp,
            ),
        )
        asset_id = int(asset_cursor.lastrowid)
        job_cursor = connection.execute(
            """
            INSERT INTO jobs (
                public_job_id,
                project_id,
                asset_id,
                created_by,
                status,
                job_json_path,
                report_json_path,
                rough_cut_path,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)
            """,
            (
                validated_public_job_id,
                project_id,
                asset_id,
                created_by,
                status,
                job_json_path,
                timestamp,
                timestamp,
            ),
        )
        connection.commit()
    except sqlite3.Error:
        connection.rollback()
        raise

    return {
        "id": int(job_cursor.lastrowid),
        "public_job_id": validated_public_job_id,
        "project_id": project_id,
        "asset_id": asset_id,
        "created_by": created_by,
        "status": status,
        "job_json_path": job_json_path,
        "report_json_path": None,
        "rough_cut_path": None,
    }
