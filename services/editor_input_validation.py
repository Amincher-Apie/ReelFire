"""Validation and explicitly scoped compatibility for Editor segment inputs."""

from __future__ import annotations

import math
from copy import deepcopy
from typing import Any


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
        raise EditorSegmentValidationError("video_duration 必须大于等于 0")
    return duration


def _normalize_segments(
    value: object,
    video_duration: object,
    *,
    legacy: bool,
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
            raise EditorSegmentValidationError(f"{prefix} 必须是 JSON 对象")
        segment = deepcopy(item)

        if "id" not in segment:
            if not legacy:
                raise EditorSegmentValidationError(f"{prefix}.id 必须存在")
            segment["id"] = f"seg_{index + 1:03d}"
        raw_id = segment["id"]
        if not isinstance(raw_id, str) or not raw_id.strip():
            raise EditorSegmentValidationError(f"{prefix}.id 必须是非空字符串")
        segment_id = raw_id.strip()
        if segment_id in seen_ids:
            raise EditorSegmentValidationError(f"{prefix}.id 不能重复")
        seen_ids.add(segment_id)

        if "order" not in segment:
            if not legacy:
                raise EditorSegmentValidationError(f"{prefix}.order 必须存在")
            segment["order"] = index + 1
        order = segment["order"]
        if isinstance(order, bool) or not isinstance(order, int) or order <= 0:
            raise EditorSegmentValidationError(f"{prefix}.order 必须是正整数")
        if order in seen_orders:
            raise EditorSegmentValidationError(f"{prefix}.order 不能重复")
        seen_orders.add(order)

        for field in ("start", "end"):
            if field not in segment:
                raise EditorSegmentValidationError(f"{prefix}.{field} 必须存在")
        start = _finite_number(segment["start"], f"{prefix}.start")
        end = _finite_number(segment["end"], f"{prefix}.end")
        if not 0 <= start < end:
            raise EditorSegmentValidationError(
                f"{prefix} 必须满足 0 <= start < end"
            )
        if duration is not None and end > duration:
            raise EditorSegmentValidationError(
                f"{prefix}.end 不能超过 video_duration"
            )

        if "score" not in segment:
            if not legacy:
                raise EditorSegmentValidationError(f"{prefix}.score 必须存在")
            score: float | None = None
        else:
            score = _finite_number(segment["score"], f"{prefix}.score")
            if not 0 <= score <= 1:
                raise EditorSegmentValidationError(
                    f"{prefix}.score 必须在 0 到 1 之间"
                )

        if "source_keyframes" not in segment:
            if not legacy:
                raise EditorSegmentValidationError(
                    f"{prefix}.source_keyframes 必须存在"
                )
            source_keyframes: list[str] = []
        else:
            raw_keyframes = segment["source_keyframes"]
            if not isinstance(raw_keyframes, list):
                raise EditorSegmentValidationError(
                    f"{prefix}.source_keyframes 必须是数组"
                )
            source_keyframes = []
            for frame_index, frame_id in enumerate(raw_keyframes):
                if not isinstance(frame_id, str) or not frame_id.strip():
                    raise EditorSegmentValidationError(
                        f"{prefix}.source_keyframes[{frame_index}] "
                        "必须是非空字符串"
                    )
                source_keyframes.append(frame_id.strip())

        segment.update(
            id=segment_id,
            order=order,
            start=start,
            end=end,
            score=score,
            source_keyframes=source_keyframes,
        )
        normalized.append(segment)

    return sorted(normalized, key=lambda segment: segment["order"])


def validate_editor_segments(
    value: object,
    video_duration: object,
) -> list[dict[str, Any]]:
    """Strictly validate current CV ``segments[]`` without inventing fields."""

    return _normalize_segments(value, video_duration, legacy=False)


def adapt_legacy_segments(
    value: object,
    video_duration: object,
) -> list[dict[str, Any]]:
    """Open explicitly identified legacy jobs with deterministic old defaults.

    This adapter is only for jobs already classified as legacy by persistent job
    metadata. It must never be selected by inspecting which segment fields are
    missing. Missing historical IDs/orders use their original array position,
    missing scores remain ``None``, and missing keyframe references become ``[]``.
    Supplied malformed values are still rejected.
    """

    return _normalize_segments(value, video_duration, legacy=True)
