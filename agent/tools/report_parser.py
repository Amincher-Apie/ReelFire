"""Validate a CV report and expose only evidence-backed Agent facts."""

from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Any


JOB_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
SCORE_FIELDS = (
    "object_score",
    "scene_change_score",
    "motion_score",
    "highlight_score",
)


class ReportValidationError(ValueError):
    """Raised when an Agent input cannot be grounded in a valid CV report."""


def _require_dict(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReportValidationError(f"{field} 必须是 JSON 对象")
    return value


def _require_list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ReportValidationError(f"{field} 必须是数组")
    return value


def _require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReportValidationError(f"{field} 必须是非空字符串")
    return value.strip()


def _number(
    value: Any,
    field: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ReportValidationError(f"{field} 必须是数字")
    result = float(value)
    if not math.isfinite(result):
        raise ReportValidationError(f"{field} 必须是有限数字")
    if minimum is not None and result < minimum:
        raise ReportValidationError(f"{field} 不能小于 {minimum}")
    if maximum is not None and result > maximum:
        raise ReportValidationError(f"{field} 不能大于 {maximum}")
    return result


def _optional_score(item: dict[str, Any], field: str, owner: str) -> float:
    if field not in item:
        return 0.0
    return _number(item[field], f"{owner}.{field}")


def _round(value: float) -> float:
    return round(float(value), 6)


class ReportParserTool:
    """Convert an untrusted analysis report into a controlled visual summary."""

    name = "report_parser"

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload = _require_dict(payload, "payload")
        if payload.get("schema_version") != "1.0":
            raise ReportValidationError("schema_version 仅支持 1.0")

        job_id = _require_string(payload.get("job_id"), "job_id")
        if not JOB_ID_PATTERN.fullmatch(job_id):
            raise ReportValidationError("job_id 格式非法")

        provider = _require_dict(payload.get("provider"), "provider")
        provider_type = provider.get("type")
        if provider_type not in {"ollama", "dify", "coze", "rule_only"}:
            raise ReportValidationError("provider.type 不受支持")

        report = _require_dict(payload.get("analysis_report"), "analysis_report")
        report_job_id = report.get("job_id")
        if report_job_id is not None and report_job_id != job_id:
            raise ReportValidationError("analysis_report.job_id 与输入 job_id 不一致")

        duration = _number(
            report.get("duration"),
            "analysis_report.duration",
            minimum=0.000001,
        )
        total_sampled_frames = report.get("total_sampled_frames")
        if (
            isinstance(total_sampled_frames, bool)
            or not isinstance(total_sampled_frames, int)
            or total_sampled_frames < 0
        ):
            raise ReportValidationError(
                "analysis_report.total_sampled_frames 必须是非负整数"
            )

        keyframes = self._validate_keyframes(
            _require_list(report.get("keyframes"), "analysis_report.keyframes"),
            duration,
        )
        keyframe_ids = {item["id"] for item in keyframes}
        segments = self._validate_segments(
            _require_list(report.get("segments"), "analysis_report.segments"),
            duration,
            keyframe_ids,
        )

        raw_samples = report.get("samples")
        if raw_samples is None:
            samples: list[dict[str, Any]] = []
        else:
            samples = self._validate_frames(
                _require_list(raw_samples, "analysis_report.samples"),
                duration,
                "analysis_report.samples",
            )

        evidence_refs: list[dict[str, Any]] = [
            {
                "ref_id": "ev:report",
                "type": "report",
                "source_id": job_id,
                "value": {
                    "duration": _round(duration),
                    "total_sampled_frames": total_sampled_frames,
                },
            }
        ]

        primary_frames = samples or keyframes
        primary_prefix = "sample" if samples else "keyframe"
        primary_source_ids = [
            self._frame_source_id(frame, primary_prefix, index)
            for index, frame in enumerate(primary_frames)
        ]
        if len(primary_source_ids) != len(set(primary_source_ids)):
            raise ReportValidationError("analysis_report.samples.frame_index 不能重复")
        class_stats: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"count": 0, "max_confidence": 0.0, "evidence_refs": []}
        )
        metric_values = {field: [] for field in SCORE_FIELDS}
        object_counts: list[int] = []
        confidence_values: list[float] = []

        for index, frame in enumerate(primary_frames):
            source_id = primary_source_ids[index]
            timestamp = frame["timestamp"]
            object_counts.append(len(frame["objects"]))
            for field in SCORE_FIELDS:
                metric_values[field].append(float(frame[field]))

            score_ref = f"ev:score:{source_id}"
            evidence_refs.append(
                {
                    "ref_id": score_ref,
                    "type": "score",
                    "source_id": source_id,
                    "timestamp": timestamp,
                    "value": {
                        field: _round(frame[field]) for field in SCORE_FIELDS
                    },
                }
            )

            for detection_index, detected in enumerate(frame["objects"]):
                detection_ref = f"ev:detection:{source_id}:{detection_index:03d}"
                evidence = {
                    "ref_id": detection_ref,
                    "type": "detection",
                    "source_id": source_id,
                    "timestamp": timestamp,
                    "class_name": detected["class"],
                    "confidence": detected["confidence"],
                }
                if detected.get("bbox") is not None:
                    evidence["value"] = {"bbox": detected["bbox"]}
                evidence_refs.append(evidence)

                confidence_values.append(detected["confidence"])
                stats = class_stats[detected["class"]]
                stats["count"] += 1
                stats["max_confidence"] = max(
                    stats["max_confidence"],
                    detected["confidence"],
                )
                stats["evidence_refs"].append(detection_ref)

        keyframe_summary = []
        for item in keyframes:
            ref_id = f"ev:keyframe:{item['id']}"
            evidence_refs.append(
                {
                    "ref_id": ref_id,
                    "type": "keyframe",
                    "source_id": item["id"],
                    "timestamp": item["timestamp"],
                    "value": {"highlight_score": item["highlight_score"]},
                }
            )
            keyframe_summary.append(
                {
                    "id": item["id"],
                    "timestamp": item["timestamp"],
                    "highlight_score": item["highlight_score"],
                    "evidence_refs": [ref_id],
                }
            )

        segment_summary = []
        for item in segments:
            ref_id = f"ev:segment:{item['id']}"
            evidence_refs.append(
                {
                    "ref_id": ref_id,
                    "type": "segment",
                    "source_id": item["id"],
                    "value": {
                        "start": item["start"],
                        "end": item["end"],
                        "score": item["score"],
                        "source_keyframes": item["source_keyframes"],
                    },
                }
            )
            segment_summary.append({**item, "evidence_refs": [ref_id]})

        detected_classes = [
            {
                "name": class_name,
                "count": details["count"],
                "max_confidence": _round(details["max_confidence"]),
                "evidence_refs": details["evidence_refs"],
            }
            for class_name, details in sorted(
                class_stats.items(),
                key=lambda item: (-item[1]["count"], item[0]),
            )
        ]

        metrics = {
            "total_detections": sum(object_counts),
            "max_object_count": max(object_counts, default=0),
            "max_confidence": _round(max(confidence_values, default=0.0)),
            "min_confidence": _round(min(confidence_values, default=0.0)),
        }
        for field, values in metric_values.items():
            metrics[f"max_{field}"] = _round(max(values, default=0.0))
            metrics[f"average_{field}"] = _round(
                sum(values) / len(values) if values else 0.0
            )

        segment_tags = report.get("segment_tags")
        if not isinstance(segment_tags, dict):
            segment_tags = {}
        cover_prompt = report.get("ai_cover_prompt")
        if not isinstance(cover_prompt, str):
            cover_prompt = ""

        return {
            "schema_version": "1.0",
            "job_id": job_id,
            "provider": provider_type,
            "duration": _round(duration),
            "total_sampled_frames": total_sampled_frames,
            "source_frame_count": len(primary_frames),
            "keyframe_count": len(keyframes),
            "segment_count": len(segments),
            "detected_classes": detected_classes,
            "metrics": metrics,
            "keyframes": keyframe_summary,
            "segments": segment_summary,
            "evidence_refs": evidence_refs,
            "rule_baseline": {
                "segment_tags": segment_tags,
                "ai_cover_prompt": cover_prompt,
            },
        }

    def _validate_keyframes(
        self,
        raw_keyframes: list[Any],
        duration: float,
    ) -> list[dict[str, Any]]:
        keyframes = self._validate_frames(
            raw_keyframes,
            duration,
            "analysis_report.keyframes",
            require_id=True,
        )
        identifiers = [item["id"] for item in keyframes]
        if len(identifiers) != len(set(identifiers)):
            raise ReportValidationError("analysis_report.keyframes.id 不能重复")
        return keyframes

    def _validate_frames(
        self,
        raw_frames: list[Any],
        duration: float,
        owner: str,
        *,
        require_id: bool = False,
    ) -> list[dict[str, Any]]:
        frames = []
        for index, raw in enumerate(raw_frames):
            field = f"{owner}[{index}]"
            item = _require_dict(raw, field)
            timestamp = _number(
                item.get("timestamp"),
                f"{field}.timestamp",
                minimum=0,
                maximum=duration,
            )
            objects = self._validate_detections(
                _require_list(item.get("objects"), f"{field}.objects"),
                f"{field}.objects",
            )
            frame = {
                "timestamp": _round(timestamp),
                "objects": objects,
            }
            for score_field in SCORE_FIELDS:
                frame[score_field] = _round(
                    _optional_score(item, score_field, field)
                )
            if require_id:
                frame["id"] = _require_string(item.get("id"), f"{field}.id")
            elif "frame_index" in item:
                frame_index = item["frame_index"]
                if (
                    isinstance(frame_index, bool)
                    or not isinstance(frame_index, int)
                    or frame_index < 0
                ):
                    raise ReportValidationError(
                        f"{field}.frame_index 必须是非负整数"
                    )
                frame["frame_index"] = frame_index
            frames.append(frame)
        return frames

    def _validate_detections(
        self,
        raw_detections: list[Any],
        owner: str,
    ) -> list[dict[str, Any]]:
        detections = []
        for index, raw in enumerate(raw_detections):
            field = f"{owner}[{index}]"
            item = _require_dict(raw, field)
            detected = {
                "class": _require_string(item.get("class"), f"{field}.class"),
                "confidence": _round(
                    _number(
                        item.get("confidence"),
                        f"{field}.confidence",
                        minimum=0,
                        maximum=1,
                    )
                ),
            }
            if "bbox" in item:
                bbox = _require_list(item["bbox"], f"{field}.bbox")
                if len(bbox) != 4:
                    raise ReportValidationError(f"{field}.bbox 必须包含 4 个数字")
                detected["bbox"] = [
                    _round(_number(value, f"{field}.bbox[{position}]"))
                    for position, value in enumerate(bbox)
                ]
            detections.append(detected)
        return detections

    def _validate_segments(
        self,
        raw_segments: list[Any],
        duration: float,
        keyframe_ids: set[str],
    ) -> list[dict[str, Any]]:
        segments = []
        identifiers: set[str] = set()
        for index, raw in enumerate(raw_segments):
            field = f"analysis_report.segments[{index}]"
            item = _require_dict(raw, field)
            identifier = _require_string(item.get("id"), f"{field}.id")
            if identifier in identifiers:
                raise ReportValidationError("analysis_report.segments.id 不能重复")
            identifiers.add(identifier)
            start = _number(item.get("start"), f"{field}.start", minimum=0)
            end = _number(
                item.get("end"),
                f"{field}.end",
                minimum=0.000001,
                maximum=duration,
            )
            if start >= end:
                raise ReportValidationError(f"{field} 必须满足 start < end")
            score = _optional_score(item, "score", field)
            source_keyframes = item.get("source_keyframes", [])
            source_keyframes = _require_list(
                source_keyframes,
                f"{field}.source_keyframes",
            )
            normalized_sources = []
            for source_index, source in enumerate(source_keyframes):
                source_id = _require_string(
                    source,
                    f"{field}.source_keyframes[{source_index}]",
                )
                if source_id not in keyframe_ids:
                    raise ReportValidationError(
                        f"{field}.source_keyframes 引用了不存在的关键帧"
                    )
                normalized_sources.append(source_id)
            segments.append(
                {
                    "id": identifier,
                    "start": _round(start),
                    "end": _round(end),
                    "score": _round(score),
                    "source_keyframes": normalized_sources,
                }
            )
        return segments

    @staticmethod
    def _frame_source_id(
        frame: dict[str, Any],
        prefix: str,
        index: int,
    ) -> str:
        if prefix == "keyframe":
            return frame["id"]
        if "frame_index" in frame:
            return f"sample_{frame['frame_index']:06d}"
        return f"sample_{index:06d}"
