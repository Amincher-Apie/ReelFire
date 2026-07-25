"""SQLite lookup helpers for public and internal job identifiers."""

from __future__ import annotations

from typing import Any

from database import get_db


class InvalidPublicJobIdError(ValueError):
    """Raised when a public job identifier is not a non-empty string."""


class JobIndexNotFoundError(LookupError):
    """Raised when no SQLite job row matches a public identifier."""


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
