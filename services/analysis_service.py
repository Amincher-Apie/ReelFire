"""Background execution and CV integration for FPS highlight extraction."""

from __future__ import annotations

import logging
import math
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

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


def _notify_progress(
    callback: Callable[[dict[str, Any]], None] | None,
    payload: dict[str, Any],
) -> None:
    if callback is not None:
        callback(payload)


def analyze_video(
    video_path: Path,
    job_dir: Path,
    settings: dict[str, Any],
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
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

    sample_interval = float(settings.get("sample_interval", 0.5))
    chunk_duration = max(5.0, float(settings.get("chunk_duration", 60.0)))
    total_chunks = max(1, math.ceil(duration / chunk_duration))
    estimated_samples = max(1, math.ceil(duration / sample_interval))
    keyframes_per_chunk = max(
        1,
        int(settings.get("keyframes_per_chunk", 4)),
    )

    model_path = Path(str(settings.get("model_path", "models/yolo11n.pt")))
    detector = YoloDetector(
        model_path,
        confidence_threshold=float(settings.get("confidence_threshold", 0.35)),
        batch_size=int(settings.get("yolo_batch_size", 8)),
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

    _notify_progress(
        progress_callback,
        {
            "stage": "sampling",
            "message": "正在读取视频并准备分块分析",
            "percent": 2.0,
            "total_chunks": total_chunks,
            "completed_chunks": 0,
            "processed_frames": 0,
            "total_frames": estimated_samples,
            "current_chunk": None,
            "chunks": [],
        },
    )

    for chunk in processor.iter_sample_chunks(
        video_path,
        interval=sample_interval,
        chunk_duration=chunk_duration,
    ):
        chunk_index = int(chunk["index"])
        chunk_number = chunk_index + 1
        chunk_id = f"chunk_{chunk_number:04d}"
        frames = list(chunk["frames"])
        timestamps = list(chunk["timestamps"])
        if not frames:
            continue

        _notify_progress(
            progress_callback,
            {
                "stage": "detecting",
                "message": (
                    f"正在分析 {float(chunk['start']):.1f}s–"
                    f"{float(chunk['end']):.1f}s"
                ),
                "percent": round(
                    5.0 + 85.0 * (chunk_index / total_chunks),
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
                },
                "chunks": analysis_chunks,
            },
        )

        detections_list = detector.detect_frames(frames)
        if len(detections_list) != len(frames):
            raise RuntimeError("YOLO 返回的检测批次数量与采样帧不一致")

        chunk_samples: list[dict[str, Any]] = []
        for local_index, (frame, detections, timestamp) in enumerate(
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
            sample = {
                "frame_index": processed_samples,
                "chunk_frame_index": local_index,
                "chunk_id": chunk_id,
                "chunk_index": chunk_number,
                "timestamp": round(float(timestamp), 3),
                "object_count": len(detections),
                "object_score": round(float(object_score), 4),
                "scene_change_score": round(float(scene_score), 4),
                "motion_score": round(float(motion_score), 4),
                "highlight_score": round(float(highlight_score), 4),
                "objects": detections,
            }
            samples.append(sample)
            chunk_samples.append(sample)
            processed_samples += 1
            previous = frame

        selected = _select_keyframes(
            chunk_samples,
            keyframes_per_chunk,
            minimum_gap,
        )
        chunk_keyframes: list[dict[str, Any]] = []
        for local_order, sample in enumerate(selected, start=1):
            keyframe_id = f"kf_c{chunk_number:04d}_{local_order:02d}"
            image_name = f"{keyframe_id}.jpg"
            annotated = _annotate_frame(
                frames[int(sample["chunk_frame_index"])],
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

        partial_result = HighlightExtractor().extract(
            [
                {
                    "timestamp": item["timestamp"],
                    "detections": item.get("objects", []),
                }
                for item in chunk_samples
            ],
            float(video.get("fps", 24.0)),
            duration,
        )
        provisional_segments = []
        for local_order, segment in enumerate(
            partial_result.get("segments", []),
            start=1,
        ):
            provisional = dict(segment)
            provisional.update(
                {
                    "id": f"seg_c{chunk_number:04d}_{local_order:02d}",
                    "chunk_id": chunk_id,
                    "provisional": True,
                }
            )
            provisional_segments.append(provisional)

        chunk_summary = {
            "id": chunk_id,
            "index": chunk_number,
            "start": round(float(chunk["start"]), 3),
            "end": round(float(chunk["end"]), 3),
            "status": "completed",
            "sample_count": len(chunk_samples),
            "keyframes": chunk_keyframes,
            "keyframe_ids": [item["id"] for item in chunk_keyframes],
            "provisional_segments": provisional_segments,
            "segment_ids": [],
        }
        analysis_chunks.append(chunk_summary)
        _notify_progress(
            progress_callback,
            {
                "stage": "detecting",
                "message": (
                    f"已完成 {len(analysis_chunks)}/{total_chunks} 个分析分块"
                ),
                "percent": round(
                    5.0 + 85.0 * (len(analysis_chunks) / total_chunks),
                    2,
                ),
                "total_chunks": total_chunks,
                "completed_chunks": len(analysis_chunks),
                "processed_frames": processed_samples,
                "total_frames": estimated_samples,
                "current_chunk": None,
                "chunks": analysis_chunks,
            },
        )

    if not samples or not keyframes:
        raise ValueError("视频中没有可分析的画面")

    best = max(keyframes, key=lambda item: item["highlight_score"])
    start, end = _bounded_clip(
        float(best["timestamp"]),
        duration,
        float(settings.get("target_duration", 30.0)),
    )
    output_ratio = str(settings.get("output_ratio", "16:9"))

    # 使用 HighlightExtractor 生成多片段（基于敌人出现/消失事件）
    fps = float(video.get("fps", 24.0))
    frame_results = [
        {
            "timestamp": s["timestamp"],
            "detections": s.get("objects", []),
        }
        for s in samples
    ]
    extractor = HighlightExtractor()
    highlight_result = extractor.extract(frame_results, fps, duration)
    segments = highlight_result.get("segments", [])

    # 向后兼容：如果没有多片段，回退到单片段
    if not segments:
        segments = [{
            "id": "seg_001",
            "order": 1,
            "start": start,
            "end": end,
            "score": best["highlight_score"],
            "source_keyframes": [best["id"]],
            "duration": round(end - start, 3),
            "peak_enemy_count": 0,
            "detected_classes": [],
            "enemy_classes_in_segment": [],
            "detections_summary": [],
            "reason": "highlight_score",
        }]

    # 给 segment 补充 source_keyframes（关联关键帧）
    for seg in segments:
        seg_keyframes = [
            kf["id"] for kf in keyframes
            if seg["start"] <= float(kf["timestamp"]) <= seg["end"]
        ]
        seg["source_keyframes"] = seg_keyframes if seg_keyframes else []
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
    _notify_progress(
        progress_callback,
        {
            "stage": "finalizing",
            "message": "正在归并跨分块片段并生成最终报告",
            "percent": 96.0,
            "total_chunks": total_chunks,
            "completed_chunks": len(analysis_chunks),
            "processed_frames": processed_samples,
            "total_frames": processed_samples,
            "current_chunk": None,
            "chunks": analysis_chunks,
        },
    )
    return {
        "video": video,
        "duration": duration,
        "settings": {key: value for key, value in settings.items() if key != "model_path"},
        "model": {"path": model_path.name},
        "analysis_mode": "streaming_chunks",
        "chunk_duration": chunk_duration,
        "analysis_chunks": analysis_chunks,
        "sample_interval": sample_interval,
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
            "start_time": segments[0]["start"] if segments else start,
            "end_time": segments[0]["end"] if segments else end,
            "output_ratio": output_ratio,
            "segment_count": len(segments),
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
            report = analyze_video(
                video_path,
                job_dir,
                settings,
                lambda value: self.jobs.write_progress(
                    job_id,
                    value,
                ),
            )
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
