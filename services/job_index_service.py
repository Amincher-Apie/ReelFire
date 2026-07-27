"""SQLite lookup helpers for public and internal job identifiers."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from database import get_db


class InvalidPublicJobIdError(ValueError):
    """Raised when a public job identifier is not a non-empty string."""


class JobIndexNotFoundError(LookupError):
    """Raised when no SQLite job row matches a public identifier."""


class JobIndexPersistenceError(RuntimeError):
    """Raised when the independent SQLite job index cannot be updated."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobIndexRepository:
    """Thread-safe job index access using one short SQLite connection per call."""

    def __init__(self, database_path: Path, storage_root: Path) -> None:
        self.database_path = Path(database_path).expanduser().resolve()
        self.storage_root = Path(storage_root).expanduser().resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self.database_path),
            timeout=5.0,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def relative_storage_path(
        self,
        path: Path,
        *,
        must_exist: bool = False,
    ) -> str:
        candidate = Path(path).resolve()
        if (
            candidate != self.storage_root
            and self.storage_root not in candidate.parents
        ):
            raise JobIndexPersistenceError("任务索引路径超出允许的存储目录")
        if must_exist and not candidate.exists():
            raise JobIndexPersistenceError("任务索引路径对应的文件不存在")
        return candidate.relative_to(self.storage_root).as_posix()

    def sync_job(
        self,
        public_job_id: str,
        job: dict[str, Any],
        *,
        job_json_path: Path,
        report_json_path: Path | None,
        rough_cut_path: Path | None,
    ) -> bool:
        validated = _validated_public_job_id(public_job_id)
        relative_job = self.relative_storage_path(
            job_json_path,
            must_exist=True,
        )
        relative_report = (
            self.relative_storage_path(report_json_path, must_exist=True)
            if report_json_path is not None
            else None
        )
        relative_rough_cut = (
            self.relative_storage_path(rough_cut_path, must_exist=True)
            if rough_cut_path is not None
            else None
        )
        status = str(job.get("status", ""))
        if status not in {"created", "queued", "running", "completed", "failed"}:
            raise JobIndexPersistenceError("任务索引状态不合法")
        error_message = job.get("error")
        if error_message is not None:
            error_message = str(error_message)
        error_code = job.get("error_code")
        if error_code is not None:
            error_code = str(error_code)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status = ?,
                    job_json_path = ?,
                    report_json_path = ?,
                    rough_cut_path = ?,
                    error_code = ?,
                    error_message = ?,
                    started_at = ?,
                    completed_at = ?,
                    updated_at = ?
                WHERE public_job_id = ?
                """,
                (
                    status,
                    relative_job,
                    relative_report,
                    relative_rough_cut,
                    error_code,
                    error_message,
                    job.get("started_at"),
                    job.get("completed_at"),
                    job.get("updated_at") or _utc_now(),
                    validated,
                ),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                raise JobIndexNotFoundError(
                    "项目任务对应的 SQLite jobs 索引不存在"
                )
            connection.commit()
            return True
        except (
            sqlite3.Error,
            JobIndexNotFoundError,
            JobIndexPersistenceError,
        ) as exc:
            if connection.in_transaction:
                connection.rollback()
            if isinstance(
                exc,
                (JobIndexNotFoundError, JobIndexPersistenceError),
            ):
                raise
            raise JobIndexPersistenceError("SQLite 任务索引同步失败") from exc
        finally:
            connection.close()

    def has_job_index(self, public_job_id: str) -> bool:
        """Return whether a public job still has a SQLite index row."""

        validated = _validated_public_job_id(public_job_id)
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT 1 FROM jobs WHERE public_job_id = ? LIMIT 1",
                (validated,),
            ).fetchone()
            return row is not None
        except sqlite3.Error as exc:
            raise JobIndexPersistenceError(
                "无法确认 SQLite 任务索引是否存在"
            ) from exc
        finally:
            connection.close()

    def list_indexed_jobs(self) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT
                    id,
                    public_job_id,
                    project_id,
                    asset_id,
                    status,
                    job_json_path,
                    report_json_path,
                    rough_cut_path
                FROM jobs
                ORDER BY id
                """
            ).fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error as exc:
            raise JobIndexPersistenceError("无法读取 SQLite 任务索引") from exc
        finally:
            connection.close()

    def mark_missing_workspace_failed(
        self,
        public_job_id: str,
        message: str,
    ) -> None:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE jobs
                SET status = 'failed',
                    report_json_path = NULL,
                    rough_cut_path = NULL,
                    error_code = 'JOB_STORAGE_MISSING',
                    error_message = ?,
                    completed_at = COALESCE(completed_at, ?),
                    updated_at = ?
                WHERE public_job_id = ?
                """,
                (message, _utc_now(), _utc_now(), public_job_id),
            )
            connection.commit()
        except sqlite3.Error as exc:
            if connection.in_transaction:
                connection.rollback()
            raise JobIndexPersistenceError("缺失任务索引修复失败") from exc
        finally:
            connection.close()

    def delete_job_index(self, public_job_id: str) -> bool:
        """Delete one job and its now-unreferenced asset in one transaction."""

        validated = _validated_public_job_id(public_job_id)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT id, asset_id FROM jobs WHERE public_job_id = ?",
                (validated,),
            ).fetchone()
            if row is None:
                connection.rollback()
                return False
            asset_id = int(row["asset_id"])
            connection.execute(
                "DELETE FROM jobs WHERE id = ?",
                (int(row["id"]),),
            )
            references = connection.execute(
                "SELECT COUNT(*) AS count FROM jobs WHERE asset_id = ?",
                (asset_id,),
            ).fetchone()
            if int(references["count"]) == 0:
                connection.execute(
                    "DELETE FROM assets WHERE id = ?",
                    (asset_id,),
                )
            connection.commit()
            return True
        except sqlite3.Error as exc:
            if connection.in_transaction:
                connection.rollback()
            raise JobIndexPersistenceError("SQLite 任务删除事务失败") from exc
        finally:
            connection.close()


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
