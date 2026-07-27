"""Validation and compatibility for Editor Segment Schema 1.0."""

from __future__ import annotations

import math
from copy import deepcopy
from typing import Any


EDITOR_SEGMENT_SCHEMA_VERSION = "1.0"
VALID_SEGMENT_SOURCES = frozenset({"cv", "manual", "merged", "split"})
VALID_SEGMENT_REVIEW_STATES = frozenset(
    {"", "pass", "needs_review", "reject"}
)
MAX_SEGMENT_ID_LENGTH = 100
MAX_REVIEW_NOTE_LENGTH = 500

EDITOR_SEGMENT_FIELDS = frozenset(
    {
        "id",
        "order",
        "start",
        "end",
        "duration",
        "score",
        "source_keyframes",
        "source",
        "source_segment_ids",
        "review",
        "review_note",
    }
)
INHERITED_EDITOR_FIELDS = frozenset(
    {"source", "source_segment_ids", "review", "review_note"}
)


class EditorSegmentValidationError(ValueError):
    """Raised when Editor segments violate their selected input contract."""


def _finite_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EditorSegmentValidationError(f"{field} 必须是有限数字")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise EditorSegmentValidationError(f"{field} 必须是有限数字")
    return normalized


def _video_duration(value: object) -> float:
    duration = _finite_number(value, "video_duration")
    if duration < 0:
        raise EditorSegmentValidationError(
            "video_duration 必须大于或等于 0"
        )
    return duration


def _string_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list):
        raise EditorSegmentValidationError(f"{field} 必须是字符串数组")
    normalized: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise EditorSegmentValidationError(
                f"{field}[{index}] 必须是非空字符串"
            )
        item_id = item.strip()
        if item_id in seen:
            raise EditorSegmentValidationError(
                f"{field} 不得包含重复项"
            )
        seen.add(item_id)
        normalized.append(item_id)
    return normalized


def _segment_source(value: object, field: str) -> str:
    if not isinstance(value, str) or value not in VALID_SEGMENT_SOURCES:
        raise EditorSegmentValidationError(
            f"{field} 必须是 cv、manual、merged 或 split"
        )
    return value


def _segment_review(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or value not in VALID_SEGMENT_REVIEW_STATES
    ):
        raise EditorSegmentValidationError(
            f'{field} 必须是 ""、pass、needs_review 或 reject'
        )
    return value


def _review_note(value: object, field: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise EditorSegmentValidationError(
            f"{field} 必须是字符串或 null"
        )
    note = value.strip()
    if len(note) > MAX_REVIEW_NOTE_LENGTH:
        raise EditorSegmentValidationError(
            f"{field} 长度不得超过 {MAX_REVIEW_NOTE_LENGTH} 个字符"
        )
    return note


def _normalize_segments(
    value: object,
    video_duration: object,
    *,
    legacy: bool,
    default_review: str,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise EditorSegmentValidationError("segments 必须是数组")

    duration = (
        None
        if legacy and video_duration is None
        else _video_duration(video_duration)
    )
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_orders: set[int] = set()

    for index, item in enumerate(value):
        prefix = f"segments[{index}]"
        if not isinstance(item, dict):
            raise EditorSegmentValidationError(
                f"{prefix} 必须是 JSON 对象"
            )

        if "id" not in item:
            if not legacy:
                raise EditorSegmentValidationError(
                    f"{prefix}.id 必须存在"
                )
            raw_id: object = f"seg_{index + 1:03d}"
        else:
            raw_id = item["id"]
        if not isinstance(raw_id, str) or not raw_id.strip():
            raise EditorSegmentValidationError(
                f"{prefix}.id 必须是非空字符串"
            )
        segment_id = raw_id.strip()
        if len(segment_id) > MAX_SEGMENT_ID_LENGTH:
            raise EditorSegmentValidationError(
                f"{prefix}.id 长度不得超过 "
                f"{MAX_SEGMENT_ID_LENGTH} 个字符"
            )
        if segment_id in seen_ids:
            raise EditorSegmentValidationError(
                f"{prefix}.id 必须唯一"
            )
        seen_ids.add(segment_id)

        if "order" not in item:
            if not legacy:
                raise EditorSegmentValidationError(
                    f"{prefix}.order 必须存在"
                )
            order: object = index + 1
        else:
            order = item["order"]
        if (
            isinstance(order, bool)
            or not isinstance(order, int)
            or order <= 0
        ):
            raise EditorSegmentValidationError(
                f"{prefix}.order 必须是正整数"
            )
        if order in seen_orders:
            raise EditorSegmentValidationError(
                f"{prefix}.order 必须唯一"
            )
        seen_orders.add(order)

        for field in ("start", "end"):
            if field not in item:
                raise EditorSegmentValidationError(
                    f"{prefix}.{field} 必须存在"
                )
        start = _finite_number(item["start"], f"{prefix}.start")
        end = _finite_number(item["end"], f"{prefix}.end")
        if not 0 <= start < end:
            raise EditorSegmentValidationError(
                f"{prefix} 必须满足 0 <= start < end"
            )
        if duration is not None and end > duration:
            raise EditorSegmentValidationError(
                f"{prefix}.end 不得超过 video_duration"
            )

        source = _segment_source(
            item.get("source", "cv"),
            f"{prefix}.source",
        )
        score_was_missing = "score" not in item
        if score_was_missing:
            if not legacy:
                raise EditorSegmentValidationError(
                    f"{prefix}.score 必须存在"
                )
            score: float | None = None
        elif item["score"] is None:
            score = None
        else:
            score = _finite_number(item["score"], f"{prefix}.score")
            if not 0 <= score <= 1:
                raise EditorSegmentValidationError(
                    f"{prefix}.score 必须在 0 到 1 之间"
                )
        if source == "cv" and score is None and not (
            legacy and score_was_missing
        ):
            raise EditorSegmentValidationError(
                f"{prefix}.score 对 cv 片段必须是数字"
            )

        source_keyframes = _string_list(
            item.get("source_keyframes", []),
            f"{prefix}.source_keyframes",
        )
        source_segment_ids = _string_list(
            item.get("source_segment_ids", []),
            f"{prefix}.source_segment_ids",
        )
        if segment_id in source_segment_ids:
            raise EditorSegmentValidationError(
                f"{prefix}.source_segment_ids 不得包含自身 id"
            )
        if source in {"cv", "manual"} and source_segment_ids:
            raise EditorSegmentValidationError(
                f"{prefix}.source_segment_ids 对 {source} 片段必须为空"
            )
        if source == "merged" and len(source_segment_ids) < 2:
            raise EditorSegmentValidationError(
                f"{prefix}.source_segment_ids 对 merged 片段"
                "至少需要两个来源 id"
            )
        if source == "split" and len(source_segment_ids) != 1:
            raise EditorSegmentValidationError(
                f"{prefix}.source_segment_ids 对 split 片段"
                "必须且只能包含一个来源 id"
            )

        review = _segment_review(
            item.get("review", default_review),
            f"{prefix}.review",
        )
        review_note = _review_note(
            item.get("review_note", ""),
            f"{prefix}.review_note",
        )

        normalized.append(
            {
                "id": segment_id,
                "order": order,
                "start": start,
                "end": end,
                "duration": round(end - start, 3),
                "score": score,
                "source_keyframes": source_keyframes,
                "source": source,
                "source_segment_ids": source_segment_ids,
                "review": review,
                "review_note": review_note,
            }
        )

    ordered = sorted(normalized, key=lambda segment: segment["order"])
    for normalized_order, segment in enumerate(ordered, start=1):
        segment["order"] = normalized_order
    return ordered


def _restore_server_extensions(
    normalized: list[dict[str, Any]],
    source: object,
) -> list[dict[str, Any]]:
    if not isinstance(source, list):
        return normalized
    source_by_id = {
        item.get("id").strip(): item
        for item in source
        if isinstance(item, dict)
        and isinstance(item.get("id"), str)
        and item["id"].strip()
    }
    restored: list[dict[str, Any]] = []
    for segment in normalized:
        source_segment = source_by_id.get(segment["id"])
        if source_segment is None:
            restored.append(segment)
            continue
        server_base = deepcopy(source_segment)
        for field in EDITOR_SEGMENT_FIELDS:
            server_base.pop(field, None)
        server_base.update(segment)
        restored.append(server_base)
    return restored


def validate_editor_segments(
    value: object,
    video_duration: object,
) -> list[dict[str, Any]]:
    """Validate client-controlled fields and ignore every unknown field."""

    return _normalize_segments(
        value,
        video_duration,
        legacy=False,
        default_review="",
    )


def normalize_stored_editor_segments(
    value: object,
    video_duration: object,
    *,
    legacy: bool = False,
) -> list[dict[str, Any]]:
    """Normalize stored segments and retain every server extension field."""

    normalized = _normalize_segments(
        value,
        video_duration,
        legacy=legacy,
        default_review="pass",
    )
    return _restore_server_extensions(normalized, value)


def merge_editor_segments(
    value: object,
    existing_segments: object,
    video_duration: object,
    *,
    legacy: bool = False,
) -> list[dict[str, Any]]:
    """Merge omitted PATCH fields from persisted segments by stable id.

    Explicit empty review and review_note values are preserved. A new Segment
    defaults to an unreviewed state. Unknown client fields are ignored, while
    every server-owned extension can only come from the persisted report.
    """

    if not isinstance(value, list):
        raise EditorSegmentValidationError("segments 必须是数组")
    existing = normalize_stored_editor_segments(
        existing_segments,
        video_duration,
        legacy=legacy,
    )
    existing_by_id = {segment["id"]: segment for segment in existing}
    merged_input: list[object] = []
    for item in value:
        if not isinstance(item, dict):
            merged_input.append(item)
            continue
        client = {
            field: deepcopy(item[field])
            for field in EDITOR_SEGMENT_FIELDS
            if field in item
        }
        raw_id = client.get("id")
        segment_id = raw_id.strip() if isinstance(raw_id, str) else None
        persisted = existing_by_id.get(segment_id) if segment_id else None
        if persisted is not None:
            for field in INHERITED_EDITOR_FIELDS:
                if field not in client:
                    client[field] = deepcopy(persisted[field])
        merged_input.append(client)

    normalized = _normalize_segments(
        merged_input,
        video_duration,
        legacy=legacy,
        default_review="",
    )
    return _restore_server_extensions(normalized, existing)


def adapt_legacy_segments(
    value: object,
    video_duration: object,
) -> list[dict[str, Any]]:
    """Normalize explicitly identified legacy persisted segments."""

    return normalize_stored_editor_segments(
        value,
        video_duration,
        legacy=True,
    )
