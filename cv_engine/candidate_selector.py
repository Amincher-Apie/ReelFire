from __future__ import annotations

import math
from typing import Any

import cv2
import numpy as np


def calculate_activity(
    frame: np.ndarray,
    previous_frame: np.ndarray | None,
) -> dict[str, float]:
    """Score cheap visual activity signals on already downscaled frames."""

    if previous_frame is None:
        return {
            "activity_score": 0.0,
            "scene_change_score": 0.0,
            "motion_score": 0.0,
            "hud_change_score": 0.0,
        }

    current_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    previous_gray = cv2.cvtColor(previous_frame, cv2.COLOR_BGR2GRAY)
    difference = cv2.absdiff(previous_gray, current_gray)

    scene_score = min(float(np.mean(difference)) / 32.0, 1.0)
    motion_score = min(float(np.mean(difference > 18)) / 0.35, 1.0)

    height, width = difference.shape
    hud = difference[
        0 : max(1, int(height * 0.42)),
        max(0, int(width * 0.52)) : width,
    ]
    hud_score = min(float(np.mean(hud)) / 26.0, 1.0) if hud.size else 0.0
    activity_score = (
        scene_score * 0.30
        + motion_score * 0.40
        + hud_score * 0.30
    )
    return {
        "activity_score": round(activity_score, 4),
        "scene_change_score": round(scene_score, 4),
        "motion_score": round(motion_score, 4),
        "hud_change_score": round(hud_score, 4),
    }


def build_overlapping_windows(
    duration: float,
    *,
    window_duration: float = 60.0,
    stride: float = 30.0,
) -> list[dict[str, Any]]:
    """Plan two staggered logical queues in q1[i], q2[i] order."""

    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Video duration must be positive")
    window_duration = min(
        duration,
        max(1.0, float(window_duration)),
    )
    stride = min(window_duration, max(1.0, float(stride)))
    queue_starts = (
        ("q1", 0.0),
        ("q2", stride),
    )
    queues: dict[str, list[dict[str, Any]]] = {}
    for queue_name, offset in queue_starts:
        queue_windows: list[dict[str, Any]] = []
        start = offset
        while start < duration:
            queue_windows.append(
                {
                    "start": round(start, 3),
                    "end": round(min(duration, start + window_duration), 3),
                    "score": None,
                    "reason": "streaming_activity",
                    "queue": queue_name,
                    "queue_index": len(queue_windows),
                }
            )
            start += window_duration
        queues[queue_name] = queue_windows

    windows: list[dict[str, Any]] = []
    queue_length = max((len(items) for items in queues.values()), default=0)
    for queue_index in range(queue_length):
        for queue_name, _offset in queue_starts:
            queue_windows = queues[queue_name]
            if queue_index >= len(queue_windows):
                continue
            windows.append(
                {
                    **queue_windows[queue_index],
                    "index": len(windows),
                }
            )
    return windows


def score_activity_window(
    samples: list[dict[str, Any]],
    start: float,
    end: float,
) -> float:
    """Blend peak and average activity for one completed logical window."""

    scores = [
        max(0.0, min(1.0, float(sample.get("activity_score", 0.0))))
        for sample in samples
        if start <= float(sample.get("timestamp", -1.0)) < end
    ]
    if not scores:
        return 0.0
    peak_count = max(1, min(3, len(scores)))
    peaks = sorted(scores, reverse=True)[:peak_count]
    score = (sum(peaks) / peak_count) * 0.7 + (sum(scores) / len(scores)) * 0.3
    return round(score, 4)


def _bounded_window(
    timestamp: float,
    duration: float,
    window_duration: float,
) -> tuple[float, float]:
    length = min(duration, window_duration)
    start = timestamp - length * 0.4
    start = min(max(0.0, start), max(0.0, duration - length))
    return round(start, 3), round(start + length, 3)


def _merge_ranges(
    ranges: list[tuple[float, float]],
    *,
    merge_gap: float = 1.0,
) -> list[tuple[float, float]]:
    merged: list[list[float]] = []
    for start, end in sorted(ranges):
        if not merged or start > merged[-1][1] + merge_gap:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [(round(start, 3), round(end, 3)) for start, end in merged]


def _coverage(ranges: list[tuple[float, float]]) -> float:
    return sum(end - start for start, end in _merge_ranges(ranges))


def select_candidate_windows(
    samples: list[dict[str, Any]],
    duration: float,
    *,
    target_duration: float = 30.0,
    coverage_ratio: float = 0.25,
    window_duration: float = 16.0,
    bucket_duration: float = 90.0,
) -> list[dict[str, Any]]:
    """Select temporally distributed high-activity windows within a budget."""

    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Video duration must be positive")
    if not samples:
        start, end = _bounded_window(duration / 2.0, duration, window_duration)
        return [
            {
                "index": 0,
                "start": start,
                "end": end,
                "score": 0.0,
                "reason": "fallback",
            }
        ]

    ratio = min(max(float(coverage_ratio), 0.05), 1.0)
    budget = min(
        duration,
        max(
            min(duration, float(window_duration)),
            min(
                min(duration, float(target_duration) * 4.0),
                duration * ratio,
            ),
        ),
    )

    normalized = sorted(
        (
            {
                **sample,
                "timestamp": min(
                    max(float(sample.get("timestamp", 0.0)), 0.0),
                    duration,
                ),
                "activity_score": float(sample.get("activity_score", 0.0)),
            }
            for sample in samples
        ),
        key=lambda sample: sample["timestamp"],
    )

    bucket_best: dict[int, dict[str, Any]] = {}
    for sample in normalized:
        bucket = int(sample["timestamp"] // max(1.0, bucket_duration))
        current = bucket_best.get(bucket)
        if (
            current is None
            or sample["activity_score"] > current["activity_score"]
        ):
            bucket_best[bucket] = sample

    distributed = sorted(
        bucket_best.values(),
        key=lambda sample: sample["timestamp"],
    )
    global_ranked = sorted(
        normalized,
        key=lambda sample: (
            -sample["activity_score"],
            sample["timestamp"],
        ),
    )
    ranked = distributed + [
        sample for sample in global_ranked if sample not in distributed
    ]

    selected: list[tuple[float, float]] = []
    selected_timestamps: set[float] = set()
    for sample in ranked:
        timestamp = float(sample["timestamp"])
        if timestamp in selected_timestamps:
            continue
        candidate = _bounded_window(timestamp, duration, window_duration)
        proposed = selected + [candidate]
        if selected and _coverage(proposed) > budget + 0.001:
            continue
        selected.append(candidate)
        selected_timestamps.add(timestamp)
        if _coverage(selected) >= budget - window_duration * 0.5:
            break

    merged = _merge_ranges(selected)
    windows: list[dict[str, Any]] = []
    for index, (start, end) in enumerate(merged):
        matching_scores = [
            sample["activity_score"]
            for sample in normalized
            if start <= sample["timestamp"] <= end
        ]
        windows.append(
            {
                "index": index,
                "start": start,
                "end": end,
                "score": round(max(matching_scores, default=0.0), 4),
                "reason": "visual_activity",
            }
        )
    return windows
