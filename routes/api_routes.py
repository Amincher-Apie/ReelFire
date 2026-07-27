"""JSON API routes for the Day08 video highlight backend."""

from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import Blueprint, current_app, jsonify, request, session
from werkzeug.datastructures import FileStorage

from database import get_db
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


@api_bp.get("/jobs/<job_id>/editor")
def get_editor(job_id: str):
    """返回剪辑预览工作台所需的聚合数据。

    聚合 CV 报告和 Agent 评论，统一为编辑页提供数据。
    Agent 评论不存在时返回空数组，编辑页展示 pending 状态。
    """
    jobs, _, _ = _services()
    job = jobs.get_job(job_id)
    report = jobs.read_report(job_id) if job.get("status") == "completed" else {}

    video = report.get("video") or {}
    segments = report.get("segments") or []
    keyframes = report.get("keyframes") or []
    output = report.get("output") or {}

    # 获取源视频文件路径（用于编辑器预览播放）
    job_dir = jobs.job_dir(job_id)
    input_video = jobs.get_input_video(job_id)
    try:
        input_video_relative = input_video.resolve().relative_to(job_dir.resolve()).as_posix()
    except (ValueError, OSError):
        input_video_relative = None

    # 尝试读取 Agent 报告（agent_report.json）
    agent_comments = []
    try:
        agent_report = jobs.read_agent_report(job_id)
        agent_comments = agent_report.get("segment_comments") or []
    except Exception:
        agent_comments = []

    return jsonify(
        ok=True,
        job_id=job_id,
        status=job.get("status", "unknown"),
        video={
            "duration": video.get("duration"),
            "width": video.get("width"),
            "height": video.get("height"),
            "fps": video.get("fps"),
            "has_audio": video.get("has_audio", False),
            "filename": input_video.name if input_video_relative else "",
            "path": (
                output.get("video")
                if output.get("video")
                else input_video_relative
            ),
        },
        segments=segments,
        agent_comments=agent_comments,
        keyframes=keyframes,
    )


# ── Project endpoints (SQLite-backed) ──────────────────────────────────

def _current_user_id() -> int | None:
    return session.get("user_id")


def _require_user() -> int:
    user_id = _current_user_id()
    if user_id is None:
        from services.file_service import FileValidationError
        raise FileValidationError("请先登录后再操作项目")
    return user_id


@api_bp.post("/projects")
def create_project():
    """Create a new project for the authenticated user."""
    user_id = _require_user()
    payload = _json_object()
    name = str(payload.get("name", "")).strip()
    if not name or len(name) > 100:
        raise FileValidationError("project name 必须为 1-100 个字符")
    game_type = str(payload.get("game_type", "other")).strip().lower()
    if game_type not in {"csgo", "valorant", "other"}:
        raise FileValidationError("game_type 仅支持 csgo、valorant 或 other")

    db = get_db()
    now = datetime.now().replace(microsecond=0).isoformat()
    cursor = db.execute(
        """
        INSERT INTO projects (owner_id, name, game_type, status, created_at, updated_at)
        VALUES (?, ?, ?, 'active', ?, ?)
        """,
        (user_id, name, game_type, now, now),
    )
    db.commit()
    return jsonify(
        ok=True,
        project={
            "id": cursor.lastrowid,
            "owner_id": user_id,
            "name": name,
            "game_type": game_type,
            "status": "active",
            "created_at": now,
            "updated_at": now,
        },
    ), 201


@api_bp.get("/projects")
def list_projects():
    """List projects belonging to the authenticated user."""
    user_id = _require_user()
    db = get_db()
    rows = db.execute(
        """
        SELECT id, owner_id, name, description, game_type, status, created_at, updated_at
        FROM projects
        WHERE owner_id = ? AND status = 'active'
        ORDER BY updated_at DESC
        """,
        (user_id,),
    ).fetchall()
    return jsonify(
        ok=True,
        projects=[dict(row) for row in rows],
    )


@api_bp.get("/projects/<int:project_id>")
def get_project(project_id: int):
    """Get a single project by id."""
    user_id = _require_user()
    db = get_db()
    row = db.execute(
        """
        SELECT id, owner_id, name, description, game_type, status, created_at, updated_at
        FROM projects
        WHERE id = ? AND owner_id = ?
        """,
        (project_id, user_id),
    ).fetchone()
    if row is None:
        return jsonify(ok=False, error="项目不存在"), 404
    return jsonify(ok=True, project=dict(row))


@api_bp.patch("/projects/<int:project_id>")
def update_project(project_id: int):
    """Rename a project."""
    user_id = _require_user()
    payload = _json_object()
    name = str(payload.get("name", "")).strip()
    if not name or len(name) > 100:
        raise FileValidationError("project name 必须为 1-100 个字符")
    db = get_db()
    row = db.execute(
        "SELECT id FROM projects WHERE id = ? AND owner_id = ? AND status = 'active'",
        (project_id, user_id),
    ).fetchone()
    if row is None:
        return jsonify(ok=False, error="项目不存在"), 404
    now = datetime.now().replace(microsecond=0).isoformat()
    db.execute(
        "UPDATE projects SET name = ?, updated_at = ? WHERE id = ?",
        (name, now, project_id),
    )
    db.commit()
    return jsonify(ok=True, project={"id": project_id, "name": name, "updated_at": now})


@api_bp.delete("/projects/<int:project_id>")
def archive_project(project_id: int):
    """Soft-delete (archive) a project."""
    user_id = _require_user()
    db = get_db()
    row = db.execute(
        "SELECT id FROM projects WHERE id = ? AND owner_id = ? AND status = 'active'",
        (project_id, user_id),
    ).fetchone()
    if row is None:
        return jsonify(ok=False, error="项目不存在"), 404
    now = datetime.now().replace(microsecond=0).isoformat()
    db.execute(
        "UPDATE projects SET status = 'archived', updated_at = ? WHERE id = ?",
        (now, project_id),
    )
    db.commit()
    return jsonify(ok=True, deleted_project_id=project_id)


# ── Job control ──────────────────────────────────────────────────────────

@api_bp.post("/jobs/<job_id>/cancel")
def cancel_job(job_id: str):
    """Cancel a queued or running job."""
    jobs, _, analysis = _services()
    job = jobs.get_job(job_id)
    if job.get("status") not in ("queued", "running"):
        raise JobStateConflictError("只能取消排队中或运行中的任务")
    analysis.cancel_job(job_id)
    jobs.update_job(job_id, status="failed", error="用户取消任务")
    return jsonify(ok=True, job_id=job_id, status="cancelled")


@api_bp.post("/jobs/<job_id>/retry")
def retry_job(job_id: str):
    """Retry a failed job."""
    jobs, _, analysis = _services()
    job = jobs.get_job(job_id)
    if job.get("status") != "failed":
        raise JobStateConflictError("只能重试失败的任务")
    analysis.enqueue(job_id)
    return jsonify(ok=True, job_id=job_id, status="queued"), 202


# ── Manual segment CRUD ──────────────────────────────────────────────────

def _read_report_or_raise(jobs: JobService, job_id: str) -> dict[str, Any]:
    if not jobs.report_path(job_id).is_file():
        raise JobStateConflictError("分析报告尚未生成，不能操作片段")
    return jobs.read_report(job_id)


@api_bp.post("/jobs/<job_id>/segments")
def add_segment(job_id: str):
    """Add a manual segment to the report."""
    jobs, _, _ = _services()
    report = _read_report_or_raise(jobs, job_id)
    payload = _json_object()
    start = _number(payload, "start", 0, minimum=0, maximum=86_400_000)
    end = _number(payload, "end", 0, minimum=0, maximum=86_400_000)
    if start >= end:
        raise FileValidationError("必须满足 0 <= start < end")

    segments = list(report.get("segments") or [])
    max_order = max((s.get("order", 0) for s in segments), default=0)
    new_seg = {
        "id": payload.get("id") or f"manual_{len(segments) + 1:03d}",
        "start": start,
        "end": end,
        "score": 0,
        "order": max_order + 1,
        "source_keyframes": [],
        "type": "manual",
    }
    segments.append(new_seg)

    def update_fn(current: dict[str, Any]) -> dict[str, Any]:
        return {**current, "segments": segments}

    updated = jobs.update_report(job_id, update_fn)
    return jsonify(ok=True, segment=new_seg, report=updated), 201


@api_bp.delete("/jobs/<job_id>/segments/<seg_id>")
def delete_segment(job_id: str, seg_id: str):
    """Delete/ignore a segment from the report."""
    jobs, _, _ = _services()
    report = _read_report_or_raise(jobs, job_id)
    segments = list(report.get("segments") or [])
    original_len = len(segments)
    segments = [s for s in segments if str(s.get("id")) != seg_id]
    if len(segments) == original_len:
        return jsonify(ok=False, error="片段不存在"), 404

    def update_fn(current: dict[str, Any]) -> dict[str, Any]:
        return {**current, "segments": segments}

    updated = jobs.update_report(job_id, update_fn)
    return jsonify(ok=True, deleted_segment_id=seg_id, report=updated)


@api_bp.patch("/jobs/<job_id>/segments/<seg_id>")
def update_segment(job_id: str, seg_id: str):
    """Update a segment's boundary, order, or status."""
    jobs, _, _ = _services()
    report = _read_report_or_raise(jobs, job_id)
    payload = _json_object()
    segments = list(report.get("segments") or [])

    target = None
    for s in segments:
        if str(s.get("id")) == seg_id:
            target = s
            break
    if target is None:
        return jsonify(ok=False, error="片段不存在"), 404

    if "start" in payload:
        start = _number(payload, "start", 0, minimum=0, maximum=86_400_000)
        if start >= target.get("end", start + 1):
            raise FileValidationError("start 必须小于 end")
        target["start"] = start
    if "end" in payload:
        end = _number(payload, "end", 0, minimum=0, maximum=86_400_000)
        if end <= target.get("start", 0):
            raise FileValidationError("end 必须大于 start")
        target["end"] = end
    if "order" in payload:
        target["order"] = _integer(payload, "order", target.get("order", 0), minimum=1, maximum=100_000)

    def update_fn(current: dict[str, Any]) -> dict[str, Any]:
        return {**current, "segments": segments}

    updated = jobs.update_report(job_id, update_fn)
    return jsonify(ok=True, segment=target, report=updated)


@api_bp.post("/jobs/<job_id>/segments/merge")
def merge_segments(job_id: str):
    """Merge two adjacent segments into one."""
    jobs, _, _ = _services()
    report = _read_report_or_raise(jobs, job_id)
    payload = _json_object()
    seg_id_1 = str(payload.get("seg_id_1") or payload.get("segment_1") or "")
    seg_id_2 = str(payload.get("seg_id_2") or payload.get("segment_2") or "")
    if not seg_id_1 or not seg_id_2:
        raise FileValidationError("必须提供 seg_id_1 和 seg_id_2")

    segments = list(report.get("segments") or [])
    seg1 = seg2 = None
    remaining = []
    for s in segments:
        sid = str(s.get("id"))
        if sid == seg_id_1:
            seg1 = s
        elif sid == seg_id_2:
            seg2 = s
        else:
            remaining.append(s)

    if seg1 is None or seg2 is None:
        return jsonify(ok=False, error="至少一个片段不存在"), 404

    merged = {
        "id": f"merged_{seg_id_1}_{seg_id_2}",
        "start": min(seg1["start"], seg2["start"]),
        "end": max(seg1["end"], seg2["end"]),
        "score": max(seg1.get("score", 0), seg2.get("score", 0)),
        "order": min(seg1.get("order", 0), seg2.get("order", 0)),
        "source_keyframes": list(
            set(seg1.get("source_keyframes", []) + seg2.get("source_keyframes", []))
        ),
        "type": "merged",
    }
    remaining.append(merged)
    remaining.sort(key=lambda s: s.get("order", 0))

    def update_fn(current: dict[str, Any]) -> dict[str, Any]:
        return {**current, "segments": remaining}

    updated = jobs.update_report(job_id, update_fn)
    return jsonify(ok=True, segment=merged, report=updated)


@api_bp.post("/jobs/<job_id>/segments/<seg_id>/split")
def split_segment(job_id: str, seg_id: str):
    """Split a segment into two at the given time point."""
    jobs, _, _ = _services()
    report = _read_report_or_raise(jobs, job_id)
    payload = _json_object()
    split_time = _number(payload, "split_time", 0, minimum=0, maximum=86_400_000)

    segments = list(report.get("segments") or [])
    target = None
    for s in segments:
        if str(s.get("id")) == seg_id:
            target = s
            break
    if target is None:
        return jsonify(ok=False, error="片段不存在"), 404
    if split_time <= target["start"] or split_time >= target["end"]:
        raise FileValidationError("split_time 必须在片段的 start 和 end 之间")

    seg_a = {
        "id": f"{seg_id}_a",
        "start": target["start"],
        "end": split_time,
        "score": target.get("score", 0),
        "order": target.get("order", 0),
        "source_keyframes": list(target.get("source_keyframes", [])),
        "type": "split",
    }
    seg_b = {
        "id": f"{seg_id}_b",
        "start": split_time,
        "end": target["end"],
        "score": target.get("score", 0),
        "order": target.get("order", 0) + 1,
        "source_keyframes": list(target.get("source_keyframes", [])),
        "type": "split",
    }

    new_segments = []
    for s in segments:
        if str(s.get("id")) == seg_id:
            new_segments.append(seg_a)
            new_segments.append(seg_b)
        else:
            new_segments.append(s)

    def update_fn(current: dict[str, Any]) -> dict[str, Any]:
        return {**current, "segments": new_segments}

    updated = jobs.update_report(job_id, update_fn)
    return jsonify(ok=True, segments=[seg_a, seg_b], report=updated)


# ── Export ───────────────────────────────────────────────────────────────

@api_bp.post("/jobs/<job_id>/export")
def export_job(job_id: str):
    """Start an export task (single clip or collection).

    Body: {mode: "single"|"collection", segments: [...], aspect_ratio, resolution,
           keep_audio: bool, filename: str}
    """
    jobs, _, _ = _services()
    job = jobs.get_job(job_id)
    if job.get("status") != "completed":
        raise JobStateConflictError("只有已完成的任务可以导出")
    if not is_ffmpeg_available():
        return jsonify(ok=False, error="FFmpeg 不可用，无法导出"), 501

    payload = _json_object()
    mode = str(payload.get("mode", "collection")).strip()
    if mode not in ("single", "collection"):
        raise FileValidationError("mode 仅支持 single 或 collection")
    aspect_ratio = str(payload.get("aspect_ratio", "16:9")).strip()
    if aspect_ratio not in current_app.config["ALLOWED_OUTPUT_RATIOS"]:
        raise FileValidationError("aspect_ratio 仅支持 16:9、9:16 或 1:1")
    resolution = str(payload.get("resolution", "original")).strip()
    if resolution not in ("original", "1080p", "720p"):
        raise FileValidationError("resolution 仅支持 original、1080p 或 720p")
    keep_audio = bool(payload.get("keep_audio", True))
    filename = str(payload.get("filename", "")).strip()
    if not filename:
        filename = f"export_{mode}_{job_id[:8]}"
    # Sanitize filename
    filename = "".join(c for c in filename if c.isalnum() or c in "._-") or "export"

    report = jobs.read_report(job_id)
    segments = list(report.get("segments") or [])
    requested_segments = payload.get("segments")

    if mode == "single":
        # Single segment export: export each requested segment separately
        if not isinstance(requested_segments, list) or not requested_segments:
            raise FileValidationError("单片段导出需要提供 segments 数组")
        seg_ids = [str(s.get("id", "")) for s in requested_segments]
        target_segs = [s for s in segments if str(s.get("id")) in seg_ids]
        if not target_segs:
            raise FileValidationError("未找到要导出的片段")

        results = []
        job_dir = jobs.job_dir(job_id)
        input_video = jobs.get_input_video(job_id)
        ratio_label = aspect_ratio.replace(":", "x")
        for i, seg in enumerate(target_segs):
            out_path = job_dir / "result" / f"{filename}_{i + 1}_{ratio_label}.mp4"
            try:
                result_path = create_rough_cut(
                    input_video, out_path, seg["start"], seg["end"], aspect_ratio
                )
                relative = Path(result_path).resolve().relative_to(job_dir.resolve()).as_posix()
                results.append({
                    "segment_id": seg["id"],
                    "output": relative,
                    "start": seg["start"],
                    "end": seg["end"],
                })
            except NotImplementedError as exc:
                return jsonify(ok=False, error=str(exc)), 501
        return jsonify(ok=True, job_id=job_id, mode=mode, exports=results)

    # Collection mode: merge all requested/adopted segments
    if isinstance(requested_segments, list) and requested_segments:
        seg_ids = [str(s.get("id", "")) for s in requested_segments]
        target_segs = [s for s in segments if str(s.get("id")) in seg_ids]
    else:
        target_segs = sorted(segments, key=lambda s: s.get("order", 0))

    if not target_segs:
        raise FileValidationError("没有可导出的片段")

    # Use ffmpeg to concatenate segments (via concat demuxer)
    job_dir = jobs.job_dir(job_id)
    input_video = jobs.get_input_video(job_id)
    ratio_label = aspect_ratio.replace(":", "x")
    out_path = job_dir / "result" / f"{filename}_{ratio_label}.mp4"

    try:
        import subprocess
        import tempfile

        # Write concat file
        concat_lines = []
        for seg in target_segs:
            duration = seg["end"] - seg["start"]
            concat_lines.append(f"file '{input_video.as_posix()}'")
            concat_lines.append(f"inpoint {seg['start']}")
            concat_lines.append(f"outpoint {seg['end']}")

        concat_file = job_dir / "result" / "_concat_list.txt"
        concat_file.write_text("\n".join(concat_lines), encoding="utf-8")

        resolution_map = {"original": None, "1080p": "1920:1080", "720p": "1280:720"}
        scale_filter = ""
        if resolution_map.get(resolution):
            scale_filter = f",scale={resolution_map[resolution]}"

        vf_parts = [f"crop=ih*{aspect_ratio.replace(':', '/')}:ih", f"scale=iw:ih{scale_filter}"]
        vf_combined = ",".join(p for p in vf_parts if p)

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_file),
        ]
        if not keep_audio:
            cmd += ["-an"]
        cmd += [
            "-c:v", "libx264", "-preset", "medium", "-crf", "23",
            "-c:a", "aac" if keep_audio else "copy",
            "-vf", vf_combined,
            "-movflags", "+faststart",
            str(out_path),
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg 导出失败: {result.stderr[:500]}")

        # Clean up concat file
        concat_file.unlink(missing_ok=True)

        relative = out_path.resolve().relative_to(job_dir.resolve()).as_posix()

        # Update report output
        def update_output(current: dict[str, Any]) -> dict[str, Any]:
            output = current.get("output") or {}
            if not isinstance(output, dict):
                output = {}
            exports = list(output.get("exports") or [])
            exports.append({
                "file": relative,
                "mode": mode,
                "aspect_ratio": aspect_ratio,
                "resolution": resolution,
                "segment_count": len(target_segs),
                "created_at": datetime.now().isoformat(),
            })
            return {**current, "output": {**output, "video": relative, "exports": exports}}

        jobs.update_report(job_id, update_output)
        jobs.update_job(job_id)

        return jsonify(
            ok=True,
            job_id=job_id,
            mode=mode,
            export={
                "file": relative,
                "segment_count": len(target_segs),
                "total_duration": sum(s["end"] - s["start"] for s in target_segs),
            },
        )
    except subprocess.TimeoutExpired:
        return jsonify(ok=False, error="导出超时"), 500
    except Exception as exc:
        return jsonify(ok=False, error=f"导出失败: {str(exc)}"), 500
