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

from cv_engine.highlight_extractor import HighlightExtractor
from cv_engine.highlight_scorer import HighlightScorer
from cv_engine.model_registry import ModelRegistry
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
    model_registry: ModelRegistry | None = None,
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

    # Resolve model path using registry if available
    # P0-1: 根据 game_type 动态选择模型和分析策略
    game_type = str(settings.get("game_type", "other")).lower().strip()
    is_fallback = False
    highlight_strategy = "generic_score"
    enemy_classes: set[str] = set()

    if model_registry:
        # 优先按 game_type 选择（P0-1 核心改动）
        model_info, strategy, is_fallback = model_registry.resolve_by_game_type(game_type)
        model_path = model_info.model_path
        enemy_classes = set(strategy.get("enemy_classes", set()))
        highlight_strategy = str(strategy.get("highlight_strategy", "generic_score"))
    else:
        model_path = Path(str(settings.get("model_path", "models/yolo11n.pt")))
        model_info = None
        # 无 registry 时，按 game_type 设置默认 enemy_classes
        if game_type == "csgo":
            enemy_classes = {"character_ct", "character_t"}
            highlight_strategy = "enemy_engagement"
        elif game_type == "valorant":
            enemy_classes = {"enemy"}
            highlight_strategy = "enemy_engagement"
        else:
            enemy_classes = {"person"}
            highlight_strategy = "generic_score"

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

    # 使用 HighlightExtractor 生成多片段（基于敌人出现/消失事件）
    # P0-1: 根据 game_type 传入对应的 enemy_classes
    fps = float(video.get("fps", 24.0))
    frame_results = [
        {
            "timestamp": s["timestamp"],
            "detections": s.get("objects", []),
        }
        for s in samples
    ]
    extractor = HighlightExtractor(enemy_classes=enemy_classes if enemy_classes else None)
    highlight_result = extractor.extract(frame_results, fps, duration)
    segments = highlight_result.get("segments", [])

    # P0-2: 没有真实 FPS 事件（无敌人出现）时返回空 segments，
    # 不再无条件生成 30 秒默认片段，由前端引导用户降低阈值或手动添加。
    if not segments:
        segments = []

    # 给 segment 补充 source_keyframes（关联关键帧）+ 代表关键帧 + 缩略图
    # P0: 分工要求"代表关键帧、缩略图、对应关键帧截图"
    seg_thumb_dir = job_dir / "result" / "segment_thumbs"
    seg_thumb_dir.mkdir(parents=True, exist_ok=True)

    for seg in segments:
        seg_keyframes = [
            kf for kf in keyframes
            if seg["start"] <= float(kf["timestamp"]) <= seg["end"]
        ]
        seg["source_keyframes"] = [kf["id"] for kf in seg_keyframes] if seg_keyframes else []

        # 代表关键帧：优先从 source_keyframes 中选 score 最高的
        if seg_keyframes:
            rep_kf = max(seg_keyframes, key=lambda kf: kf.get("highlight_score", 0.0))
            seg["representative_keyframe"] = rep_kf["id"]
            seg["thumbnail"] = rep_kf.get("image")
        else:
            # 没有关键帧时，从 segment 时间范围内选 score 最高的 sample 生成缩略图
            seg_samples = [
                s for s in samples
                if seg["start"] <= float(s["timestamp"]) <= seg["end"]
            ]
            rep_id = None
            thumb_rel = None
            if seg_samples:
                best_sample = max(seg_samples, key=lambda s: s.get("highlight_score", 0.0))
                frame_idx = int(best_sample["frame_index"])
                if 0 <= frame_idx < len(frames):
                    thumb_name = f"{seg['id']}_thumb.jpg"
                    thumb_path = seg_thumb_dir / thumb_name
                    annotated = _annotate_frame(frames[frame_idx], best_sample.get("objects", []))
                    if cv2.imwrite(str(thumb_path), annotated):
                        thumb_rel = f"result/segment_thumbs/{thumb_name}"
            seg["representative_keyframe"] = rep_id
            seg["thumbnail"] = thumb_rel

        # 在 evidence 中引用代表关键帧（供 Agent 引用）
        seg["evidence"]["representative_keyframe"] = seg.get("representative_keyframe")
        seg["evidence"]["thumbnail"] = seg.get("thumbnail")

    segment_tags = scorer.calculate_segment_tags(samples, segments)
    ai_cover_prompt = scorer.generate_cover_prompt(best)

    contact_sheet = job_dir / "result" / "contact_sheet.jpg"
    contact_sheet_ready = _save_contact_sheet(selected, frames, contact_sheet)

    # Build model info for report
    model_report = {"path": model_path.name}
    if model_info:
        model_report.update({
            "id": model_info.model_id,
            "display_name": model_info.display_name,
            "is_custom": model_info.is_custom,
            "num_classes": model_info.num_classes,
            "class_names": model_info.class_names,
            "mAP50": model_info.mAP50,
            "mAP50_95": model_info.mAP50_95,
        })
    # P0-1: 报告中记录游戏类型和分析策略，让前端可见
    # P0-3: 报告中保存模型版本和阈值（分工要求"模型 ID、模型版本、阈值和类别表"）
    model_report.update({
        "game_type": game_type,
        "highlight_strategy": highlight_strategy,
        "is_fallback": is_fallback,
        "enemy_classes": sorted(enemy_classes) if enemy_classes else [],
        "version": model_info.model_id if model_info else "unknown",
        "confidence_threshold": float(settings.get("confidence_threshold", 0.35)),
        "sample_interval": sample_interval,
    })

    return {
        "video": video,
        "duration": duration,
        "settings": {key: value for key, value in settings.items() if key != "model_path"},
        "model": model_report,
        "sample_interval": sample_interval,
        "total_sampled_frames": len(samples),
        "score_weights": {
            "object": object_weight,
            "scene_change": scene_weight,
            "motion": motion_weight,
        },
        "samples": samples,
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
        self.model_registry = ModelRegistry(Path(__file__).resolve().parent.parent)
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
            # P0-1: 不再固定使用全局 model_path，改为按 game_type 动态选择
            # settings["model_path"] = str(self.model_path)  # 已弃用
            settings["game_type"] = job.get("game_type", "other")
            report = analyze_video(
                video_path, job_dir, settings, model_registry=self.model_registry
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
