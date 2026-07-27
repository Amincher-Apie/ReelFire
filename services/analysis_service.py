"""Background execution and CV integration for FPS highlight extraction."""

from __future__ import annotations

import logging
import math
import threading
import time
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from cv_engine.model_registry import ModelRegistry
from services.job_service import JobService, JobStateConflictError, iso_now

if TYPE_CHECKING:
    import numpy as np


LOGGER = logging.getLogger(__name__)


def _bounded_clip(center: float, duration: float, target_duration: float) -> tuple[float, float]:
    """Return a target-length clip while keeping it inside the source video."""
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("视频时长无效，无法生成推荐片段")
    length = min(max(float(target_duration), 0.1), duration)
    # FPS highlights benefit from more post-event time, so use 40/60 pre/post.
    start = center - length * 0.4
    start = min(max(start, 0.0), duration - length)
    end = start + length
    return round(start, 3), round(min(end, duration), 3)


def _select_keyframes(
    samples: list[dict[str, Any]],
    maximum: int,
    minimum_gap: float,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for sample in sorted(samples, key=lambda item: item["highlight_score"], reverse=True):
        if all(
            abs(float(sample["timestamp"]) - float(existing["timestamp"]))
            >= minimum_gap
            for existing in selected
        ):
            selected.append(sample)
        if len(selected) >= maximum:
            break
    if not selected and samples:
        selected.append(max(samples, key=lambda item: item["highlight_score"]))
    return selected


def _segments_overlap(
    first: dict[str, Any],
    second: dict[str, Any],
) -> bool:
    def bounds(segment: dict[str, Any]) -> tuple[float, float]:
        tracking = segment.get("tracking")
        boundary = (
            tracking.get("boundary")
            if isinstance(tracking, dict)
            else None
        )
        if isinstance(boundary, dict):
            return (
                float(boundary.get("original_start", segment["start"])),
                float(boundary.get("original_end", segment["end"])),
            )
        return float(segment["start"]), float(segment["end"])

    first_start, first_end = bounds(first)
    second_start, second_end = bounds(second)
    return (
        max(first_start, second_start)
        < min(first_end, second_end) - 1e-6
    )


def _merge_tracking_payloads(
    first: object,
    second: object,
    refined_start: float,
    refined_end: float,
) -> dict[str, Any] | None:
    payloads = [
        payload
        for payload in (first, second)
        if isinstance(payload, dict)
    ]
    if not payloads:
        return None
    tracks: list[dict[str, Any]] = []
    seen_track_keys: set[str] = set()
    scope_ids: list[str] = []
    original_starts: list[float] = []
    original_ends: list[float] = []
    for payload in payloads:
        payload_scope_ids = list(payload.get("scope_ids", []))
        payload_scope_ids.append(payload.get("scope_id", ""))
        for raw_scope_id in payload_scope_ids:
            scope_id = str(raw_scope_id).strip()
            if scope_id and scope_id not in scope_ids:
                scope_ids.append(scope_id)
        scope_id = str(payload.get("scope_id", "")).strip()
        boundary = payload.get("boundary")
        if isinstance(boundary, dict):
            original_starts.append(
                float(boundary.get("original_start", refined_start))
            )
            original_ends.append(
                float(boundary.get("original_end", refined_end))
            )
        for track in payload.get("tracks", []):
            if not isinstance(track, dict):
                continue
            track_key = str(
                track.get("track_key")
                or f"{scope_id}:{track.get('track_id', 0)}"
            )
            if track_key in seen_track_keys:
                continue
            seen_track_keys.add(track_key)
            tracks.append(dict(track))
    status = "completed" if tracks else str(
        payloads[0].get("status", "no_enemy_tracks")
    )
    return {
        "status": status,
        "mode": "per_window_detection_association",
        "scope_ids": scope_ids,
        "tracks": tracks,
        "refined": any(
            bool(payload.get("refined"))
            for payload in payloads
        ),
        "boundary": {
            "original_start": round(
                min(original_starts or [refined_start]),
                3,
            ),
            "original_end": round(
                max(original_ends or [refined_end]),
                3,
            ),
            "refined_start": round(refined_start, 3),
            "refined_end": round(refined_end, 3),
        },
    }


def _source_segment_ids(segment: dict[str, Any]) -> list[str]:
    raw_values = segment.get("source_segment_ids", [])
    if not isinstance(raw_values, list):
        raw_values = []
    values = [
        str(value).strip()
        for value in raw_values
        if str(value).strip()
    ]
    segment_id = str(segment.get("id", "")).strip()
    if segment_id:
        values.append(segment_id)
    return list(dict.fromkeys(values))


def _merge_overlapping_segments(
    segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Take the transitive time union of every positively overlapping segment."""

    merged: list[dict[str, Any]] = []
    for segment in sorted(
        (dict(item) for item in segments),
        key=lambda item: (
            float(item.get("start", 0.0)),
            float(item.get("end", 0.0)),
            str(item.get("id", "")),
        ),
    ):
        segment["source_segment_ids"] = _source_segment_ids(segment)
        if not merged or not _segments_overlap(merged[-1], segment):
            segment["duration"] = round(
                float(segment["end"]) - float(segment["start"]),
                3,
            )
            merged.append(segment)
            continue

        current = merged[-1]
        current_id = str(current.get("id", "")).strip()
        current_sources = _source_segment_ids(current)
        incoming_sources = _source_segment_ids(segment)
        union_start = min(
            float(current["start"]),
            float(segment["start"]),
        )
        union_end = max(
            float(current["end"]),
            float(segment["end"]),
        )
        source_keyframes = list(current.get("source_keyframes", [])) + list(
            segment.get("source_keyframes", [])
        )
        current_score = float(current.get("score", 0.0))
        incoming_score = float(segment.get("score", 0.0))
        merged_tracking = _merge_tracking_payloads(
            current.get("tracking"),
            segment.get("tracking"),
            union_start,
            union_end,
        )
        if incoming_score > current_score:
            preferred = dict(segment)
            preferred["id"] = current_id or str(segment.get("id", ""))
            current.clear()
            current.update(preferred)
        current["start"] = round(
            union_start,
            3,
        )
        current["end"] = round(
            union_end,
            3,
        )
        current["duration"] = round(
            float(current["end"]) - float(current["start"]),
            3,
        )
        current["score"] = round(max(current_score, incoming_score), 4)
        current["reason"] = "overlap_union"
        current["source_segment_ids"] = list(
            dict.fromkeys(current_sources + incoming_sources)
        )
        current["source_keyframes"] = list(
            dict.fromkeys(
                [
                    str(value)
                    for value in source_keyframes
                    if str(value)
                ]
            )
        )
        if merged_tracking is not None:
            current["tracking"] = merged_tracking
            evidence = current.get("evidence")
            if not isinstance(evidence, dict):
                evidence = {}
                current["evidence"] = evidence
            evidence["tracks"] = [
                {
                    key: track[key]
                    for key in (
                        "track_key",
                        "track_id",
                        "scope_id",
                        "class",
                        "first_seen",
                        "last_seen",
                        "duration",
                        "hit_count",
                        "average_confidence",
                        "max_confidence",
                    )
                    if key in track
                }
                for track in merged_tracking["tracks"]
            ]
            evidence["tracking_boundary"] = merged_tracking["boundary"]
    return merged


def _agent_segment_id(segment: dict[str, Any]) -> str:
    sources = _source_segment_ids(segment)
    seed = sources[0] if sources else str(segment.get("id", "candidate"))
    return f"seg_union_{seed}"[:100]


def _published_window_segments(
    segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    published = _merge_overlapping_segments(segments)
    for order, segment in enumerate(published, start=1):
        sources = _source_segment_ids(segment)
        segment["id"] = _agent_segment_id(segment)
        segment["order"] = order
        segment["provisional"] = True
        if len(sources) >= 2:
            segment["source"] = "merged"
            segment["source_segment_ids"] = sources
        else:
            segment["source"] = "cv"
            segment["source_segment_ids"] = []
    return published


def _reconcile_window_segments(
    segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge overlapping-window results and assign stable final IDs."""

    kept = _merge_overlapping_segments(segments)
    for index, segment in enumerate(kept, start=1):
        sources = _source_segment_ids(segment)
        segment["agent_segment_id"] = _agent_segment_id(segment)
        segment["id"] = f"seg_{index:03d}"
        segment["order"] = index
        if len(sources) >= 2:
            segment["source"] = "merged"
            segment["source_segment_ids"] = sources
        else:
            segment["source"] = "cv"
            segment["source_segment_ids"] = []
    return kept


def _bounded_tracking_points(
    points: list[dict[str, Any]],
    maximum: int,
) -> list[dict[str, Any]]:
    if maximum <= 0 or len(points) <= maximum:
        return points
    if maximum == 1:
        return [points[-1]]
    last = len(points) - 1
    indexes = {
        round(index * last / (maximum - 1))
        for index in range(maximum)
    }
    return [points[index] for index in sorted(indexes)]


def _associate_window_detections(
    detector: Any,
    detection_frames: list[list[dict[str, Any]]],
    settings: dict[str, Any],
    scope_id: str,
    sample_interval: float,
) -> tuple[list[list[dict[str, Any]]], dict[str, Any]]:
    copied_frames = [
        [
            {
                key: value
                for key, value in detection.items()
                if key != "track_id"
            }
            for detection in detections
        ]
        for detections in detection_frames
    ]
    raw_enabled = settings.get("tracking_enabled", True)
    enabled = (
        raw_enabled
        if isinstance(raw_enabled, bool)
        else str(raw_enabled).strip().lower()
        not in {"0", "false", "no", "off"}
    )
    summary = {
        "enabled": enabled,
        "status": "disabled" if not enabled else "pending",
        "mode": "per_window_detection_association",
        "scope_id": scope_id,
        "frame_count": len(copied_frames),
        "sample_interval": round(sample_interval, 4),
    }
    if not enabled:
        return copied_frames, summary
    associate = getattr(detector, "associate_detections", None)
    if not callable(associate):
        summary["status"] = "unsupported"
        return copied_frames, summary
    try:
        associated = associate(
            copied_frames,
            tracker=str(
                settings.get("tracking_tracker", "bytetrack.yaml")
            ),
            sample_fps=1.0 / max(0.001, sample_interval),
            track_buffer_seconds=max(
                0.1,
                float(
                    settings.get(
                        "tracking_track_buffer_seconds",
                        2.0,
                    )
                ),
            ),
        )
        if len(associated) != len(copied_frames):
            raise RuntimeError(
                "ByteTrack output count does not match the window frames"
            )
        summary["status"] = "completed"
        summary["tracked_detection_count"] = sum(
            1
            for detections in associated
            for detection in detections
            if detection.get("track_id") is not None
        )
        return associated, summary
    except Exception as exc:
        LOGGER.exception(
            "Window tracking failed for scope %s",
            scope_id,
        )
        summary["status"] = "failed"
        summary["reason"] = type(exc).__name__
        return copied_frames, summary


def _refine_window_segments_with_tracking(
    segments: list[dict[str, Any]],
    samples: list[dict[str, Any]],
    duration: float,
    enemy_classes: set[str] | None,
    settings: dict[str, Any],
    association: dict[str, Any],
) -> dict[str, Any]:
    summary = {
        **association,
        "candidate_segment_count": len(segments),
        "refined_segment_count": 0,
        "track_count": 0,
        "point_count": 0,
    }
    scope_id = str(association.get("scope_id", "window"))
    association_status = str(association.get("status", "unsupported"))
    if not segments:
        return summary

    normalized_enemy_classes = {
        str(class_name).strip().lower()
        for class_name in (
            enemy_classes
            or {"character_ct", "character_t", "enemy"}
        )
        if str(class_name).strip()
    }
    min_hits = max(2, int(settings.get("tracking_min_hits", 2)))
    margin = max(
        0.0,
        float(settings.get("tracking_margin_seconds", 2.0)),
    )
    pre_roll = max(
        0.0,
        float(settings.get("tracking_pre_roll_seconds", 1.0)),
    )
    post_roll = max(
        0.0,
        float(settings.get("tracking_post_roll_seconds", 1.5)),
    )
    min_clip = max(
        0.1,
        float(settings.get("tracking_min_clip_seconds", 3.0)),
    )
    max_points = max(
        2,
        int(settings.get("tracking_max_points_per_track", 120)),
    )
    ordered = sorted(
        segments,
        key=lambda item: (
            float(item.get("start", 0.0)),
            float(item.get("end", 0.0)),
        ),
    )
    originals = [
        (
            max(0.0, float(segment.get("start", 0.0))),
            min(duration, float(segment.get("end", duration))),
        )
        for segment in ordered
    ]

    for index, segment in enumerate(ordered):
        original_start, original_end = originals[index]
        base_tracking = {
            "status": association_status,
            "mode": "per_window_detection_association",
            "scope_id": scope_id,
            "sample_interval": association.get("sample_interval"),
            "tracks": [],
            "refined": False,
            "boundary": {
                "original_start": round(original_start, 3),
                "original_end": round(original_end, 3),
                "refined_start": round(original_start, 3),
                "refined_end": round(original_end, 3),
            },
        }
        segment["tracking"] = base_tracking
        if association_status != "completed":
            continue

        scan_start = max(0.0, original_start - margin)
        scan_end = min(duration, original_end + margin)
        raw_tracks: dict[tuple[str, int], dict[str, Any]] = {}
        for sample in samples:
            timestamp = float(sample.get("timestamp", -1.0))
            if not scan_start <= timestamp <= scan_end:
                continue
            for detection in sample.get("objects", []):
                track_id = detection.get("track_id")
                class_name = str(
                    detection.get("class", "")
                ).strip()
                bbox = detection.get("bbox")
                if (
                    track_id is None
                    or class_name.lower() not in normalized_enemy_classes
                    or not isinstance(bbox, list)
                    or len(bbox) != 4
                ):
                    continue
                try:
                    normalized_track_id = int(track_id)
                    x1, y1, x2, y2 = (
                        float(value) for value in bbox
                    )
                    confidence = float(
                        detection.get("confidence", 0.0)
                    )
                except (TypeError, ValueError):
                    continue
                key = (class_name, normalized_track_id)
                track = raw_tracks.setdefault(
                    key,
                    {
                        "track_key": (
                            f"{scope_id}:{class_name}:"
                            f"{normalized_track_id}"
                        ),
                        "track_id": normalized_track_id,
                        "scope_id": scope_id,
                        "class": class_name,
                        "first_seen": timestamp,
                        "last_seen": timestamp,
                        "confidence_total": 0.0,
                        "max_confidence": 0.0,
                        "hit_count": 0,
                        "points": [],
                    },
                )
                track["first_seen"] = min(
                    float(track["first_seen"]),
                    timestamp,
                )
                track["last_seen"] = max(
                    float(track["last_seen"]),
                    timestamp,
                )
                track["confidence_total"] += confidence
                track["max_confidence"] = max(
                    float(track["max_confidence"]),
                    confidence,
                )
                track["hit_count"] += 1
                track["points"].append(
                    {
                        "timestamp": round(timestamp, 3),
                        "x": round(x1, 2),
                        "y": round(y1, 2),
                        "w": round(max(0.0, x2 - x1), 2),
                        "h": round(max(0.0, y2 - y1), 2),
                    }
                )

        stable_tracks: list[dict[str, Any]] = []
        for track in raw_tracks.values():
            hit_count = int(track["hit_count"])
            if hit_count < min_hits:
                continue
            confidence_total = float(track.pop("confidence_total"))
            track["points"] = _bounded_tracking_points(
                track["points"],
                max_points,
            )
            track["first_seen"] = round(
                float(track["first_seen"]),
                3,
            )
            track["last_seen"] = round(
                float(track["last_seen"]),
                3,
            )
            track["duration"] = round(
                float(track["last_seen"])
                - float(track["first_seen"]),
                3,
            )
            track["average_confidence"] = round(
                confidence_total / hit_count,
                4,
            )
            track["max_confidence"] = round(
                float(track["max_confidence"]),
                4,
            )
            stable_tracks.append(track)
        stable_tracks.sort(
            key=lambda item: (
                float(item["first_seen"]),
                int(item["track_id"]),
            )
        )
        if not stable_tracks:
            base_tracking["status"] = "no_enemy_tracks"
            continue

        left_bound = (
            0.0
            if index == 0
            else (originals[index - 1][1] + original_start) / 2.0
        )
        right_bound = (
            duration
            if index + 1 == len(originals)
            else (original_end + originals[index + 1][0]) / 2.0
        )
        first_seen = min(
            float(track["first_seen"]) for track in stable_tracks
        )
        last_seen = max(
            float(track["last_seen"]) for track in stable_tracks
        )
        refined_start = max(left_bound, first_seen - pre_roll)
        refined_end = min(right_bound, last_seen + post_roll)
        target_length = min(
            min_clip,
            max(0.0, right_bound - left_bound),
        )
        if refined_end - refined_start < target_length:
            center = (refined_start + refined_end) / 2.0
            refined_start = max(
                left_bound,
                center - target_length / 2.0,
            )
            refined_end = refined_start + target_length
            if refined_end > right_bound:
                refined_end = right_bound
                refined_start = refined_end - target_length
        refined_start = round(max(0.0, refined_start), 3)
        refined_end = round(min(duration, refined_end), 3)
        if refined_end <= refined_start:
            continue

        segment["start"] = refined_start
        segment["end"] = refined_end
        segment["duration"] = round(
            refined_end - refined_start,
            3,
        )
        segment["reason"] = "tracked_enemy_engagement"
        base_tracking.update(
            {
                "status": "completed",
                "tracks": stable_tracks,
                "refined": (
                    abs(refined_start - original_start) > 1e-3
                    or abs(refined_end - original_end) > 1e-3
                ),
                "boundary": {
                    "original_start": round(original_start, 3),
                    "original_end": round(original_end, 3),
                    "enemy_first_seen": round(first_seen, 3),
                    "enemy_last_seen": round(last_seen, 3),
                    "refined_start": refined_start,
                    "refined_end": refined_end,
                },
            }
        )
        if base_tracking["refined"]:
            summary["refined_segment_count"] += 1
        summary["track_count"] += len(stable_tracks)
        summary["point_count"] += sum(
            len(track["points"]) for track in stable_tracks
        )
        evidence = segment.get("evidence")
        if not isinstance(evidence, dict):
            evidence = {}
            segment["evidence"] = evidence
        evidence["tracks"] = [
            {
                key: track[key]
                for key in (
                    "track_key",
                    "track_id",
                    "scope_id",
                    "class",
                    "first_seen",
                    "last_seen",
                    "duration",
                    "hit_count",
                    "average_confidence",
                    "max_confidence",
                )
            }
            for track in stable_tracks
        ]
        evidence["tracking_boundary"] = base_tracking["boundary"]
    return summary


def _annotate_frame(frame: np.ndarray, objects: list[dict[str, Any]]) -> np.ndarray:
    """Draw YOLO boxes on a copy of a frame for human-verifiable evidence."""
    import cv2

    annotated = frame.copy()
    for detected in objects:
        bbox = detected.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue
        try:
            x1, y1, x2, y2 = (int(round(float(value))) for value in bbox)
        except (TypeError, ValueError):
            continue
        x1 = max(0, min(x1, annotated.shape[1] - 1))
        x2 = max(0, min(x2, annotated.shape[1] - 1))
        y1 = max(0, min(y1, annotated.shape[0] - 1))
        y2 = max(0, min(y2, annotated.shape[0] - 1))
        if x2 <= x1 or y2 <= y1:
            continue
        label = str(detected.get("class", "object"))
        confidence = detected.get("confidence")
        if isinstance(confidence, (int, float)):
            label = f"{label} {float(confidence):.2f}"
        cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 80), 2)
        (text_width, text_height), _ = cv2.getTextSize(
            label,
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            1,
        )
        text_top = max(0, y1 - text_height - 8)
        cv2.rectangle(
            annotated,
            (x1, text_top),
            (min(annotated.shape[1] - 1, x1 + text_width + 8), y1),
            (0, 255, 80),
            -1,
        )
        cv2.putText(
            annotated,
            label,
            (x1 + 4, max(text_height + 1, y1 - 5)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (10, 20, 10),
            1,
            cv2.LINE_AA,
        )
    return annotated


def _save_contact_sheet(
    selected: list[dict[str, Any]],
    frames: list[np.ndarray],
    destination: Path,
) -> bool:
    import cv2
    import numpy as np

    if not selected:
        return False
    thumb_width, thumb_height, columns = 320, 180, 3
    rows = math.ceil(len(selected) / columns)
    sheet = np.zeros((rows * thumb_height, columns * thumb_width, 3), dtype=np.uint8)
    for index, item in enumerate(selected):
        frame = _annotate_frame(
            frames[int(item["frame_index"])],
            item.get("objects", []),
        )
        thumb = cv2.resize(frame, (thumb_width, thumb_height))
        cv2.putText(
            thumb,
            f"{item['timestamp']:.1f}s  score={item['highlight_score']:.3f}",
            (8, 22),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        row, column = divmod(index, columns)
        sheet[
            row * thumb_height : (row + 1) * thumb_height,
            column * thumb_width : (column + 1) * thumb_width,
        ] = thumb
    destination.parent.mkdir(parents=True, exist_ok=True)
    return bool(cv2.imwrite(str(destination), sheet))


def _save_contact_sheet_from_keyframes(
    keyframes: list[dict[str, Any]],
    job_dir: Path,
    destination: Path,
) -> bool:
    """Build a bounded contact sheet from already persisted keyframes."""

    import cv2
    import numpy as np

    if not keyframes:
        return False
    visible = keyframes[:24]
    thumb_width, thumb_height, columns = 320, 180, 3
    rows = math.ceil(len(visible) / columns)
    sheet = np.zeros(
        (rows * thumb_height, columns * thumb_width, 3),
        dtype=np.uint8,
    )
    written = 0
    for index, item in enumerate(visible):
        image = cv2.imread(str(job_dir / str(item.get("image", ""))))
        if image is None:
            continue
        thumb = cv2.resize(image, (thumb_width, thumb_height))
        cv2.putText(
            thumb,
            f"{float(item.get('timestamp', 0.0)):.1f}s  "
            f"score={float(item.get('highlight_score', 0.0)):.3f}",
            (8, 22),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        row, column = divmod(index, columns)
        sheet[
            row * thumb_height : (row + 1) * thumb_height,
            column * thumb_width : (column + 1) * thumb_width,
        ] = thumb
        written += 1
    destination.parent.mkdir(parents=True, exist_ok=True)
    return written > 0 and bool(cv2.imwrite(str(destination), sheet))


def _save_segment_thumbnail(
    video_path: Path,
    timestamp: float,
    objects: list[dict[str, Any]],
    destination: Path,
) -> bool:
    """Seek one source frame so streaming analysis never retains old chunks."""
    import cv2

    capture = cv2.VideoCapture(str(video_path))
    try:
        if not capture.isOpened():
            return False
        capture.set(cv2.CAP_PROP_POS_MSEC, max(0.0, timestamp) * 1000.0)
        ok, frame = capture.read()
        if not ok:
            return False
        destination.parent.mkdir(parents=True, exist_ok=True)
        return bool(
            cv2.imwrite(
                str(destination),
                _annotate_frame(frame, objects),
            )
        )
    finally:
        capture.release()


def _notify_progress(
    callback: Callable[[dict[str, Any]], None] | None,
    payload: dict[str, Any],
) -> None:
    if callback is not None:
        callback(deepcopy(payload))


def analyze_video(
    video_path: Path,
    job_dir: Path,
    settings: dict[str, Any],
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    model_registry: ModelRegistry | None = None,
    segment_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run bounded chunk sampling, YOLO detection and explainable scoring."""
    import cv2

    from cv_engine.highlight_extractor import HighlightExtractor
    from cv_engine.highlight_scorer import HighlightScorer
    from cv_engine.video_processor import VideoProcessor
    from cv_engine.yolo_detector import YoloDetector

    processor = VideoProcessor()
    video = processor.get_video_info(video_path)
    duration = float(video.get("duration", 0.0))
    if duration <= 0 or int(video.get("width", 0)) <= 0:
        raise ValueError("无法读取视频信息，文件可能已损坏或不受支持")

    from cv_engine.candidate_selector import build_overlapping_windows

    analysis_started = time.monotonic()

    def notify(payload: dict[str, Any]) -> None:
        elapsed = max(0.0, time.monotonic() - analysis_started)
        value = dict(payload)
        percent = float(value.get("percent", 0.0))
        value["elapsed_seconds"] = round(elapsed, 1)
        if "eta_seconds" not in value:
            value["eta_seconds"] = (
                round(elapsed * (100.0 - percent) / percent, 1)
                if elapsed >= 2.0 and 1.0 < percent < 100.0
                else None
            )
        _notify_progress(progress_callback, value)

    sample_interval = max(0.1, float(settings.get("sample_interval", 0.5)))
    chunk_duration = max(5.0, float(settings.get("chunk_duration", 60.0)))
    keyframes_per_chunk = max(
        1,
        int(settings.get("keyframes_per_chunk", 4)),
    )
    analysis_width = max(320, int(settings.get("analysis_width", 640)))
    two_stage_min_duration = max(
        60.0,
        float(settings.get("two_stage_min_duration", 300.0)),
    )
    use_candidate_pipeline = duration >= two_stage_min_duration
    candidate_duration = duration
    progress_base_samples = 0

    if use_candidate_pipeline:
        streaming_window_duration = max(
            30.0,
            float(settings.get("streaming_window_duration", 60.0)),
        )
        streaming_window_stride = min(
            streaming_window_duration,
            max(
                10.0,
                float(settings.get("streaming_window_stride", 30.0)),
            ),
        )
        candidate_windows = build_overlapping_windows(
            duration,
            window_duration=streaming_window_duration,
            stride=streaming_window_stride,
        )
        estimated_samples = max(1, math.ceil(duration / sample_interval))
        candidate_duration = duration
        analysis_mode = "streaming_staggered_windows_v6"
    else:
        streaming_window_duration = chunk_duration
        streaming_window_stride = chunk_duration
        candidate_windows = [
            {
                "index": index,
                "start": round(index * chunk_duration, 3),
                "end": round(min(duration, (index + 1) * chunk_duration), 3),
                "score": None,
                "reason": "full_scan",
            }
            for index in range(max(1, math.ceil(duration / chunk_duration)))
        ]
        estimated_samples = max(1, math.ceil(duration / sample_interval))
        chunk_source = processor.iter_sample_chunks(
            video_path,
            interval=sample_interval,
            chunk_duration=chunk_duration,
            max_width=analysis_width,
        )
        analysis_mode = "streaming_chunks"

    total_chunks = len(candidate_windows)
    chunk_queue: list[dict[str, Any]] = [
        {
            "id": f"chunk_{index + 1:04d}",
            "index": index + 1,
            "start": round(float(window["start"]), 3),
            "end": round(float(window["end"]), 3),
            "candidate_score": window.get("score"),
            "queue": window.get("queue"),
            "queue_index": window.get("queue_index"),
            "status": "queued",
            "sample_count": 0,
            "keyframes": [],
            "keyframe_ids": [],
            "provisional_segments": [],
            "segment_ids": [],
        }
        for index, window in enumerate(candidate_windows)
    ]

    game_type = str(settings.get("game_type", "other")).lower().strip()
    model_info = None
    is_fallback = False
    highlight_strategy = "enemy_engagement"
    enemy_classes: set[str] | None = None
    if model_registry is not None:
        model_info, strategy, is_fallback = (
            model_registry.resolve_by_game_type(game_type)
        )
        model_path = model_info.model_path
        enemy_classes = set(strategy.get("enemy_classes", set()))
        highlight_strategy = str(
            strategy.get("highlight_strategy", "generic_score")
        )
    else:
        model_path = Path(
            str(settings.get("model_path", "models/yolo11n.pt"))
        )
    detector = YoloDetector(
        model_path,
        confidence_threshold=float(settings.get("confidence_threshold", 0.35)),
        batch_size=int(settings.get("yolo_batch_size", 8)),
        image_size=analysis_width,
    )
    scorer = HighlightScorer()

    object_weight = float(settings.get("object_weight", 0.45))
    scene_weight = float(settings.get("scene_change_weight", 0.35))
    motion_weight = float(settings.get("motion_weight", 0.20))
    samples: list[dict[str, Any]] = []
    keyframes: list[dict[str, Any]] = []
    analysis_chunks: list[dict[str, Any]] = []
    previous = None
    processed_samples = 0
    keyframe_dir = job_dir / "keyframes"
    keyframe_dir.mkdir(parents=True, exist_ok=True)
    minimum_gap = max(
        0.0,
        float(settings.get("min_keyframe_gap", 5.0)),
    )
    sample_cache: dict[float, dict[str, Any]] = {}
    window_segments: list[dict[str, Any]] = []
    published_segments: list[dict[str, Any]] = []
    agent_dispatched_ids: set[str] = set()
    tracking_report: dict[str, Any] = {
        "enabled": True,
        "status": "pending",
        "mode": "per_window_detection_association",
        "window_count": 0,
        "completed_window_count": 0,
        "failed_window_count": 0,
        "candidate_segment_count": 0,
        "refined_segment_count": 0,
        "track_count": 0,
        "point_count": 0,
        "windows": [],
    }

    def provisional_snapshot() -> list[dict[str, Any]]:
        snapshots = []
        for segment in published_segments:
            snapshot = {
                key: segment.get(key)
                for key in (
                    "id",
                    "order",
                    "start",
                    "end",
                    "duration",
                    "score",
                    "reason",
                    "chunk_id",
                    "provisional",
                    "source_keyframes",
                    "source",
                    "source_segment_ids",
                    "evidence",
                    "tracking",
                )
            }
            snapshot["source_segment_ids"] = [
                source_id
                for source_id in snapshot.get("source_segment_ids", [])
                if source_id != snapshot.get("id")
            ]
            snapshots.append(snapshot)
        return snapshots

    def dispatch_agent_segment(segment: dict[str, Any]) -> None:
        if segment_callback is None:
            return
        segment_id = str(segment.get("id", "")).strip()
        if not segment_id or segment_id in agent_dispatched_ids:
            return
        segment_samples = [
            dict(item)
            for item in samples
            if float(segment["start"])
            <= float(item["timestamp"])
            <= float(segment["end"])
        ]
        segment_keyframes = [
            dict(keyframe)
            for keyframe in keyframes
            if float(segment["start"])
            <= float(keyframe["timestamp"])
            <= float(segment["end"])
        ]
        try:
            segment_callback(
                {
                    "duration": duration,
                    "total_sampled_frames": len(segment_samples),
                    "samples": segment_samples,
                    "keyframes": segment_keyframes,
                    "segments": [dict(segment)],
                    "segment_tags": {},
                    "ai_cover_prompt": "",
                }
            )
            agent_dispatched_ids.add(segment_id)
        except Exception:
            LOGGER.exception(
                "Failed to enqueue merged Agent segment %s",
                segment_id,
            )

    def iter_candidate_chunks():
        for window in candidate_windows:
            window_index = int(window["index"])
            decoded = next(
                processor.iter_sample_windows(
                    video_path,
                    [window],
                    interval=sample_interval,
                    max_width=analysis_width,
                    preserve_order=True,
                )
            )
            decoded["index"] = window_index
            decoded["candidate_score"] = window.get("score")
            decoded["queue"] = window.get("queue")
            decoded["queue_index"] = window.get("queue_index")
            yield decoded

    if use_candidate_pipeline:
        chunk_source = iter_candidate_chunks()

    notify(
        {
            "stage": "sampling",
            "message": (
                f"已规划 {total_chunks} 个重叠逻辑窗口；"
                "正在直接启动首个 q1 YOLO 窗口"
                if use_candidate_pipeline
                else "正在读取视频并准备分块分析"
            ),
            "percent": 2.0,
            "total_chunks": total_chunks,
            "completed_chunks": 0,
            "processed_frames": progress_base_samples,
            "total_frames": estimated_samples,
            "current_chunk": None,
            "chunks": chunk_queue,
            "candidate_duration_seconds": round(candidate_duration, 3),
            "candidate_coverage_ratio": round(
                candidate_duration / duration,
                4,
            ),
            "provisional_segment_count": 0,
            "provisional_keyframe_count": 0,
            "eta_seconds": None,
            "video": video,
        }
    )

    detection_started = time.monotonic()
    for chunk in chunk_source:
        chunk_index = int(chunk["index"])
        chunk_number = chunk_index + 1
        chunk_id = f"chunk_{chunk_number:04d}"
        frames = list(chunk["frames"])
        timestamps = list(chunk["timestamps"])
        if not frames:
            continue
        if use_candidate_pipeline:
            previous = None

        chunk_queue[chunk_index]["status"] = "running"
        detection_base_percent = 3.0 if use_candidate_pipeline else 5.0
        detection_span_percent = 92.0 if use_candidate_pipeline else 85.0
        notify(
            {
                "stage": "detecting",
                "message": (
                    f"正在检测候选区间 {chunk_number}/{total_chunks}："
                    f"{float(chunk['start']):.1f}s-"
                    f"{float(chunk['end']):.1f}s"
                ),
                "percent": round(
                    detection_base_percent
                    + detection_span_percent
                    * (len(analysis_chunks) / total_chunks),
                    2,
                ),
                "total_chunks": total_chunks,
                "completed_chunks": len(analysis_chunks),
                "processed_frames": processed_samples,
                "total_frames": estimated_samples,
                "current_chunk": {
                    "id": chunk_id,
                    "index": chunk_number,
                    "start": float(chunk["start"]),
                    "end": float(chunk["end"]),
                    "queue": chunk.get("queue"),
                    "queue_index": chunk.get("queue_index"),
                },
                "chunks": chunk_queue,
                "candidate_duration_seconds": round(candidate_duration, 3),
                "candidate_coverage_ratio": round(
                    candidate_duration / duration,
                    4,
                ),
                "provisional_segment_count": len(published_segments),
                "provisional_segments": provisional_snapshot(),
                "provisional_keyframe_count": len(keyframes),
                "eta_seconds": None,
                "video": video,
            }
        )

        timestamp_keys = [round(float(timestamp), 3) for timestamp in timestamps]
        uncached_indexes = [
            index
            for index, timestamp_key in enumerate(timestamp_keys)
            if timestamp_key not in sample_cache
        ]
        uncached_frames = [frames[index] for index in uncached_indexes]
        uncached_detections = (
            detector.detect_frames(uncached_frames)
            if uncached_frames
            else []
        )
        if len(uncached_detections) != len(uncached_frames):
            raise RuntimeError("YOLO 返回的检测批次数量与采样帧不一致")
        detections_by_index = dict(
            zip(uncached_indexes, uncached_detections)
        )
        raw_window_detections = [
            (
                list(sample_cache[timestamp_key].get("objects", []))
                if timestamp_key in sample_cache
                else list(detections_by_index[local_index])
            )
            for local_index, timestamp_key in enumerate(timestamp_keys)
        ]
        chunk_queue[chunk_index]["status"] = "tracking"
        notify(
            {
                "stage": "tracking",
                "message": (
                    f"窗口 {chunk_number}/{total_chunks} 的 YOLO 已完成，"
                    "正在关联本窗口目标轨迹"
                ),
                "percent": round(
                    detection_base_percent
                    + detection_span_percent
                    * (len(analysis_chunks) / total_chunks),
                    2,
                ),
                "total_chunks": total_chunks,
                "completed_chunks": len(analysis_chunks),
                "processed_frames": processed_samples,
                "total_frames": estimated_samples,
                "current_chunk": {
                    "id": chunk_id,
                    "index": chunk_number,
                    "start": float(chunk["start"]),
                    "end": float(chunk["end"]),
                    "queue": chunk.get("queue"),
                    "queue_index": chunk.get("queue_index"),
                },
                "chunks": chunk_queue,
                "provisional_segment_count": len(published_segments),
                "provisional_segments": provisional_snapshot(),
                "provisional_keyframe_count": len(keyframes),
                "video": video,
            }
        )
        window_detections, window_association = (
            _associate_window_detections(
                detector,
                raw_window_detections,
                settings,
                chunk_id,
                sample_interval,
            )
        )

        chunk_samples: list[dict[str, Any]] = []
        new_chunk_samples: list[dict[str, Any]] = []
        for local_index, (frame, timestamp) in enumerate(
            zip(frames, timestamps)
        ):
            timestamp_key = timestamp_keys[local_index]
            cached = sample_cache.get(timestamp_key)
            if cached is not None:
                window_sample = dict(cached)
                window_sample["objects"] = window_detections[local_index]
                window_sample["object_count"] = len(
                    window_detections[local_index]
                )
                chunk_samples.append(window_sample)
                previous = frame
                continue
            detections = window_detections[local_index]
            object_score = scorer.calculate_object_score(detections)
            scene_score = scorer.calculate_scene_change_score(frame, previous)
            motion_score = scorer.calculate_motion_score(frame, previous)
            highlight_score = (
                object_score * object_weight
                + scene_score * scene_weight
                + motion_score * motion_weight
            )
            sample = {
                "frame_index": processed_samples,
                "chunk_frame_index": local_index,
                "chunk_id": chunk_id,
                "chunk_index": chunk_number,
                "timestamp": timestamp_key,
                "object_count": len(detections),
                "object_score": round(float(object_score), 4),
                "scene_change_score": round(float(scene_score), 4),
                "motion_score": round(float(motion_score), 4),
                "highlight_score": round(float(highlight_score), 4),
                "objects": detections,
            }
            sample_cache[timestamp_key] = sample
            samples.append(sample)
            chunk_samples.append(sample)
            new_chunk_samples.append(sample)
            processed_samples += 1
            previous = frame

        selected = _select_keyframes(
            new_chunk_samples,
            min(keyframes_per_chunk, 2)
            if use_candidate_pipeline
            else keyframes_per_chunk,
            minimum_gap,
        )
        chunk_keyframes: list[dict[str, Any]] = []
        for local_order, sample in enumerate(selected, start=1):
            keyframe_id = f"kf_c{chunk_number:04d}_{local_order:02d}"
            image_name = f"{keyframe_id}.jpg"
            annotated = _annotate_frame(
                frames[
                    timestamp_keys.index(
                        round(float(sample["timestamp"]), 3)
                    )
                ],
                sample.get("objects", []),
            )
            if not cv2.imwrite(str(keyframe_dir / image_name), annotated):
                raise RuntimeError(f"无法保存关键帧 {image_name}")
            keyframe = {
                key: value
                for key, value in sample.items()
                if key != "chunk_frame_index"
            }
            keyframe.update(
                {
                    "id": keyframe_id,
                    "image": f"keyframes/{image_name}",
                    "decision": "keep",
                    "label": "",
                    "note": "",
                    "order": len(keyframes) + 1,
                }
            )
            keyframes.append(keyframe)
            chunk_keyframes.append(keyframe)

        partial_result = HighlightExtractor(
            enemy_classes=enemy_classes,
            max_duration=float(settings.get("max_highlight_duration", 18.0)),
        ).extract(
            [
                {
                    "timestamp": item["timestamp"],
                    "detections": item.get("objects", []),
                    "highlight_score": item.get("highlight_score", 0.0),
                }
                for item in chunk_samples
            ],
            float(video.get("fps", 24.0)),
            duration,
        )
        chunk_segment_candidates: list[dict[str, Any]] = []
        for local_order, segment in enumerate(
            partial_result.get("segments", []),
            start=1,
        ):
            provisional = dict(segment)
            provisional.update(
                {
                    "id": f"seg_c{chunk_number:04d}_{local_order:02d}",
                    "order": 1,
                    "chunk_id": chunk_id,
                    "provisional": True,
                }
            )
            chunk_segment_candidates.append(provisional)

        window_tracking = _refine_window_segments_with_tracking(
            chunk_segment_candidates,
            chunk_samples,
            duration,
            enemy_classes,
            settings,
            window_association,
        )
        tracking_report["enabled"] = bool(window_tracking.get("enabled"))
        tracking_report["window_count"] += 1
        window_status = str(window_tracking.get("status", "unsupported"))
        if window_status == "completed":
            tracking_report["completed_window_count"] += 1
        elif window_status == "failed":
            tracking_report["failed_window_count"] += 1
        for field in (
            "candidate_segment_count",
            "refined_segment_count",
            "track_count",
            "point_count",
        ):
            tracking_report[field] += int(window_tracking.get(field) or 0)
        tracking_report["windows"].append(window_tracking)

        provisional_segments = []
        for provisional in chunk_segment_candidates:
            segment_keyframes = [
                keyframe
                for keyframe in chunk_keyframes
                if float(provisional["start"])
                <= float(keyframe["timestamp"])
                <= float(provisional["end"])
            ]
            provisional["source_keyframes"] = [
                str(keyframe["id"]) for keyframe in segment_keyframes
            ]
            window_segments.append(provisional)
            if not use_candidate_pipeline:
                dispatch_agent_segment(provisional)
            provisional_segments.append(
                {
                    key: provisional.get(key)
                    for key in (
                        "id",
                        "start",
                        "end",
                        "duration",
                        "score",
                        "reason",
                        "chunk_id",
                        "provisional",
                        "tracking",
                    )
                }
            )

        chunk_summary = {
            "id": chunk_id,
            "index": chunk_number,
            "start": round(float(chunk["start"]), 3),
            "end": round(float(chunk["end"]), 3),
            "candidate_score": chunk_queue[chunk_index].get(
                "candidate_score"
            ),
            "queue": chunk.get("queue"),
            "queue_index": chunk.get("queue_index"),
            "status": "completed",
            "sample_count": len(new_chunk_samples),
            "window_sample_count": len(chunk_samples),
            "reused_sample_count": len(chunk_samples) - len(new_chunk_samples),
            "keyframes": chunk_keyframes,
            "keyframe_ids": [item["id"] for item in chunk_keyframes],
            "provisional_segments": provisional_segments,
            "segment_ids": [],
            "tracking": window_tracking,
        }
        analysis_chunks.append(chunk_summary)
        chunk_queue[chunk_index] = chunk_summary
        if use_candidate_pipeline and (
            chunk.get("queue") == "q2"
            or len(analysis_chunks) == total_chunks
        ):
            published_segments = _published_window_segments(window_segments)
            next_window_start = (
                float(candidate_windows[len(analysis_chunks)]["start"])
                if len(analysis_chunks) < total_chunks
                else math.inf
            )
            merge_guard_seconds = 2.0
            for segment in published_segments:
                if (
                    float(segment["end"])
                    <= next_window_start - merge_guard_seconds + 1e-6
                ):
                    dispatch_agent_segment(segment)
        detection_elapsed = max(
            0.001,
            time.monotonic() - detection_started,
        )
        detection_remaining = (
            detection_elapsed
            * max(0, total_chunks - len(analysis_chunks))
            / max(1, len(analysis_chunks))
        )
        provisional_segment_count = (
            len(published_segments)
            if use_candidate_pipeline
            else sum(
                len(item.get("provisional_segments", []))
                for item in analysis_chunks
            )
        )
        notify(
            {
                "stage": "detecting",
                "message": (
                    f"已完成 {len(analysis_chunks)}/{total_chunks} "
                    "个候选区间"
                ),
                "percent": round(
                    detection_base_percent
                    + detection_span_percent
                    * (len(analysis_chunks) / total_chunks),
                    2,
                ),
                "total_chunks": total_chunks,
                "completed_chunks": len(analysis_chunks),
                "processed_frames": processed_samples,
                "total_frames": estimated_samples,
                "current_chunk": None,
                "chunks": chunk_queue,
                "provisional_segments": (
                    provisional_snapshot()
                    if use_candidate_pipeline
                    else []
                ),
                "candidate_duration_seconds": round(candidate_duration, 3),
                "candidate_coverage_ratio": round(
                    candidate_duration / duration,
                    4,
                ),
                "provisional_segment_count": provisional_segment_count,
                "provisional_keyframe_count": len(keyframes),
                "stage_eta_seconds": round(detection_remaining, 1),
                "eta_seconds": round(detection_remaining + 2.0, 1),
                "video": video,
            }
        )

    window_tracking_statuses = {
        str(window.get("status", "unsupported"))
        for window in tracking_report["windows"]
    }
    if not tracking_report["enabled"]:
        tracking_report["status"] = "disabled"
    elif tracking_report["failed_window_count"] > 0:
        tracking_report["status"] = (
            "partial"
            if tracking_report["completed_window_count"] > 0
            else "failed"
        )
    elif "completed" in window_tracking_statuses:
        tracking_report["status"] = "completed"
    elif "unsupported" in window_tracking_statuses:
        tracking_report["status"] = "unsupported"
    else:
        tracking_report["status"] = "not_needed"

    if not samples or not keyframes:
        raise ValueError("视频中没有可分析的画面")

    samples.sort(key=lambda item: float(item["timestamp"]))
    keyframes.sort(key=lambda item: float(item["timestamp"]))
    for order, keyframe in enumerate(keyframes, start=1):
        keyframe["order"] = order

    best = max(keyframes, key=lambda item: item["highlight_score"])
    start, end = _bounded_clip(
        float(best["timestamp"]),
        duration,
        float(settings.get("target_duration", 30.0)),
    )
    output_ratio = str(settings.get("output_ratio", "16:9"))

    # Short videos are continuous. Long videos must only reconcile window-local
    # extraction results, otherwise gaps between candidates become fake events.
    fps = float(video.get("fps", 24.0))
    frame_results = [
        {
            "timestamp": s["timestamp"],
            "detections": s.get("objects", []),
            "highlight_score": s.get("highlight_score", 0.0),
        }
        for s in samples
    ]
    if window_segments:
        segments = _reconcile_window_segments(window_segments)
    else:
        extractor = HighlightExtractor(
            enemy_classes=enemy_classes,
            max_duration=float(settings.get("max_highlight_duration", 18.0)),
        )
        highlight_result = extractor.extract(frame_results, fps, duration)
        segments = highlight_result.get("segments", [])

    segment_thumbnail_dir = job_dir / "result" / "segment_thumbs"
    for seg in segments:
        seg_keyframes = [
            kf for kf in keyframes
            if seg["start"] <= float(kf["timestamp"]) <= seg["end"]
        ]
        seg["source_keyframes"] = [
            str(keyframe["id"])
            for keyframe in seg_keyframes
        ]
        if seg_keyframes:
            representative = max(
                seg_keyframes,
                key=lambda keyframe: float(
                    keyframe.get("highlight_score", 0.0)
                ),
            )
            seg["representative_keyframe"] = str(representative["id"])
            seg["thumbnail"] = representative.get("image")
        else:
            segment_samples = [
                sample
                for sample in samples
                if float(seg["start"])
                <= float(sample["timestamp"])
                <= float(seg["end"])
            ]
            seg["representative_keyframe"] = None
            seg["thumbnail"] = None
            if segment_samples:
                representative_sample = max(
                    segment_samples,
                    key=lambda sample: float(
                        sample.get("highlight_score", 0.0)
                    ),
                )
                thumbnail_name = f"{seg['id']}_thumb.jpg"
                thumbnail_path = segment_thumbnail_dir / thumbnail_name
                if _save_segment_thumbnail(
                    video_path,
                    float(representative_sample["timestamp"]),
                    representative_sample.get("objects", []),
                    thumbnail_path,
                ):
                    seg["thumbnail"] = (
                        f"result/segment_thumbs/{thumbnail_name}"
                    )
        evidence = seg.get("evidence")
        if not isinstance(evidence, dict):
            evidence = {}
            seg["evidence"] = evidence
        evidence["representative_keyframe"] = seg.get(
            "representative_keyframe"
        )
        evidence["thumbnail"] = seg.get("thumbnail")
        seg["provisional"] = False

    for chunk in analysis_chunks:
        chunk["segment_ids"] = [
            str(segment["id"])
            for segment in segments
            if float(segment["end"]) >= float(chunk["start"])
            and float(segment["start"]) <= float(chunk["end"])
        ]
        chunk.pop("provisional_segments", None)

    segment_tags = scorer.calculate_segment_tags(samples, segments)
    ai_cover_prompt = scorer.generate_cover_prompt(best)

    contact_sheet = job_dir / "result" / "contact_sheet.jpg"
    contact_sheet_ready = _save_contact_sheet_from_keyframes(
        keyframes,
        job_dir,
        contact_sheet,
    )
    notify(
        {
            "stage": "finalizing",
            "message": "正在归并候选片段并生成最终报告",
            "percent": 99.0,
            "total_chunks": total_chunks,
            "completed_chunks": len(analysis_chunks),
            "processed_frames": processed_samples,
            "total_frames": processed_samples,
            "current_chunk": None,
            "chunks": analysis_chunks,
            "candidate_duration_seconds": round(candidate_duration, 3),
            "candidate_coverage_ratio": round(
                candidate_duration / duration,
                4,
            ),
            "provisional_segment_count": (
                len(published_segments)
                if use_candidate_pipeline
                else sum(
                    len(item.get("provisional_segments", []))
                    for item in analysis_chunks
                )
            ),
            "provisional_segments": (
                provisional_snapshot()
                if use_candidate_pipeline
                else []
            ),
            "provisional_keyframe_count": len(keyframes),
            "eta_seconds": 2.0,
            "video": video,
        }
    )
    model_report = {
        "path": model_path.name,
        "game_type": game_type,
        "highlight_strategy": highlight_strategy,
        "is_fallback": is_fallback,
        "enemy_classes": sorted(enemy_classes or []),
        "version": (
            model_info.model_id if model_info is not None else "unknown"
        ),
        "confidence_threshold": float(
            settings.get("confidence_threshold", 0.35)
        ),
        "sample_interval": sample_interval,
    }
    if model_info is not None:
        model_report.update(
            {
                "id": model_info.model_id,
                "display_name": model_info.display_name,
                "is_custom": model_info.is_custom,
                "num_classes": model_info.num_classes,
                "class_names": model_info.class_names,
                "mAP50": model_info.mAP50,
                "mAP50_95": model_info.mAP50_95,
            }
        )

    return {
        "video": video,
        "duration": duration,
        "settings": {key: value for key, value in settings.items() if key != "model_path"},
        "model": model_report,
        "analysis_mode": analysis_mode,
        "tracking": tracking_report,
        "chunk_duration": chunk_duration,
        "analysis_chunks": analysis_chunks,
        "sample_interval": sample_interval,
        "screening": {
            "enabled": False,
            "strategy": (
                "direct_staggered_windows"
                if use_candidate_pipeline
                else "direct_chunks"
            ),
            "coarse_interval": None,
            "coarse_sample_count": 0,
            "candidate_window_count": len(candidate_windows),
            "candidate_duration": round(
                candidate_duration,
                3,
            ),
            "coverage_ratio": round(
                candidate_duration / duration,
                4,
            ),
            "processing_order": (
                "staggered_q1_q2"
                if use_candidate_pipeline
                else "chronological"
            ),
            "window_duration": round(streaming_window_duration, 3),
            "window_stride": round(streaming_window_stride, 3),
            "overlap_reuses_yolo": use_candidate_pipeline,
        },
        "total_sampled_frames": len(samples),
        "score_weights": {
            "object": object_weight,
            "scene_change": scene_weight,
            "motion": motion_weight,
        },
        "samples": [
            {
                key: value
                for key, value in sample.items()
                if key != "chunk_frame_index"
            }
            for sample in samples
        ],
        "keyframes": keyframes,
        "segments": segments,
        "segment_tags": segment_tags,
        "ai_cover_prompt": ai_cover_prompt,
        "recommended_clip": {
            "start_time": segments[0]["start"] if segments else None,
            "end_time": segments[0]["end"] if segments else None,
            "output_ratio": output_ratio,
            "segment_count": len(segments),
            "is_empty": not segments,
        },
        "output": {
            "video": None,
            "contact_sheet": "result/contact_sheet.jpg" if contact_sheet_ready else None,
        },
    }


class AnalysisService:
    def __init__(
        self,
        jobs: JobService,
        max_workers: int = 2,
        model_path: Path = Path("models/yolo11n.pt"),
    ) -> None:
        self.jobs = jobs
        self.model_path = Path(model_path).resolve()
        self.model_registry = ModelRegistry(
            Path(__file__).resolve().parent.parent,
            official_model_path=self.model_path,
        )
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, int(max_workers)),
            thread_name_prefix="reelfire-analysis",
        )
        self._active: set[str] = set()
        self._active_lock = threading.Lock()
        self._segment_callback: (
            Callable[[str, dict[str, Any]], None] | None
        ) = None
        self._segment_finalizer: (
            Callable[[str, list[dict[str, Any]]], None] | None
        ) = None

    def set_segment_callback(
        self,
        callback: Callable[[str, dict[str, Any]], None] | None,
        finalizer: Callable[[str, list[dict[str, Any]]], None] | None = None,
    ) -> None:
        self._segment_callback = callback
        self._segment_finalizer = finalizer

    def enqueue(self, job_id: str) -> None:
        with self._active_lock:
            if job_id in self._active:
                raise JobStateConflictError("任务已在排队或分析中")
            self.jobs.queue_for_analysis(job_id)
            self.jobs.write_progress(
                job_id,
                {
                    "stage": "queued",
                    "message": "任务已创建，正在等待分析线程",
                    "percent": 0.0,
                    "total_chunks": 0,
                    "completed_chunks": 0,
                    "processed_frames": 0,
                    "total_frames": 0,
                    "current_chunk": None,
                    "chunks": [],
                },
            )
            self._active.add(job_id)
        try:
            self._executor.submit(self._run, job_id)
        except RuntimeError as exc:
            with self._active_lock:
                self._active.discard(job_id)
            self.jobs.mark_failed(job_id, "后台任务调度器不可用")
            raise RuntimeError("后台任务调度器不可用") from exc

    def _run(self, job_id: str) -> None:
        try:
            job = self.jobs.mark_running(job_id)
            self.jobs.write_progress(
                job_id,
                {
                    "stage": "initializing",
                    "message": "正在读取视频元数据并加载 YOLO 模型",
                    "percent": 1.0,
                    "total_chunks": 0,
                    "completed_chunks": 0,
                    "processed_frames": 0,
                    "total_frames": 0,
                    "current_chunk": None,
                    "chunks": [],
                },
            )
            video_path = self.jobs.get_input_video(job_id)
            job_dir = self.jobs.job_dir(job_id)
            settings = dict(job["settings"])
            settings["model_path"] = str(self.model_path)
            settings["game_type"] = str(job.get("game_type") or "other")
            report = analyze_video(
                video_path,
                job_dir,
                settings,
                lambda value: self.jobs.write_progress(
                    job_id,
                    value,
                ),
                model_registry=self.model_registry,
                segment_callback=(
                    (
                        lambda partial: self._segment_callback(
                            job_id,
                            {**partial, "job_id": job_id},
                        )
                    )
                    if self._segment_callback is not None
                    else None
                ),
            )
            if not isinstance(report, dict):
                raise TypeError("analyze_video 必须返回 JSON 对象")
            report.setdefault("job_id", job_id)
            report["updated_at"] = iso_now()
            if self._segment_finalizer is not None:
                self._segment_finalizer(
                    job_id,
                    [
                        dict(segment)
                        for segment in report.get("segments", [])
                        if isinstance(segment, dict)
                    ],
                )
            for segment in report.get("segments", []):
                if isinstance(segment, dict):
                    segment.pop("agent_segment_id", None)
            self.jobs.write_report(job_id, report)
            video = report.get("video", {})
            self.jobs.update_job(
                job_id,
                duration=video.get("duration"),
                width=video.get("width"),
                height=video.get("height"),
                fps=video.get("fps"),
                has_audio=video.get("has_audio"),
            )
            self.jobs.mark_completed(job_id, "analysis_report.json")
            chunks = report.get("analysis_chunks", [])
            self.jobs.write_progress(
                job_id,
                {
                    "stage": "completed",
                    "message": "视频分块分析和最终报告已完成",
                    "percent": 100.0,
                    "total_chunks": len(chunks),
                    "completed_chunks": len(chunks),
                    "processed_frames": report.get("total_sampled_frames", 0),
                    "total_frames": report.get("total_sampled_frames", 0),
                    "current_chunk": None,
                    "chunks": chunks,
                    "video": video,
                },
            )
        except Exception as exc:  # Persist every background failure.
            message = str(exc).strip() or exc.__class__.__name__
            try:
                self.jobs.mark_failed(job_id, message)
                previous_progress = self.jobs.read_progress(job_id)
                previous_progress.update(
                    {
                        "stage": "failed",
                        "message": message,
                    }
                )
                self.jobs.write_progress(job_id, previous_progress)
            except Exception:
                LOGGER.exception("无法把后台分析失败状态写回任务 %s", job_id)
        finally:
            with self._active_lock:
                self._active.discard(job_id)

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=False)
