"""Background execution and CV integration for FPS highlight extraction."""

from __future__ import annotations

import logging
import math
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from cv_engine.highlight_scorer import HighlightScorer
from cv_engine.video_processor import VideoProcessor
from cv_engine.yolo_detector import YoloDetector
from services.job_service import JobService, JobStateConflictError, iso_now


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


def _annotate_frame(frame: np.ndarray, objects: list[dict[str, Any]]) -> np.ndarray:
    """Draw YOLO boxes on a copy of a frame for human-verifiable evidence."""
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


def analyze_video(
    video_path: Path,
    job_dir: Path,
    settings: dict[str, Any],
) -> dict[str, Any]:
    """Run OpenCV sampling, YOLO detection and explainable scoring."""
    processor = VideoProcessor()
    video = processor.get_video_info(video_path)
    duration = float(video.get("duration", 0.0))
    if duration <= 0 or int(video.get("width", 0)) <= 0:
        raise ValueError("无法读取视频信息，文件可能已损坏或不受支持")

    sample_interval = float(settings.get("sample_interval", 0.5))
    frames, timestamps = processor.sample_video(video_path, sample_interval)
    if not frames:
        raise ValueError("视频中没有可分析的画面")

    model_path = Path(str(settings.get("model_path", "models/yolo11n.pt")))
    detector = YoloDetector(
        model_path,
        confidence_threshold=float(settings.get("confidence_threshold", 0.35)),
    )
    detections_list = detector.detect_frames(frames)
    scorer = HighlightScorer()

    object_weight = float(settings.get("object_weight", 0.45))
    scene_weight = float(settings.get("scene_change_weight", 0.35))
    motion_weight = float(settings.get("motion_weight", 0.20))
    samples: list[dict[str, Any]] = []
    previous = None
    for index, (frame, detections, timestamp) in enumerate(
        zip(frames, detections_list, timestamps)
    ):
        object_score = scorer.calculate_object_score(detections)
        scene_score = scorer.calculate_scene_change_score(frame, previous)
        motion_score = scorer.calculate_motion_score(frame, previous)
        highlight_score = (
            object_score * object_weight
            + scene_score * scene_weight
            + motion_score * motion_weight
        )
        samples.append(
            {
                "frame_index": index,
                "timestamp": round(float(timestamp), 3),
                "object_count": len(detections),
                "object_score": round(float(object_score), 4),
                "scene_change_score": round(float(scene_score), 4),
                "motion_score": round(float(motion_score), 4),
                "highlight_score": round(float(highlight_score), 4),
                "objects": detections,
            }
        )
        previous = frame

    selected = _select_keyframes(
        samples,
        max(1, int(settings.get("max_keyframes", 10))),
        max(0.0, float(settings.get("min_keyframe_gap", 5.0))),
    )
    keyframe_dir = job_dir / "keyframes"
    keyframe_dir.mkdir(parents=True, exist_ok=True)
    keyframes: list[dict[str, Any]] = []
    for order, sample in enumerate(selected, start=1):
        keyframe_id = f"kf_{order:03d}"
        image_name = f"{keyframe_id}.jpg"
        annotated = _annotate_frame(
            frames[int(sample["frame_index"])],
            sample.get("objects", []),
        )
        if not cv2.imwrite(str(keyframe_dir / image_name), annotated):
            raise RuntimeError(f"无法保存关键帧 {image_name}")
        keyframes.append(
            {
                **sample,
                "id": keyframe_id,
                "image": f"keyframes/{image_name}",
                "decision": "keep",
                "label": "",
                "note": "",
                "order": order,
            }
        )

    best = max(keyframes, key=lambda item: item["highlight_score"])
    start, end = _bounded_clip(
        float(best["timestamp"]),
        duration,
        float(settings.get("target_duration", 30.0)),
    )
    output_ratio = str(settings.get("output_ratio", "16:9"))
    segment = {
        "id": "seg_001",
        "start": start,
        "end": end,
        "score": best["highlight_score"],
        "source_keyframes": [best["id"]],
        "order": 1,
    }

    contact_sheet = job_dir / "result" / "contact_sheet.jpg"
    contact_sheet_ready = _save_contact_sheet(selected, frames, contact_sheet)
    return {
        "video": video,
        "duration": duration,
        "settings": {key: value for key, value in settings.items() if key != "model_path"},
        "model": {"path": model_path.name},
        "sample_interval": sample_interval,
        "total_sampled_frames": len(samples),
        "score_weights": {
            "object": object_weight,
            "scene_change": scene_weight,
            "motion": motion_weight,
        },
        "samples": samples,
        "keyframes": keyframes,
        "segments": [segment],
        "recommended_clip": {
            "start_time": start,
            "end_time": end,
            "output_ratio": output_ratio,
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
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, int(max_workers)),
            thread_name_prefix="reelfire-analysis",
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
            settings = dict(job["settings"])
            settings["model_path"] = str(self.model_path)
            report = analyze_video(video_path, job_dir, settings)
            if not isinstance(report, dict):
                raise TypeError("analyze_video 必须返回 JSON 对象")
            report.setdefault("job_id", job_id)
            report["updated_at"] = iso_now()
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
        except Exception as exc:  # Persist every background failure.
            message = str(exc).strip() or exc.__class__.__name__
            try:
                self.jobs.mark_failed(job_id, message)
            except Exception:
                LOGGER.exception("无法把后台分析失败状态写回任务 %s", job_id)
        finally:
            with self._active_lock:
                self._active.discard(job_id)

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=False)
