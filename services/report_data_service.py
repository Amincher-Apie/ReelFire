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
        "access_token",
        "api_token",
        "job_row_id",
        "owner_id",
        "private_path",
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
    "source",
    "source_segment_ids",
    "review",
    "review_note",
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
_AGENT_PRIORITIES = frozenset({"high", "medium", "low"})
_AGENT_RECOMMENDATIONS = frozenset(
    {"pass", "needs_review", "reject"}
)
_AGENT_ACTION_RECOMMENDATIONS = frozenset(
    {"adopt", "needs_review", "reject"}
)
_AGENT_BOUNDARY_ACTIONS = frozenset(
    {
        "keep",
        "review_start",
        "review_end",
        "review_both",
        "manual_review",
    }
)
_AGENT_EVIDENCE_TYPES = frozenset(
    {"detection", "score", "keyframe", "segment", "report"}
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
        "tags": [],
        "suggestions": [],
        "review": None,
        "evidence_refs": [],
        "segment_comments": [],
        "knowledge_refs": [],
        "calls": copy.deepcopy(call_statistics),
    }


def _agent_string(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ReportDataValidationError(f"{field} must be a string")
    return value


def _agent_string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) for item in value
    ):
        raise ReportDataValidationError(
            f"{field} must be an array of strings"
        )
    return list(value)


def _agent_number(
    value: Any,
    field: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> int | float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        raise ReportDataValidationError(
            f"{field} must be a finite number"
        )
    if minimum is not None and value < minimum:
        raise ReportDataValidationError(f"{field} is below its minimum")
    if maximum is not None and value > maximum:
        raise ReportDataValidationError(f"{field} exceeds its maximum")
    return value


def _agent_optional_number(
    value: Any,
    field: str,
    *,
    minimum: float = 0.0,
) -> int | float | None:
    if value is None:
        return None
    return _agent_number(value, field, minimum=minimum)


def _public_agent_tags(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ReportDataValidationError("agent tags must be an array")
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ReportDataValidationError(
                "agent tags must contain objects"
            )
        result.append(
            {
                "name": _agent_string(item.get("name"), "tag.name"),
                "description": _agent_string(
                    item.get("description"),
                    "tag.description",
                ),
                "evidence_refs": _agent_string_list(
                    item.get("evidence_refs"),
                    "tag.evidence_refs",
                ),
            }
        )
    return result


def _public_agent_suggestions(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ReportDataValidationError(
            "agent suggestions must be an array"
        )
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ReportDataValidationError(
                "agent suggestions must contain objects"
            )
        priority = item.get("priority")
        if priority not in _AGENT_PRIORITIES:
            raise ReportDataValidationError(
                "agent suggestion priority is invalid"
            )
        result.append(
            {
                "suggestion_id": _agent_string(
                    item.get("suggestion_id"),
                    "suggestion.suggestion_id",
                ),
                "title": _agent_string(
                    item.get("title"),
                    "suggestion.title",
                ),
                "action": _agent_string(
                    item.get("action"),
                    "suggestion.action",
                ),
                "priority": priority,
                "evidence_refs": _agent_string_list(
                    item.get("evidence_refs"),
                    "suggestion.evidence_refs",
                ),
                "knowledge_refs": _agent_string_list(
                    item.get("knowledge_refs"),
                    "suggestion.knowledge_refs",
                ),
            }
        )
    return result


def _public_agent_review(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ReportDataValidationError("agent review must be an object")
    recommendation = value.get("recommendation")
    if recommendation not in _AGENT_RECOMMENDATIONS:
        raise ReportDataValidationError(
            "agent review recommendation is invalid"
        )
    return {
        "recommendation": recommendation,
        "confidence": _agent_number(
            value.get("confidence"),
            "review.confidence",
            minimum=0.0,
            maximum=1.0,
        ),
        "reasons": _agent_string_list(
            value.get("reasons"),
            "review.reasons",
        ),
    }


def _public_agent_evidence(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ReportDataValidationError(
            "agent evidence_refs must be an array"
        )
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ReportDataValidationError(
                "agent evidence_refs must contain objects"
            )
        evidence_type = item.get("type")
        if evidence_type not in _AGENT_EVIDENCE_TYPES:
            raise ReportDataValidationError(
                "agent evidence type is invalid"
            )
        public = {
            "ref_id": _agent_string(
                item.get("ref_id"),
                "evidence.ref_id",
            ),
            "type": evidence_type,
            "source_id": _agent_string(
                item.get("source_id"),
                "evidence.source_id",
            ),
        }
        if "timestamp" in item:
            public["timestamp"] = _agent_number(
                item["timestamp"],
                "evidence.timestamp",
                minimum=0.0,
            )
        if "class_name" in item:
            public["class_name"] = _agent_string(
                item["class_name"],
                "evidence.class_name",
            )
        if "confidence" in item:
            public["confidence"] = _agent_number(
                item["confidence"],
                "evidence.confidence",
                minimum=0.0,
                maximum=1.0,
            )
        if "value" in item:
            public["value"] = _copy_public_value(item["value"])
        result.append(public)
    return result


def _public_agent_detection(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReportDataValidationError(
            "explanation detections must contain objects"
        )
    track_id = value.get("track_id")
    if (
        track_id is not None
        and (
            isinstance(track_id, bool)
            or not isinstance(track_id, (str, int))
        )
    ):
        raise ReportDataValidationError(
            "detection.track_id has an invalid type"
        )
    observed = value.get("observed_frame_count")
    consecutive = value.get("consecutive_frame_count")
    if (
        isinstance(observed, bool)
        or not isinstance(observed, int)
        or observed < 0
    ):
        raise ReportDataValidationError(
            "observed_frame_count must be a non-negative integer"
        )
    if (
        consecutive is not None
        and (
            isinstance(consecutive, bool)
            or not isinstance(consecutive, int)
            or consecutive < 0
        )
    ):
        raise ReportDataValidationError(
            "consecutive_frame_count must be null or non-negative"
        )
    return {
        "class_name": _agent_string(
            value.get("class_name"),
            "detection.class_name",
        ),
        "track_id": track_id,
        "first_seen": _agent_optional_number(
            value.get("first_seen"),
            "detection.first_seen",
        ),
        "last_seen": _agent_optional_number(
            value.get("last_seen"),
            "detection.last_seen",
        ),
        "observed_frame_count": observed,
        "consecutive_frame_count": consecutive,
        "average_confidence": _agent_number(
            value.get("average_confidence"),
            "detection.average_confidence",
            minimum=0.0,
            maximum=1.0,
        ),
        "max_confidence": _agent_number(
            value.get("max_confidence"),
            "detection.max_confidence",
            minimum=0.0,
            maximum=1.0,
        ),
        "evidence_refs": _agent_string_list(
            value.get("evidence_refs"),
            "detection.evidence_refs",
        ),
    }


def _public_agent_explanation(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReportDataValidationError(
            "segment explanation must be an object"
        )
    time_range = value.get("time_range")
    detections = value.get("detections")
    if not isinstance(time_range, dict):
        raise ReportDataValidationError(
            "explanation.time_range must be an object"
        )
    if not isinstance(detections, list):
        raise ReportDataValidationError(
            "explanation.detections must be an array"
        )
    start = _agent_number(
        time_range.get("start"),
        "explanation.time_range.start",
        minimum=0.0,
    )
    end = _agent_number(
        time_range.get("end"),
        "explanation.time_range.end",
        minimum=0.0,
    )
    if start > end:
        raise ReportDataValidationError(
            "explanation time range is invalid"
        )
    return {
        "highlight_type": _agent_string(
            value.get("highlight_type"),
            "explanation.highlight_type",
        ),
        "trigger_rule": _agent_string(
            value.get("trigger_rule"),
            "explanation.trigger_rule",
        ),
        "time_range": {"start": start, "end": end},
        "detections": [
            _public_agent_detection(item) for item in detections
        ],
        "keyframe_refs": _agent_string_list(
            value.get("keyframe_refs"),
            "explanation.keyframe_refs",
        ),
        "detection_box_refs": _agent_string_list(
            value.get("detection_box_refs"),
            "explanation.detection_box_refs",
        ),
    }


def _public_boundary_suggestion(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReportDataValidationError(
            "boundary_suggestion must be an object"
        )
    action = value.get("action")
    if action not in _AGENT_BOUNDARY_ACTIONS:
        raise ReportDataValidationError(
            "boundary_suggestion action is invalid"
        )
    return {
        "action": action,
        "suggested_start": _agent_optional_number(
            value.get("suggested_start"),
            "boundary_suggestion.suggested_start",
        ),
        "suggested_end": _agent_optional_number(
            value.get("suggested_end"),
            "boundary_suggestion.suggested_end",
        ),
        "reason": _agent_string(
            value.get("reason"),
            "boundary_suggestion.reason",
        ),
    }


def _public_agent_comments(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ReportDataValidationError(
            "agent segment_comments must be an array"
        )
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ReportDataValidationError(
                "agent segment_comments must contain objects"
            )
        public: dict[str, Any] = {}
        for field in (
            "segment_id",
            "title",
            "comment",
            "score_reason",
        ):
            if field in item:
                public[field] = _agent_string(
                    item[field],
                    f"segment_comment.{field}",
                )
        if "review_status" in item:
            if item["review_status"] not in _AGENT_RECOMMENDATIONS:
                raise ReportDataValidationError(
                    "segment review_status is invalid"
                )
            public["review_status"] = item["review_status"]
        if "evidence_refs" in item:
            public["evidence_refs"] = _agent_string_list(
                item["evidence_refs"],
                "segment_comment.evidence_refs",
            )
        if "action_recommendation" in item:
            action = item["action_recommendation"]
            if action not in _AGENT_ACTION_RECOMMENDATIONS:
                raise ReportDataValidationError(
                    "segment action_recommendation is invalid"
                )
            public["action_recommendation"] = action
        if "explanation" in item:
            public["explanation"] = _public_agent_explanation(
                item["explanation"]
            )
        if "boundary_suggestion" in item:
            public["boundary_suggestion"] = _public_boundary_suggestion(
                item["boundary_suggestion"]
            )
        result.append(public)
    return result


def _public_agent_knowledge(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ReportDataValidationError(
            "agent knowledge_refs must be an array"
        )
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ReportDataValidationError(
                "agent knowledge_refs must contain objects"
            )
        result.append(
            {
                field: _agent_string(
                    item.get(field),
                    f"knowledge_ref.{field}",
                )
                for field in ("knowledge_id", "category", "title")
            }
        )
    return result


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
        if status not in {"completed", "degraded"}:
            return _empty_agent("invalid", call_statistics)
        summary = agent_report.get("summary")
        if summary is not None and not isinstance(summary, str):
            return _empty_agent("invalid", call_statistics)

        public_agent = {
            "availability": "ready",
            "status": status,
            "summary": summary,
            "tags": _public_agent_tags(agent_report.get("tags", [])),
            "suggestions": _public_agent_suggestions(
                agent_report.get("suggestions", [])
            ),
            "review": _public_agent_review(
                agent_report.get("review")
            ),
            "evidence_refs": _public_agent_evidence(
                agent_report.get("evidence_refs", [])
            ),
            "segment_comments": _public_agent_comments(
                agent_report.get("segment_comments")
            ),
            "knowledge_refs": _public_agent_knowledge(
                agent_report.get("knowledge_refs")
            ),
            "calls": copy.deepcopy(call_statistics),
        }
        _assert_no_private_data(public_agent)
        return public_agent
    except ReportDataValidationError:
        return _empty_agent("invalid", call_statistics)


def _assert_no_private_data(
    value: Any,
    *,
    allow_path_text: bool = False,
) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in _FORBIDDEN_KEYS:
                raise ReportDataValidationError(
                    "report data contains a private field"
                )
            _assert_no_private_data(
                item,
                allow_path_text=(key == "review_note"),
            )
        return
    if isinstance(value, list):
        for item in value:
            _assert_no_private_data(
                item,
                allow_path_text=allow_path_text,
            )
        return
    if isinstance(value, float) and not math.isfinite(value):
        raise ReportDataValidationError(
            "report data contains a non-finite number"
        )
    if not allow_path_text and isinstance(value, str) and (
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
