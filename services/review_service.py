"""SQLite review history and coordinated report persistence."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from database import get_db
from services.job_index_service import resolve_job_row_id


VALID_REVIEW_STATUSES = frozenset({"approved", "pending", "rejected"})


class ReviewValidationError(ValueError):
    """Raised when review metadata violates the public API contract."""


class ReviewPersistenceUnavailableError(RuntimeError):
    """Raised when a legacy file task cannot be linked to SQLite reviews."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_review_status(value: object) -> str:
    if not isinstance(value, str) or value not in VALID_REVIEW_STATUSES:
        raise ReviewValidationError(
            "status 仅支持 approved、pending 或 rejected"
        )
    return value


def normalize_review_labels(value: object) -> list[str]:
    if not isinstance(value, list):
        raise ReviewValidationError("labels 必须是字符串数组")
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise ReviewValidationError("labels 必须是字符串数组")
        label = item.strip()
        if not label:
            continue
        if len(label) > 50:
            raise ReviewValidationError("单个 label 长度不能超过 50 个字符")
        if label not in seen:
            seen.add(label)
            normalized.append(label)
    if len(normalized) > 20:
        raise ReviewValidationError("labels 最多包含 20 项")
    return normalized


def normalize_review_note(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ReviewValidationError("note 必须是字符串或 null")
    note = value.strip()
    if len(note) > 2000:
        raise ReviewValidationError("note 长度不能超过 2000 个字符")
    return note or None


def _json_or_none(value: object | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _public_review(row) -> dict[str, Any]:
    def decoded(field: str) -> list[Any]:
        value = row[field]
        if value is None:
            return []
        decoded_value = json.loads(value)
        return decoded_value if isinstance(decoded_value, list) else []

    return {
        "id": int(row["id"]),
        "status": row["status"],
        "labels": decoded("labels_json"),
        "note": row["note"],
        "segments": decoded("segments_json"),
        "keyframes": decoded("keyframes_json"),
        "reviewer_id": int(row["reviewer_id"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def create_review(
    *,
    public_job_id: str,
    reviewer_id: int,
    status: str,
    labels: list[str] | None,
    note: str | None,
    segments: list[dict[str, Any]] | None,
    keyframes: list[dict[str, Any]] | None,
    apply_report_update: Callable[[], dict[str, Any]],
    restore_report: Callable[[], None],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Insert one review and update its report without partial success."""
    job_row_id = resolve_job_row_id(public_job_id)
    status = validate_review_status(status)
    timestamp = _utc_now()
    connection = get_db()
    report_updated = False
    updated_report: dict[str, Any] | None = None
    try:
        cursor = connection.execute(
            """
            INSERT INTO reviews (
                job_row_id,
                reviewer_id,
                status,
                labels_json,
                note,
                segments_json,
                keyframes_json,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_row_id,
                reviewer_id,
                status,
                _json_or_none(labels),
                note,
                _json_or_none(segments),
                _json_or_none(keyframes),
                timestamp,
                timestamp,
            ),
        )
        updated_report = apply_report_update()
        report_updated = True
        connection.commit()
    except Exception:
        connection.rollback()
        if report_updated:
            restore_report()
        raise

    row = connection.execute(
        """
        SELECT
            id,
            reviewer_id,
            status,
            labels_json,
            note,
            segments_json,
            keyframes_json,
            created_at,
            updated_at
        FROM reviews
        WHERE id = ?
        """,
        (cursor.lastrowid,),
    ).fetchone()
    if row is None or updated_report is None:
        raise sqlite3.DatabaseError("Created review could not be reloaded")
    return _public_review(row), updated_report


def list_review_history(public_job_id: str) -> list[dict[str, Any]]:
    """Return newest-first review history for one indexed job."""
    rows = get_db().execute(
        """
        SELECT
            reviews.id,
            reviews.reviewer_id,
            reviews.status,
            reviews.labels_json,
            reviews.note,
            reviews.segments_json,
            reviews.keyframes_json,
            reviews.created_at,
            reviews.updated_at
        FROM reviews
        JOIN jobs ON jobs.id = reviews.job_row_id
        WHERE jobs.public_job_id = ?
        ORDER BY reviews.id DESC
        """,
        (public_job_id,),
    ).fetchall()
    return [_public_review(row) for row in rows]


def get_latest_review(public_job_id: str) -> dict[str, Any] | None:
    """Return the most recent review, if one exists."""
    history = list_review_history(public_job_id)
    return history[0] if history else None
