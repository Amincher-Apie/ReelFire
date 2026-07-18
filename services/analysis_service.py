"""Background execution integrated with the CV engine."""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import cv2

from services.job_service import JobService, JobStateConflictError, iso_now

# Ensure the project root is importable for cv_engine
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from cv_engine.video_processor import VideoProcessor
from cv_engine.yolo_detector import YoloDetector
from cv_engine.highlight_scorer import HighlightScorer


LOGGER = logging.getLogger(__name__)


def analyze_video(
    video_path: Path,
    job_dir: Path,
    settings: dict[str, Any],
) -> dict[str, Any]:
    """Analyze one video using the CV engine and return a JSON-serializable report."""

    video_path_str = str(video_path)
    job_dir_str = str(job_dir)

    # ── 1. Sample video frames ────────────────────────────────
    processor = VideoProcessor()
    video_info = processor.get_video_info(video_path_str)
    sample_interval = float(settings.get("sample_interval", 1.0))
    frames, timestamps = processor.sample_video(video_path_str, interval=sample_interval)

    if not frames:
        raise RuntimeError(f"视频采样失败：未能从 {video_path_str} 读取任何帧")

    # ── 2. YOLO detection ─────────────────────────────────────
    detector = YoloDetector(
        model_path=os.path.join(str(_PROJECT_ROOT), "models", "yolo11n.pt")
    )
    detections_list = detector.detect_frames(frames)

    # ── 3. Highlight scoring ──────────────────────────────────
    scorer = HighlightScorer(
        object_weight=float(settings.get("object_weight", 0.45)),
        scene_change_weight=float(settings.get("scene_change_weight", 0.35)),
        motion_weight=float(settings.get("motion_weight", 0.20)),
    )
    raw = scorer.analyze(frames, detections_list, timestamps, job_id=str(job_dir.name))

    # ── 4. Save keyframe images ──────────────────────────────
    keyframes_dir = os.path.join(job_dir_str, "keyframes")
    os.makedirs(keyframes_dir, exist_ok=True)
    top_kfs = raw.get("top_keyframes", raw.get("keyframes", []))[:8]
    saved_keyframes = []
    for idx, kf in enumerate(top_kfs):
        frame_index = kf["frame_index"]
        img_path = os.path.join(keyframes_dir, f"kf_{idx+1:03d}_{kf['timestamp']:.1f}s.jpg")
        try:
            processor.save_frame(frames[frame_index], img_path)
        except Exception:
            img_path = ""
        saved_keyframes.append({
            "id": f"kf_{idx+1:03d}",
            "timestamp": kf["timestamp"],
            "frame_index": frame_index,
            "image": img_path,
            "scores": {
                "object_score": kf.get("object_score", 0),
                "scene_change_score": kf.get("scene_change_score", 0),
                "motion_score": kf.get("motion_score", 0),
                "final_score": kf.get("highlight_score", 0),
            },
            "labels": [],
            "notes": "",
            "ignored": False,
            "order": idx + 1,
            "detections": kf.get("objects", []),
        })

    # ── 5. Calculate aggregate scores ─────────────────────────
    all_keyframes = raw.get("keyframes", [])
    if all_keyframes:
        avg_obj = sum(k.get("object_score", 0) for k in all_keyframes) / len(all_keyframes)
        avg_sc = sum(k.get("scene_change_score", 0) for k in all_keyframes) / len(all_keyframes)
        avg_mo = sum(k.get("motion_score", 0) for k in all_keyframes) / len(all_keyframes)
        avg_final = sum(k.get("highlight_score", 0) for k in all_keyframes) / len(all_keyframes)
    else:
        avg_obj = avg_sc = avg_mo = avg_final = 0.0

    # ── 6. Format segments ────────────────────────────────────
    raw_segments = raw.get("recommended_segments", [])
    segments = []
    for idx, seg in enumerate(raw_segments):
        segments.append({
            "id": f"seg_{idx+1:03d}",
            "start": seg.get("start", 0),
            "end": seg.get("end", 0),
            "duration": round(seg.get("end", 0) - seg.get("start", 0), 2),
            "keyframes_used": [],
            "avg_score": seg.get("score", 0),
            "title": f"精彩片段 {idx+1}",
        })

    # ── 7. Build final report ─────────────────────────────────
    return {
        "video_info": {
            "file_name": os.path.basename(video_path_str),
            "duration": video_info.get("duration", 0),
            "resolution": [video_info.get("width", 0), video_info.get("height", 0)],
            "fps": video_info.get("fps", 0),
            "has_audio": video_info.get("has_audio", False),
        },
        "scores": {
            "object_score": round(avg_obj, 4),
            "scene_change_score": round(avg_sc, 4),
            "motion_score": round(avg_mo, 4),
            "final_score": round(avg_final, 4),
        },
        "weights": {
            "object_weight": float(settings.get("object_weight", 0.45)),
            "scene_change_weight": float(settings.get("scene_change_weight", 0.35)),
            "motion_weight": float(settings.get("motion_weight", 0.20)),
        },
        "keyframes": saved_keyframes,
        "segments": segments,
    }


class AnalysisService:
    def __init__(self, jobs: JobService, max_workers: int = 2) -> None:
        self.jobs = jobs
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, int(max_workers)),
            thread_name_prefix="day08-analysis",
        )
        self._active: set[str] = set()
        self._active_lock = threading.Lock()

    def enqueue(self, job_id: str) -> None:
        with self._active_lock:
            if job_id in self._active:
                raise JobStateConflictError("任务已在排队或分析中")
            self.jobs.queue_for_analysis(job_id)
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
            video_path = self.jobs.get_input_video(job_id)
            job_dir = self.jobs.job_dir(job_id)
            report = analyze_video(video_path, job_dir, dict(job["settings"]))
            if not isinstance(report, dict):
                raise TypeError("analyze_video 必须返回 JSON 对象")
            report.setdefault("job_id", job_id)
            report["updated_at"] = iso_now()
            self.jobs.write_report(job_id, report)
            self.jobs.mark_completed(job_id, "analysis_report.json")
        except Exception as exc:  # Background boundary: persist every expected failure.
            message = str(exc).strip() or exc.__class__.__name__
            try:
                self.jobs.mark_failed(job_id, message)
            except Exception:
                # Preserve process availability, but never hide persistence failures.
                LOGGER.exception("无法把后台分析失败状态写回任务 %s", job_id)
        finally:
            with self._active_lock:
                self._active.discard(job_id)

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=False)
