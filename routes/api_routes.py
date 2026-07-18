"""JSON API routes for the Day08 video highlight backend."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from flask import Blueprint, current_app, jsonify, request
from werkzeug.datastructures import FileStorage

from services.analysis_service import AnalysisService
from services.ffmpeg_service import create_rough_cut, is_ffmpeg_available
from services.file_service import FileService, FileValidationError
from services.job_service import JobService, JobStateConflictError


api_bp = Blueprint("api", __name__, url_prefix="/api")


def _services() -> tuple[JobService, FileService, AnalysisService]:
    return (
        current_app.extensions["job_service"],
        current_app.extensions["file_service"],
        current_app.extensions["analysis_service"],
    )


def _number(
    source: dict[str, Any],
    key: str,
    default: float,
    *,
    minimum: float,
    maximum: float,
) -> float:
    raw = source.get(key, default)
    if isinstance(raw, bool):
        raise FileValidationError(f"{key} 必须是数字")
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise FileValidationError(f"{key} 必须是数字") from exc
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise FileValidationError(f"{key} 必须在 {minimum} 到 {maximum} 之间")
    return value


def _integer(
    source: dict[str, Any],
    key: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    raw = source.get(key, default)
    if isinstance(raw, bool):
        raise FileValidationError(f"{key} 必须是整数")
    try:
        text = str(raw).strip()
        value = int(text)
    except (TypeError, ValueError) as exc:
        raise FileValidationError(f"{key} 必须是整数") from exc
    if str(value) != text and not (text.startswith("+") and str(value) == text[1:]):
        raise FileValidationError(f"{key} 必须是整数")
    if not minimum <= value <= maximum:
        raise FileValidationError(f"{key} 必须在 {minimum} 到 {maximum} 之间")
    return value


def _parse_job_settings(form: dict[str, Any]) -> dict[str, Any]:
    defaults = current_app.config["DEFAULT_JOB_SETTINGS"]
    settings = {
        "sample_interval": _number(
            form,
            "sample_interval",
            defaults["sample_interval"],
            minimum=0.1,
            maximum=3600.0,
        ),
        "target_duration": _number(
            form,
            "target_duration",
            defaults["target_duration"],
            minimum=0.1,
            maximum=86400.0,
        ),
        "max_keyframes": _integer(
            form,
            "max_keyframes",
            defaults["max_keyframes"],
            minimum=1,
            maximum=1000,
        ),
        "min_keyframe_gap": _number(
            form,
            "min_keyframe_gap",
            defaults["min_keyframe_gap"],
            minimum=0.0,
            maximum=86400.0,
        ),
        "object_weight": _number(
            form,
            "object_weight",
            defaults["object_weight"],
            minimum=0.0,
            maximum=1.0,
        ),
        "scene_change_weight": _number(
            form,
            "scene_change_weight",
            defaults["scene_change_weight"],
            minimum=0.0,
            maximum=1.0,
        ),
        "motion_weight": _number(
            form,
            "motion_weight",
            defaults["motion_weight"],
            minimum=0.0,
            maximum=1.0,
        ),
        "output_ratio": str(form.get("output_ratio", defaults["output_ratio"])).strip(),
    }
    weight_sum = (
        settings["object_weight"]
        + settings["scene_change_weight"]
        + settings["motion_weight"]
    )
    if not math.isclose(weight_sum, 1.0, abs_tol=1e-6):
        raise FileValidationError("object_weight、scene_change_weight 与 motion_weight 之和必须为 1")
    if settings["output_ratio"] not in current_app.config["ALLOWED_OUTPUT_RATIOS"]:
        raise FileValidationError("output_ratio 仅支持 16:9、9:16 或 1:1")
    return settings


def _duration(job: dict[str, Any], report: dict[str, Any]) -> float | None:
    candidates = [job.get("duration"), report.get("duration")]
    video = report.get("video")
    if isinstance(video, dict):
        candidates.append(video.get("duration"))
    for candidate in candidates:
        if isinstance(candidate, (int, float)) and not isinstance(candidate, bool):
            value = float(candidate)
            if math.isfinite(value) and value >= 0:
                return value
    return None


def _validate_clip(value: Any, duration: float | None) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise FileValidationError("recommended_clip 必须是 JSON 对象")
    clip = dict(value)
    if "start_time" not in clip or "end_time" not in clip:
        raise FileValidationError("recommended_clip 必须包含 start_time 和 end_time")
    start = _number(
        clip, "start_time", 0.0, minimum=0.0, maximum=86_400_000.0
    )
    end = _number(
        clip, "end_time", 0.0, minimum=0.0, maximum=86_400_000.0
    )
    if start >= end:
        raise FileValidationError("推荐片段必须满足 0 <= start_time < end_time")
    if duration is not None and end > duration:
        raise FileValidationError("推荐片段 end_time 不能超过视频时长")
    ratio = str(clip.get("output_ratio", "16:9")).strip()
    if ratio not in current_app.config["ALLOWED_OUTPUT_RATIOS"]:
        raise FileValidationError("output_ratio 仅支持 16:9、9:16 或 1:1")
    clip.update(start_time=start, end_time=end, output_ratio=ratio)
    return clip


def _validate_keyframes(value: Any, duration: float | None) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise FileValidationError("keyframes 必须是数组")
    keyframes: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise FileValidationError(f"keyframes[{index}] 必须是 JSON 对象")
        frame = dict(item)
        if "timestamp" in frame:
            timestamp = _number(
                frame,
                "timestamp",
                0.0,
                minimum=0.0,
                maximum=86_400_000.0,
            )
            if duration is not None and timestamp > duration:
                raise FileValidationError(f"keyframes[{index}].timestamp 超过视频时长")
            frame["timestamp"] = timestamp
        if "keep" in frame and not isinstance(frame["keep"], bool):
            raise FileValidationError(f"keyframes[{index}].keep 必须是布尔值")
        if "decision" in frame and frame["decision"] not in {"keep", "skip"}:
            raise FileValidationError(
                f"keyframes[{index}].decision 仅支持 keep 或 skip"
            )
        if "order" in frame:
            frame["order"] = _integer(
                frame, "order", index, minimum=0, maximum=100_000
            )
        for field, limit in (("label", 100), ("note", 1000)):
            if field in frame:
                if not isinstance(frame[field], str):
                    raise FileValidationError(
                        f"keyframes[{index}].{field} 必须是字符串"
                    )
                if len(frame[field]) > limit:
                    raise FileValidationError(
                        f"keyframes[{index}].{field} 长度不能超过 {limit}"
                    )
        keyframes.append(frame)
    return keyframes


def _validate_segments(value: Any, duration: float | None) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise FileValidationError("segments 必须是非空数组")
    segments: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise FileValidationError(f"segments[{index}] 必须是 JSON 对象")
        segment = dict(item)
        start = _number(
            segment, "start", 0.0, minimum=0.0, maximum=86_400_000.0
        )
        end = _number(
            segment, "end", 0.0, minimum=0.0, maximum=86_400_000.0
        )
        if start >= end:
            raise FileValidationError(
                f"segments[{index}] 必须满足 0 <= start < end"
            )
        if duration is not None and end > duration:
            raise FileValidationError(f"segments[{index}].end 超过视频时长")
        order = _integer(
            segment, "order", index + 1, minimum=1, maximum=100_000
        )
        segment.update(
            id=str(segment.get("id") or f"seg_{index + 1:03d}"),
            start=start,
            end=end,
            order=order,
        )
        segments.append(segment)
    return sorted(segments, key=lambda item: item["order"])


def _json_object(*, optional: bool = False) -> dict[str, Any]:
    if optional and not request.data:
        return {}
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise FileValidationError("请求体必须是合法的 JSON 对象")
    return payload


@api_bp.get("/health")
def health():
    model_path = Path(current_app.config["MODEL_PATH"])
    return jsonify(
        ok=True,
        status="ok",
        service="reelfire",
        version="1.0.0",
        model_ready=model_path.is_file(),
        ffmpeg_ready=is_ffmpeg_available(),
    )


@api_bp.post("/jobs")
def create_job():
    jobs, files, _ = _services()
    upload = request.files.get("file")
    if not isinstance(upload, FileStorage):
        raise FileValidationError("缺少必填的 file 字段")

    original_name, _ = files.validate_filename(upload)
    settings = _parse_job_settings(request.form.to_dict(flat=True))
    project_name = request.form.get(
        "project_name", current_app.config["DEFAULT_PROJECT_NAME"]
    ).strip()
    if not project_name:
        project_name = current_app.config["DEFAULT_PROJECT_NAME"]
    if len(project_name) > 100:
        raise FileValidationError("project_name 长度不能超过 100")
    game_type = str(request.form.get("game_type", "other")).strip().lower()
    if game_type not in {"csgo", "valorant", "other"}:
        raise FileValidationError("game_type 仅支持 csgo、valorant 或 other")

    job_id, job_dir = jobs.reserve_workspace()
    try:
        saved_path = files.save_upload(upload, job_dir / "input")
        job = jobs.create_job_record(
            job_id,
            project_name,
            saved_path.name,
            settings,
        )
        if original_name != saved_path.name:
            job = jobs.update_job(job_id, original_asset_name=original_name)
        job = jobs.update_job(job_id, game_type=game_type)
    except Exception:
        jobs.discard_workspace(job_id)
        raise
    return jsonify(ok=True, job_id=job_id, status=job["status"]), 201


@api_bp.get("/jobs")
def list_jobs():
    jobs, _, _ = _services()
    return jsonify(ok=True, jobs=jobs.list_jobs())


@api_bp.get("/jobs/<job_id>")
def get_job(job_id: str):
    jobs, _, _ = _services()
    return jsonify(ok=True, job=jobs.get_job_detail(job_id))


@api_bp.delete("/jobs/<job_id>")
def delete_job(job_id: str):
    jobs, _, _ = _services()
    jobs.delete_job(job_id)
    return jsonify(ok=True, deleted_job_id=job_id)


@api_bp.post("/jobs/<job_id>/analyze")
def analyze_job(job_id: str):
    jobs, _, analysis = _services()
    jobs.get_job(job_id)
    analysis.enqueue(job_id)
    return jsonify(ok=True, job_id=job_id, status="queued"), 202


@api_bp.patch("/jobs/<job_id>/review")
def review_job(job_id: str):
    jobs, _, _ = _services()
    job = jobs.get_job(job_id)
    if not jobs.report_path(job_id).is_file():
        raise JobStateConflictError("分析报告尚未生成，不能进行人工审核")
    report = jobs.read_report(job_id)
    payload = _json_object()
    unexpected = set(payload) - {"keyframes", "recommended_clip", "segments"}
    if unexpected:
        raise FileValidationError(f"不支持的审核字段：{', '.join(sorted(unexpected))}")
    if not payload:
        raise FileValidationError("至少提交 keyframes、segments 或 recommended_clip")
    duration = _duration(job, report)
    changes: dict[str, Any] = {}
    if "keyframes" in payload:
        changes["keyframes"] = _validate_keyframes(payload["keyframes"], duration)
    if "recommended_clip" in payload:
        changes["recommended_clip"] = _validate_clip(
            payload["recommended_clip"], duration
        )
    if "segments" in payload:
        segments = _validate_segments(payload["segments"], duration)
        changes["segments"] = segments
        first = segments[0]
        existing_clip = report.get("recommended_clip", {})
        ratio = (
            existing_clip.get("output_ratio", "16:9")
            if isinstance(existing_clip, dict)
            else "16:9"
        )
        changes["recommended_clip"] = _validate_clip(
            {
                "start_time": first["start"],
                "end_time": first["end"],
                "output_ratio": ratio,
            },
            duration,
        )

    updated = jobs.update_report(job_id, lambda current: {**current, **changes})
    jobs.update_job(job_id)
    return jsonify(ok=True, report=updated)


@api_bp.post("/jobs/<job_id>/rough-cut")
def rough_cut(job_id: str):
    jobs, _, _ = _services()
    job = jobs.get_job(job_id)
    if job.get("status") != "completed":
        raise JobStateConflictError("只有 completed 任务可以生成粗剪视频")
    if not jobs.report_path(job_id).is_file():
        raise JobStateConflictError("分析报告尚未生成，不能生成粗剪视频")
    report = jobs.read_report(job_id)
    payload = _json_object(optional=True)
    recommended = report.get("recommended_clip")
    if not isinstance(recommended, dict):
        raise FileValidationError("分析报告中缺少 recommended_clip")
    clip_source = dict(recommended)
    for field in ("start_time", "end_time", "output_ratio"):
        if field in payload:
            clip_source[field] = payload[field]
    clip = _validate_clip(clip_source, _duration(job, report))
    if not is_ffmpeg_available():
        return jsonify(ok=False, error="FFmpeg 不可用，无法生成粗剪视频"), 501

    job_dir = jobs.job_dir(job_id)
    ratio_label = clip["output_ratio"].replace(":", "x")
    output_path = job_dir / "result" / f"rough_cut_{ratio_label}.mp4"
    try:
        result_path = create_rough_cut(
            jobs.get_input_video(job_id),
            output_path,
            clip["start_time"],
            clip["end_time"],
            clip["output_ratio"],
        )
    except NotImplementedError as exc:
        return jsonify(ok=False, error=str(exc)), 501
    result_path = Path(result_path).resolve()
    result_dir = (job_dir / "result").resolve()
    if result_path.parent != result_dir or not result_path.is_file():
        raise RuntimeError("粗剪服务未生成有效输出文件")
    relative = result_path.relative_to(job_dir).as_posix()
    jobs.update_job(job_id, rough_cut_file=relative)
    def update_output(current: dict[str, Any]) -> dict[str, Any]:
        output = current.get("output")
        if not isinstance(output, dict):
            output = {}
        output = {**output, "video": relative, "ratio": clip["output_ratio"]}
        return {
            **current,
            "recommended_clip": clip,
            "output": output,
        }

    jobs.update_report(job_id, update_output)
    return jsonify(ok=True, job_id=job_id, rough_cut_file=relative)


@api_bp.get("/jobs/<job_id>/report")
def get_report(job_id: str):
    jobs, _, _ = _services()
    return jsonify(ok=True, report=jobs.read_report(job_id))
