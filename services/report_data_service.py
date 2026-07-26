"""Pure, whitelist-based aggregation for the Job report-data API."""

from __future__ import annotations

import copy
import math
import re
from typing import Any


_WINDOWS_ABSOLUTE_PATH = re.compile(r"(?i)(?<![a-z0-9])[a-z]:[\\/]")
_UNIX_PRIVATE_PATH = re.compile(
    r"(?i)(?<![/a-z0-9])"
    r"/(?:home|srv|root|users|tmp|var|opt|mnt|etc)/"
)
_FORBIDDEN_KEYS = frozenset(
    {
        "api_key",
        "asset_id",
        "authorization",
        "job_row_id",
        "owner_id",
        "project_id",
        "requested_by",
        "result_path",
        "reviewer_id",
        "token",
    }
)
_SEGMENT_FIELDS = (
    "id",
    "order",
    "start",
    "end",
    "score",
    "source_keyframes",
    "duration",
    "peak_enemy_count",
    "detected_classes",
    "enemy_classes_in_segment",
    "detections_summary",
    "reason",
)
_KEYFRAME_FIELDS = (
    "id",
    "frame_index",
    "timestamp",
    "keep",
    "decision",
    "order",
    "label",
    "note",
    "image",
)


class ReportDataValidationError(ValueError):
    """Raised when report data cannot be exposed through the public contract."""


def _copy_public_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ReportDataValidationError(
                "report data contains a non-finite number"
            )
        return value
    if isinstance(value, list):
        return [_copy_public_value(item) for item in value]
    if isinstance(value, dict):
        copied: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ReportDataValidationError(
                    "report data object keys must be strings"
                )
            if key.lower() in _FORBIDDEN_KEYS:
                raise ReportDataValidationError(
                    "report data contains a private field"
                )
            copied[key] = _copy_public_value(item)
        return copied
    raise ReportDataValidationError(
        "report data contains an unsupported JSON value"
    )


def _public_segment(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReportDataValidationError("segments must contain objects")
    return {
        field: _copy_public_value(value[field])
        for field in _SEGMENT_FIELDS
        if field in value
    }


def _public_keyframe(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReportDataValidationError("keyframes must contain objects")
    return {
        field: _copy_public_value(value[field])
        for field in _KEYFRAME_FIELDS
        if field in value
    }


def _public_review(
    reviews: list[dict[str, Any]],
    review_statistics: dict[str, Any],
) -> dict[str, Any]:
    latest: dict[str, Any] | None = None
    if reviews:
        source = reviews[0]
        if not isinstance(source, dict):
            raise ReportDataValidationError("reviews must contain objects")
        raw_segments = source.get("segments", [])
        raw_keyframes = source.get("keyframes", [])
        if not isinstance(raw_segments, list) or not isinstance(
            raw_keyframes, list
        ):
            raise ReportDataValidationError(
                "review snapshots must contain arrays"
            )
        latest = {
            "status": source.get("status"),
            "labels": _copy_public_value(source.get("labels", [])),
            "note": _copy_public_value(source.get("note")),
            "segments": [
                _public_segment(segment) for segment in raw_segments
            ],
            "keyframes": [
                _public_keyframe(keyframe) for keyframe in raw_keyframes
            ],
            "created_at": _copy_public_value(source.get("created_at")),
            "updated_at": _copy_public_value(source.get("updated_at")),
        }
    return {
        "latest": latest,
        "history_count": review_statistics["history_count"],
        "status_counts": copy.deepcopy(
            review_statistics["status_counts"]
        ),
    }


def _empty_agent(
    availability: str,
    call_statistics: dict[str, Any],
) -> dict[str, Any]:
    return {
        "availability": availability,
        "status": None,
        "summary": None,
        "segment_comments": [],
        "knowledge_refs": [],
        "calls": copy.deepcopy(call_statistics),
    }


def _public_agent(
    agent_report: dict[str, Any] | None,
    availability: str,
    call_statistics: dict[str, Any],
) -> dict[str, Any]:
    if availability not in {"ready", "unavailable", "invalid"}:
        raise ReportDataValidationError(
            "agent availability is invalid"
        )
    if availability != "ready":
        return _empty_agent(availability, call_statistics)
    if not isinstance(agent_report, dict):
        return _empty_agent("invalid", call_statistics)
    try:
        _assert_no_private_data(agent_report)
        status = agent_report.get("status")
        comments = agent_report.get("segment_comments")
        knowledge_refs = agent_report.get("knowledge_refs")
        if (
            status not in {"completed", "degraded"}
            or not isinstance(comments, list)
            or not isinstance(knowledge_refs, list)
        ):
            return _empty_agent("invalid", call_statistics)

        public_comments: list[dict[str, Any]] = []
        for item in comments:
            if not isinstance(item, dict):
                return _empty_agent("invalid", call_statistics)
            public_comments.append(
                {
                    field: _copy_public_value(item[field])
                    for field in (
                        "segment_id",
                        "title",
                        "comment",
                        "score_reason",
                        "review_status",
                        "evidence_refs",
                    )
                    if field in item
                }
            )

        public_knowledge: list[dict[str, Any]] = []
        for item in knowledge_refs:
            if not isinstance(item, dict):
                return _empty_agent("invalid", call_statistics)
            public_knowledge.append(
                {
                    field: _copy_public_value(item[field])
                    for field in ("knowledge_id", "category", "title")
                    if field in item
                }
            )

        public_agent = {
            "availability": "ready",
            "status": status,
            "summary": _copy_public_value(agent_report.get("summary")),
            "segment_comments": public_comments,
            "knowledge_refs": public_knowledge,
            "calls": copy.deepcopy(call_statistics),
        }
        _assert_no_private_data(public_agent)
        return public_agent
    except ReportDataValidationError:
        return _empty_agent("invalid", call_statistics)


def _assert_no_private_data(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in _FORBIDDEN_KEYS:
                raise ReportDataValidationError(
                    "report data contains a private field"
                )
            _assert_no_private_data(item)
        return
    if isinstance(value, list):
        for item in value:
            _assert_no_private_data(item)
        return
    if isinstance(value, float) and not math.isfinite(value):
        raise ReportDataValidationError(
            "report data contains a non-finite number"
        )
    if isinstance(value, str) and (
        _WINDOWS_ABSOLUTE_PATH.search(value)
        or _UNIX_PRIVATE_PATH.search(value)
    ):
        raise ReportDataValidationError(
            "report data contains a private path"
        )
    if value is not None and not isinstance(
        value, (str, bool, int, float)
    ):
        raise ReportDataValidationError(
            "report data contains an unsupported JSON value"
        )


def build_job_report_data(
    *,
    job: dict[str, Any],
    video: dict[str, Any],
    report: dict[str, Any],
    statistics: dict[str, Any],
    reviews: list[dict[str, Any]],
    agent_report: dict[str, Any] | None,
    agent_availability: str,
    rough_cut: dict[str, Any],
) -> dict[str, Any]:
    """Build the stable public report bundle without I/O or mutation."""
    if not all(
        isinstance(value, dict)
        for value in (job, video, report, statistics, rough_cut)
    ):
        raise ReportDataValidationError(
            "report-data object inputs must be objects"
        )
    if not isinstance(reviews, list):
        raise ReportDataValidationError("reviews must be an array")
    raw_segments = report.get("segments", [])
    if not isinstance(raw_segments, list):
        raise ReportDataValidationError("segments must be an array")
    review_statistics = statistics.get("reviews")
    call_statistics = statistics.get("agent_calls")
    timeline = statistics.get("timeline")
    detections = statistics.get("detections")
    segment_statistics = statistics.get("segments")
    if not all(
        isinstance(value, dict)
        for value in (
            review_statistics,
            call_statistics,
            timeline,
            detections,
            segment_statistics,
        )
    ):
        raise ReportDataValidationError(
            "statistics does not match contract version 1.0"
        )

    sample_interval = report.get("sample_interval")
    if isinstance(sample_interval, bool) or not isinstance(
        sample_interval, (int, float)
    ):
        sample_interval = None
    elif not math.isfinite(float(sample_interval)):
        raise ReportDataValidationError(
            "sample_interval must be finite"
        )
    else:
        sample_interval = float(sample_interval)

    result = {
        "job": {
            "job_id": _copy_public_value(job.get("job_id")),
            "status": _copy_public_value(job.get("status")),
            "created_at": _copy_public_value(job.get("created_at")),
            "completed_at": _copy_public_value(job.get("completed_at")),
        },
        "video": {
            "filename": _copy_public_value(video.get("filename")),
            "duration_seconds": _copy_public_value(
                timeline.get("video_duration_seconds")
            ),
        },
        "statistics": copy.deepcopy(statistics),
        "cv": {
            "summary": {
                "sample_interval_seconds": sample_interval,
                "sampled_frame_count": timeline["sampled_frame_count"],
                "keyframe_count": timeline["keyframe_count"],
                "detection_occurrence_count": detections[
                    "total_occurrences"
                ],
                "segment_count": segment_statistics["count"],
            },
            "segments": [
                _public_segment(segment) for segment in raw_segments
            ],
        },
        "agent": _public_agent(
            agent_report,
            agent_availability,
            call_statistics,
        ),
        "review": _public_review(reviews, review_statistics),
        "rough_cut": {
            "available": bool(rough_cut.get("available", False)),
            "filename": _copy_public_value(rough_cut.get("filename")),
            "download_url": _copy_public_value(
                rough_cut.get("download_url")
            ),
        },
    }
    _assert_no_private_data(result)
    return result
