"""Pure aggregation for the read-only Job statistics API."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any


REVIEW_STATUSES = ("pending", "approved", "rejected")
AGENT_CALL_STATUSES = (
    "queued",
    "running",
    "completed",
    "needs_review",
    "failed",
)


class StatisticsValidationError(ValueError):
    """Raised when source data cannot be represented safely as statistics."""


def _round(value: float) -> float:
    return round(value, 6)


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    normalized = float(value)
    return normalized if math.isfinite(normalized) else None


def _optional_duration(report: dict[str, Any]) -> float | None:
    if "duration" in report:
        raw_duration = report["duration"]
    else:
        video = report.get("video")
        raw_duration = (
            video.get("duration")
            if isinstance(video, dict) and "duration" in video
            else None
        )
    if raw_duration is None:
        return None
    duration = _finite_number(raw_duration)
    if duration is None or duration < 0:
        raise StatisticsValidationError(
            "video duration must be a finite non-negative number"
        )
    return duration


def _array(report: dict[str, Any], field: str) -> list[Any]:
    if field not in report:
        return []
    value = report[field]
    if not isinstance(value, list):
        raise StatisticsValidationError(f"{field} must be an array")
    return value


def _confidence(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {
            "minimum": None,
            "maximum": None,
            "average": None,
        }
    return {
        "minimum": _round(min(values)),
        "maximum": _round(max(values)),
        "average": _round(sum(values) / len(values)),
    }


def _build_timeline_statistics(
    report: dict[str, Any],
    duration: float | None,
) -> dict[str, Any]:
    return {
        "video_duration_seconds": (
            _round(duration) if duration is not None else None
        ),
        "sampled_frame_count": len(_array(report, "samples")),
        "keyframe_count": len(_array(report, "keyframes")),
    }


def _build_detection_statistics(
    report: dict[str, Any],
) -> dict[str, Any]:
    confidence_values: list[float] = []
    category_counts: dict[str, int] = defaultdict(int)
    category_confidences: dict[str, list[float]] = defaultdict(list)
    total_occurrences = 0

    for sample_index, sample in enumerate(_array(report, "samples")):
        if not isinstance(sample, dict):
            raise StatisticsValidationError(
                f"samples[{sample_index}] must be an object"
            )
        objects = sample.get("objects", [])
        if not isinstance(objects, list):
            raise StatisticsValidationError(
                f"samples[{sample_index}].objects must be an array"
            )
        for detection in objects:
            if not isinstance(detection, dict):
                continue
            total_occurrences += 1
            confidence = _finite_number(detection.get("confidence"))
            valid_confidence = (
                confidence
                if confidence is not None and 0 <= confidence <= 1
                else None
            )
            if valid_confidence is not None:
                confidence_values.append(valid_confidence)

            raw_name = detection.get("class")
            name = raw_name.strip() if isinstance(raw_name, str) else ""
            if not name:
                continue
            category_counts[name] += 1
            if valid_confidence is not None:
                category_confidences[name].append(valid_confidence)

    categories = [
        {
            "name": name,
            "count": count,
            "confidence_observation_count": len(
                category_confidences[name]
            ),
            "confidence": _confidence(category_confidences[name]),
        }
        for name, count in sorted(
            category_counts.items(),
            key=lambda item: (-item[1], item[0]),
        )
    ]
    return {
        "count_semantics": "sampled_detection_occurrences",
        "total_occurrences": total_occurrences,
        "confidence_observation_count": len(confidence_values),
        "confidence": _confidence(confidence_values),
        "categories": categories,
    }


def _valid_segment_interval(
    segment: object,
    duration: float | None,
) -> tuple[float, float] | None:
    if not isinstance(segment, dict):
        return None
    start = _finite_number(segment.get("start"))
    end = _finite_number(segment.get("end"))
    if start is None or end is None or start < 0 or start >= end:
        return None
    if duration is not None and end > duration:
        return None
    return start, end


def _build_segment_statistics(
    report: dict[str, Any],
    duration: float | None,
) -> dict[str, Any]:
    intervals = [
        interval
        for segment in _array(report, "segments")
        if (interval := _valid_segment_interval(segment, duration))
        is not None
    ]
    simple_sum = sum(end - start for start, end in intervals)

    covered = 0.0
    if intervals:
        ordered = sorted(intervals)
        current_start, current_end = ordered[0]
        for start, end in ordered[1:]:
            if start <= current_end:
                current_end = max(current_end, end)
            else:
                covered += current_end - current_start
                current_start, current_end = start, end
        covered += current_end - current_start

    coverage_ratio = (
        None
        if duration is None or duration == 0
        else _round(covered / duration)
    )
    return {
        "count": len(intervals),
        "sum_duration_seconds": _round(simple_sum),
        "covered_duration_seconds": _round(covered),
        "coverage_ratio": coverage_ratio,
    }


def _build_status_statistics(
    history: list[dict[str, Any]],
    statuses: tuple[str, ...],
    field: str,
) -> dict[str, Any]:
    counts = {status: 0 for status in statuses}
    for index, item in enumerate(history):
        if not isinstance(item, dict) or item.get("status") not in counts:
            raise StatisticsValidationError(
                f"{field}[{index}] has an invalid status"
            )
        counts[str(item["status"])] += 1
    return {
        "history_count": len(history),
        "status_counts": counts,
        "latest_status": history[0]["status"] if history else None,
    }


def build_job_statistics(
    *,
    job_id: str,
    report: dict[str, Any],
    reviews: list[dict[str, Any]],
    agent_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the stable public statistics contract without side effects."""
    if not isinstance(job_id, str) or not job_id.strip():
        raise StatisticsValidationError("job_id must be a non-empty string")
    if not isinstance(report, dict):
        raise StatisticsValidationError("report must be an object")
    if not isinstance(reviews, list):
        raise StatisticsValidationError("reviews must be an array")
    if not isinstance(agent_calls, list):
        raise StatisticsValidationError("agent_calls must be an array")

    duration = _optional_duration(report)
    return {
        "job_id": job_id,
        "timeline": _build_timeline_statistics(report, duration),
        "detections": _build_detection_statistics(report),
        "segments": _build_segment_statistics(report, duration),
        "reviews": _build_status_statistics(
            reviews,
            REVIEW_STATUSES,
            "reviews",
        ),
        "agent_calls": _build_status_statistics(
            agent_calls,
            AGENT_CALL_STATUSES,
            "agent_calls",
        ),
    }
