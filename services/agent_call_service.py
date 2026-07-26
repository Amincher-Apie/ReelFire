"""SQLite persistence for Agent call lifecycle logs, without Agent execution."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any

from database import get_db
from services.job_index_service import resolve_job_row_id


AGENT_CALL_STATUSES = frozenset(
    {"queued", "running", "completed", "failed", "needs_review"}
)
ACTIVE_STATUSES = frozenset({"queued", "running"})
INLINE_RESULT_PREFIX = "inline_json$"
_CREATE_LOCK = threading.RLock()


class AgentCallValidationError(ValueError):
    """Raised when Agent call metadata violates the service contract."""


class AgentCallNotFoundError(LookupError):
    """Raised when an Agent call ID does not exist."""


class AgentCallPersistenceUnavailableError(RuntimeError):
    """Raised when a legacy task cannot own an Agent call row."""


class AgentAlreadyRunningError(RuntimeError):
    """Raised when a task already has a queued or running Agent call."""


class AgentCallStateConflictError(RuntimeError):
    """Raised when an Agent call transition is not allowed."""


class AgentReportNotReadyError(RuntimeError):
    """Raised when a task is not ready to create an Agent call."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _positive_id(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise AgentCallValidationError(
            "agent_call_id 必须是正整数"
        )
    return value


def _required_text(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise AgentCallValidationError(f"{field} 必须是字符串")
    normalized = value.strip()
    if not normalized:
        raise AgentCallValidationError(f"{field} 不能为空")
    if len(normalized) > maximum:
        raise AgentCallValidationError(
            f"{field} 长度不能超过 {maximum} 个字符"
        )
    return normalized


def _optional_text(value: object, field: str, maximum: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise AgentCallValidationError(f"{field} 必须是字符串或 null")
    normalized = value.strip()
    if len(normalized) > maximum:
        raise AgentCallValidationError(
            f"{field} 长度不能超过 {maximum} 个字符"
        )
    return normalized or None


def _duration(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AgentCallValidationError(
            "duration_ms 必须是非负整数或 null"
        )
    return value


def _json_list(value: object, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise AgentCallValidationError(f"{field} 必须是数组")
    if len(value) > 100:
        raise AgentCallValidationError(f"{field} 最多包含 100 项")
    return value


def _json_text(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise AgentCallValidationError(
            "Agent JSON 字段包含不可序列化的值"
        ) from exc


def _decoded_list(value: str | None, field: str) -> list[Any]:
    if value is None:
        return []
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise sqlite3.DatabaseError(f"Invalid {field} JSON") from exc
    if not isinstance(decoded, list):
        raise sqlite3.DatabaseError(f"Invalid {field} JSON type")
    return decoded


def _encode_result(result: dict[str, Any]) -> str:
    return f"{INLINE_RESULT_PREFIX}{_json_text(result)}"


def _decode_result(value: str | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if not value.startswith(INLINE_RESULT_PREFIX):
        return None
    try:
        decoded = json.loads(value.removeprefix(INLINE_RESULT_PREFIX))
    except json.JSONDecodeError as exc:
        raise sqlite3.DatabaseError("Invalid inline Agent result JSON") from exc
    if not isinstance(decoded, dict):
        raise sqlite3.DatabaseError("Invalid inline Agent result JSON type")
    return decoded


AGENT_CALL_SELECT = """
    SELECT
        agent_calls.id,
        jobs.public_job_id,
        agent_calls.requested_by,
        agent_calls.status,
        agent_calls.model_name,
        agent_calls.prompt_version,
        agent_calls.input_summary,
        agent_calls.output_summary,
        agent_calls.tool_trace_json,
        agent_calls.references_json,
        agent_calls.result_path,
        agent_calls.duration_ms,
        agent_calls.error_code,
        agent_calls.error_message,
        agent_calls.created_at,
        agent_calls.completed_at
    FROM agent_calls
    JOIN jobs ON jobs.id = agent_calls.job_row_id
"""


def _public_agent_call(row, *, details: bool) -> dict[str, Any]:
    if row["status"] not in AGENT_CALL_STATUSES:
        raise sqlite3.DatabaseError("Invalid Agent call status")
    value = {
        "id": int(row["id"]),
        "job_id": row["public_job_id"],
        "status": row["status"],
        "model_name": row["model_name"],
        "prompt_version": row["prompt_version"],
        "duration_ms": row["duration_ms"],
        "error_code": row["error_code"],
        "error_message": row["error_message"],
        "created_at": row["created_at"],
        "completed_at": row["completed_at"],
    }
    if details:
        value.update(
            requested_by=row["requested_by"],
            input_summary=row["input_summary"],
            output_summary=row["output_summary"],
            tool_trace=_decoded_list(
                row["tool_trace_json"],
                "tool_trace",
            ),
            references=_decoded_list(
                row["references_json"],
                "references",
            ),
            result=_decode_result(row["result_path"]),
        )
    return value


def _get_row(agent_call_id: int):
    row = get_db().execute(
        f"{AGENT_CALL_SELECT} WHERE agent_calls.id = ?",
        (_positive_id(agent_call_id),),
    ).fetchone()
    if row is None:
        raise AgentCallNotFoundError("Agent 调用记录不存在")
    return row


def create_agent_call(
    *,
    public_job_id: str,
    requested_by: int,
    prompt_version: object,
) -> dict[str, Any]:
    """Create one queued call while excluding other active calls."""
    normalized_prompt_version = _required_text(
        prompt_version,
        "prompt_version",
        100,
    )
    job_row_id = resolve_job_row_id(public_job_id)
    connection = get_db()
    with _CREATE_LOCK:
        try:
            connection.execute("BEGIN IMMEDIATE")
            active = connection.execute(
                """
                SELECT 1
                FROM agent_calls
                WHERE job_row_id = ?
                  AND status IN ('queued', 'running')
                LIMIT 1
                """,
                (job_row_id,),
            ).fetchone()
            if active is not None:
                raise AgentAlreadyRunningError(
                    "该任务已有 queued 或 running 的 Agent 调用"
                )
            cursor = connection.execute(
                """
                INSERT INTO agent_calls (
                    job_row_id,
                    requested_by,
                    status,
                    prompt_version,
                    created_at
                )
                VALUES (?, ?, 'queued', ?, ?)
                """,
                (
                    job_row_id,
                    requested_by,
                    normalized_prompt_version,
                    _utc_now(),
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return get_agent_call(int(cursor.lastrowid))


def get_agent_call(agent_call_id: int) -> dict[str, Any]:
    """Return a complete Agent call log with its public job ID."""
    return _public_agent_call(_get_row(agent_call_id), details=True)


def list_agent_calls(public_job_id: str) -> list[dict[str, Any]]:
    """Return newest-first summary logs for one public job ID."""
    rows = get_db().execute(
        f"""
        {AGENT_CALL_SELECT}
        WHERE jobs.public_job_id = ?
        ORDER BY agent_calls.id DESC
        """,
        (public_job_id,),
    ).fetchall()
    return [_public_agent_call(row, details=False) for row in rows]


def mark_agent_call_running(
    agent_call_id: int,
    *,
    model_name: object = None,
    input_summary: object = None,
) -> dict[str, Any]:
    """Transition queued to running and save real execution metadata."""
    normalized_model = _optional_text(model_name, "model_name", 200)
    normalized_input = _optional_text(input_summary, "input_summary", 4000)
    connection = get_db()
    try:
        connection.execute("BEGIN IMMEDIATE")
        current = _get_row(agent_call_id)
        if current["status"] != "queued":
            raise AgentCallStateConflictError(
                "只有 queued 调用可以进入 running"
            )
        connection.execute(
            """
            UPDATE agent_calls
            SET status = 'running',
                model_name = ?,
                input_summary = ?
            WHERE id = ?
            """,
            (
                normalized_model,
                normalized_input,
                agent_call_id,
            ),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return get_agent_call(agent_call_id)


def complete_agent_call(
    agent_call_id: int,
    *,
    status: str,
    model_name: object,
    output_summary: object,
    tool_trace: object,
    references: object,
    result: object,
    duration_ms: object,
) -> dict[str, Any]:
    """Complete a running call with a real structured result."""
    if status not in {"completed", "needs_review"}:
        raise AgentCallValidationError(
            "完成状态仅支持 completed 或 needs_review"
        )
    normalized_model = _optional_text(model_name, "model_name", 200)
    normalized_output = _optional_text(
        output_summary,
        "output_summary",
        4000,
    )
    normalized_trace = _json_list(tool_trace, "tool_trace")
    normalized_references = _json_list(references, "references")
    if not isinstance(result, dict):
        raise AgentCallValidationError("result 必须是 JSON 对象")
    normalized_duration = _duration(duration_ms)
    if normalized_duration is None:
        raise AgentCallValidationError("duration_ms 不能为空")

    connection = get_db()
    try:
        connection.execute("BEGIN IMMEDIATE")
        current = _get_row(agent_call_id)
        if current["status"] != "running":
            raise AgentCallStateConflictError(
                "只有 running 调用可以完成"
            )
        connection.execute(
            """
            UPDATE agent_calls
            SET status = ?,
                model_name = COALESCE(?, model_name),
                output_summary = ?,
                tool_trace_json = ?,
                references_json = ?,
                result_path = ?,
                duration_ms = ?,
                error_code = NULL,
                error_message = NULL,
                completed_at = ?
            WHERE id = ?
            """,
            (
                status,
                normalized_model,
                normalized_output,
                _json_text(normalized_trace),
                _json_text(normalized_references),
                _encode_result(result),
                normalized_duration,
                _utc_now(),
                agent_call_id,
            ),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return get_agent_call(agent_call_id)


def fail_agent_call(
    agent_call_id: int,
    *,
    error_code: object,
    error_message: object,
    duration_ms: object = None,
    tool_trace: object = None,
) -> dict[str, Any]:
    """Persist a failed terminal state without inventing an Agent result."""
    normalized_error_code = _required_text(error_code, "error_code", 100)
    normalized_error_message = _required_text(
        error_message,
        "error_message",
        2000,
    )
    normalized_duration = _duration(duration_ms)
    normalized_trace = (
        None
        if tool_trace is None
        else _json_list(tool_trace, "tool_trace")
    )

    connection = get_db()
    try:
        connection.execute("BEGIN IMMEDIATE")
        current = _get_row(agent_call_id)
        if current["status"] not in ACTIVE_STATUSES:
            raise AgentCallStateConflictError(
                "只有 queued 或 running 调用可以失败"
            )
        connection.execute(
            """
            UPDATE agent_calls
            SET status = 'failed',
                output_summary = NULL,
                tool_trace_json = COALESCE(?, tool_trace_json),
                references_json = NULL,
                result_path = NULL,
                duration_ms = ?,
                error_code = ?,
                error_message = ?,
                completed_at = ?
            WHERE id = ?
            """,
            (
                (
                    _json_text(normalized_trace)
                    if normalized_trace is not None
                    else None
                ),
                normalized_duration,
                normalized_error_code,
                normalized_error_message,
                _utc_now(),
                agent_call_id,
            ),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return get_agent_call(agent_call_id)
