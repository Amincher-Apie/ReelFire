"""JSON API routes for the Day08 video highlight backend."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from flask import Blueprint, current_app, jsonify, request, url_for
from werkzeug.datastructures import FileStorage

from services.analysis_service import AnalysisService
from services.agent_call_service import (
    AgentCallPersistenceUnavailableError,
    AgentCallValidationError,
    AgentReportNotReadyError,
    create_agent_call,
    fail_agent_call,
    get_agent_call,
    list_agent_calls,
)
from services.agent_execution_service import AgentExecutionUnavailableError
from services.editor_input_validation import (
    EditorSegmentValidationError,
    adapt_legacy_segments,
    validate_editor_segments,
)
from services.ffmpeg_service import (
    create_multi_segment_rough_cut,
    create_rough_cut,
    is_ffmpeg_available,
)
from services.file_service import FileService, FileValidationError
from services.job_access_service import (
    get_visible_job_ids,
    require_job_access,
)
from services.job_index_service import create_asset_and_job_index
from services.job_service import JobService, JobStateConflictError
from services.project_service import (
    ProjectOwnerForbiddenError,
    ProjectValidationError,
    create_project,
    get_owned_project,
    list_projects_for_owner,
)
from services.review_service import (
    ReviewPersistenceUnavailableError,
    ReviewValidationError,
    create_review,
    get_latest_review,
    list_review_history,
    normalize_review_labels,
    normalize_review_note,
    validate_review_status,
)
from services.session_service import require_authenticated_user_id


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


def _agent_comments(job_dir: Path) -> tuple[dict[str, dict[str, Any]], str]:
    """Read validated, final Agent comments without deriving prose from scores."""
    candidates = (
        job_dir / "agent_report.json",
        job_dir / "result" / "agent_report.json",
    )
    source = next((path for path in candidates if path.is_file()), None)
    if source is None:
        return {}, "pending"
    try:
        with source.open("r", encoding="utf-8") as handle:
            report = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}, "unavailable"
    if not isinstance(report, dict):
        return {}, "unavailable"
    if report.get("status") == "failed":
        return {}, "unavailable"

    comments: dict[str, dict[str, Any]] = {}
    direct = report.get("segment_comments", [])
    if isinstance(direct, list):
        for item in direct:
            if not isinstance(item, dict):
                continue
            segment_id = str(item.get("segment_id", "")).strip()
            comment = str(item.get("comment", "")).strip()
            if not segment_id or not comment:
                continue
            refs = item.get("evidence_refs", [])
            review_status = item.get("review_status")
            if review_status not in {"pass", "needs_review", "reject"}:
                review_status = None
            comments[segment_id] = {
                "comment": comment[:1000],
                "review_status": review_status,
                "evidence_refs": [
                    str(ref)
                    for ref in refs
                    if isinstance(ref, str) and ref.strip()
                ][:20],
            }

    suggestions = report.get("suggestions", [])
    if isinstance(suggestions, list):
        for item in suggestions:
            if not isinstance(item, dict):
                continue
            action = str(item.get("action", "")).strip()
            refs = item.get("evidence_refs", [])
            if not action or not isinstance(refs, list):
                continue
            normalized_refs = [
                str(ref)
                for ref in refs
                if isinstance(ref, str) and ref.strip()
            ]
            for reference in normalized_refs:
                prefix = "ev:segment:"
                if not reference.startswith(prefix):
                    continue
                segment_id = reference.removeprefix(prefix)
                comments.setdefault(
                    segment_id,
                    {
                        "comment": action[:1000],
                        "review_status": None,
                        "evidence_refs": normalized_refs[:20],
                    },
                )
    return comments, "pending"


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


def _json_object(*, optional: bool = False) -> dict[str, Any]:
    if optional and not request.data:
        return {}
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise FileValidationError("请求体必须是合法的 JSON 对象")
    return payload


def _positive_project_id(raw_value: object) -> int:
    if isinstance(raw_value, bool) or not isinstance(raw_value, str):
        raise ProjectValidationError("project_id 必须是正整数")
    value = raw_value.strip()
    if not value.isascii() or not value.isdecimal():
        raise ProjectValidationError("project_id 必须是正整数")
    project_id = int(value)
    if project_id <= 0:
        raise ProjectValidationError("project_id 必须是正整数")
    return project_id


def _positive_agent_call_id(raw_value: object) -> int:
    if isinstance(raw_value, bool) or not isinstance(raw_value, str):
        raise AgentCallValidationError("agent_call_id 必须是正整数")
    value = raw_value.strip()
    if not value.isascii() or not value.isdecimal() or int(value) <= 0:
        raise AgentCallValidationError("agent_call_id 必须是正整数")
    return int(value)


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


@api_bp.post("/projects")
def create_project_route():
    owner_id = require_authenticated_user_id()
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ProjectValidationError("请求体必须是合法的 JSON 对象")
    if "owner_id" in payload:
        raise ProjectOwnerForbiddenError("owner_id 只能来自当前登录 Session")
    if "status" in payload:
        raise ProjectValidationError("status 由服务端管理")
    project = create_project(
        owner_id,
        payload.get("name"),
        payload.get("description"),
        payload.get("game_type"),
    )
    return jsonify(ok=True, project=project), 201


@api_bp.get("/projects")
def list_projects_route():
    owner_id = require_authenticated_user_id()
    return jsonify(
        ok=True,
        projects=list_projects_for_owner(owner_id),
    )


@api_bp.post("/jobs")
def create_job():
    jobs, files, _ = _services()
    owner_id = require_authenticated_user_id()
    project: dict[str, Any] | None = None
    requested_name: str | None = None
    if "project_id" in request.form:
        project_id = _positive_project_id(request.form.get("project_id"))
        project = get_owned_project(project_id, owner_id)
    else:
        requested_name = request.form.get(
            "project_name", current_app.config["DEFAULT_PROJECT_NAME"]
        ).strip()
        if not requested_name:
            requested_name = current_app.config["DEFAULT_PROJECT_NAME"]
        if len(requested_name) > 100:
            raise FileValidationError("project_name 长度不能超过 100")

    upload = request.files.get("file")
    if not isinstance(upload, FileStorage):
        raise FileValidationError("缺少必填的 file 字段")

    original_name, _ = files.validate_filename(upload)
    settings = _parse_job_settings(request.form.to_dict(flat=True))
    game_type = str(request.form.get("game_type", "other")).strip().lower()
    if game_type not in {"csgo", "valorant", "other"}:
        raise FileValidationError("game_type 仅支持 csgo、valorant 或 other")
    project_name = project["name"] if project is not None else requested_name

    job_id, job_dir = jobs.reserve_workspace()
    try:
        saved_path = files.save_upload(upload, job_dir / "input")
        if project is None:
            project = create_project(owner_id, requested_name)
        job = jobs.create_job_record(
            job_id,
            project_name,
            saved_path.name,
            settings,
        )
        if original_name != saved_path.name:
            job = jobs.update_job(job_id, original_asset_name=original_name)
        job = jobs.update_job(job_id, game_type=game_type)
        job = jobs.update_job(job_id, project_id=project["id"])
        relative_base = Path(current_app.config["OUTPUTS_DIR"]).resolve().parent
        stored_path = saved_path.resolve().relative_to(relative_base).as_posix()
        job_json_path = (
            (job_dir / "job.json")
            .resolve()
            .relative_to(relative_base)
            .as_posix()
        )
        create_asset_and_job_index(
            project_id=int(project["id"]),
            created_by=owner_id,
            public_job_id=job_id,
            original_name=original_name,
            stored_path=stored_path,
            mime_type=upload.mimetype or None,
            size_bytes=saved_path.stat().st_size,
            job_json_path=job_json_path,
            status=str(job["status"]),
        )
    except Exception:
        jobs.discard_workspace(job_id)
        raise
    return jsonify(ok=True, job_id=job_id, status=job["status"]), 201


@api_bp.get("/jobs")
def list_jobs():
    jobs, _, _ = _services()
    visible_ids = get_visible_job_ids()
    visible_jobs = [
        job
        for job in jobs.list_jobs()
        if job.get("job_id") in visible_ids
    ]
    return jsonify(ok=True, jobs=visible_jobs)


@api_bp.get("/jobs/<job_id>")
def get_job(job_id: str):
    jobs, _, _ = _services()
    require_job_access(job_id)
    return jsonify(ok=True, job=jobs.get_job_detail(job_id))


@api_bp.delete("/jobs/<job_id>")
def delete_job(job_id: str):
    jobs, _, _ = _services()
    require_job_access(job_id)
    jobs.delete_job(job_id)
    return jsonify(ok=True, deleted_job_id=job_id)


@api_bp.post("/jobs/<job_id>/analyze")
def analyze_job(job_id: str):
    jobs, _, analysis = _services()
    require_job_access(job_id)
    jobs.get_job(job_id)
    analysis.enqueue(job_id)
    return jsonify(ok=True, job_id=job_id, status="queued"), 202


@api_bp.patch("/jobs/<job_id>/review")
def review_job(job_id: str):
    jobs, _, _ = _services()
    access = require_job_access(job_id)
    job = jobs.get_job(job_id)
    if not jobs.report_path(job_id).is_file():
        raise JobStateConflictError("分析报告尚未生成，不能进行人工审核")
    report = jobs.read_report(job_id)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ReviewValidationError("请求体必须是合法的 JSON 对象")
    unexpected = set(payload) - {
        "keyframes",
        "recommended_clip",
        "segments",
        "status",
        "labels",
        "note",
    }
    if unexpected:
        raise ReviewValidationError(
            f"不支持的审核字段：{', '.join(sorted(unexpected))}"
        )
    if not payload:
        raise ReviewValidationError(
            "至少提交审核状态或报告审核字段"
        )
    status = (
        validate_review_status(payload["status"])
        if "status" in payload
        else None
    )
    labels = (
        normalize_review_labels(payload["labels"])
        if "labels" in payload
        else None
    )
    note = (
        normalize_review_note(payload["note"])
        if "note" in payload
        else None
    )
    if status is None and ("labels" in payload or "note" in payload):
        raise ReviewValidationError("labels 和 note 必须与 status 一同提交")
    duration = _duration(job, report)
    changes: dict[str, Any] = {}
    if "keyframes" in payload:
        changes["keyframes"] = _validate_keyframes(payload["keyframes"], duration)
    if "recommended_clip" in payload:
        changes["recommended_clip"] = _validate_clip(
            payload["recommended_clip"], duration
        )
    if "segments" in payload:
        try:
            segments = (
                adapt_legacy_segments(payload["segments"], duration)
                if access["is_legacy"]
                else validate_editor_segments(payload["segments"], duration)
            )
        except EditorSegmentValidationError as exc:
            raise ReviewValidationError(str(exc)) from exc
        changes["segments"] = segments
        if segments:
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

    apply_report_update = lambda: jobs.update_report(
        job_id,
        lambda current: {**current, **changes},
    )
    if status is None:
        updated = apply_report_update()
    else:
        if access["is_legacy"]:
            raise ReviewPersistenceUnavailableError(
                "旧文件任务无法持久化 SQLite 审核记录"
            )
        if "segments" in payload:
            segments_snapshot = changes["segments"]
        else:
            try:
                segments_snapshot = validate_editor_segments(
                    report.get("segments", []),
                    duration,
                )
            except EditorSegmentValidationError as exc:
                raise ReviewValidationError(str(exc)) from exc
        _, updated = create_review(
            public_job_id=job_id,
            reviewer_id=int(access["user_id"]),
            status=status,
            labels=labels,
            note=note,
            segments=segments_snapshot,
            keyframes=(
                changes.get("keyframes")
                if "keyframes" in payload
                else None
            ),
            apply_report_update=apply_report_update,
            restore_report=lambda: jobs.write_report(job_id, report),
        )
    jobs.update_job(job_id)
    return jsonify(ok=True, report=updated)


@api_bp.get("/jobs/<job_id>/reviews")
def get_review_history(job_id: str):
    access = require_job_access(job_id)
    reviews = (
        []
        if access["is_legacy"]
        else list_review_history(job_id)
    )
    return jsonify(ok=True, reviews=reviews)


@api_bp.get("/jobs/<job_id>/review/latest")
def get_latest_job_review(job_id: str):
    access = require_job_access(job_id)
    review = (
        None
        if access["is_legacy"]
        else get_latest_review(job_id)
    )
    return jsonify(ok=True, review=review)


@api_bp.post("/jobs/<job_id>/agent-calls")
def create_job_agent_call(job_id: str):
    jobs, _, _ = _services()
    access = require_job_access(job_id)
    if access["is_legacy"]:
        raise AgentCallPersistenceUnavailableError(
            "旧文件任务无法持久化 Agent 调用日志"
        )

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise AgentCallValidationError("请求体必须是合法的 JSON 对象")
    unexpected = set(payload) - {"prompt_version", "force"}
    if unexpected:
        raise AgentCallValidationError(
            f"不支持的 Agent 调用字段：{', '.join(sorted(unexpected))}"
        )
    force = payload.get("force", False)
    if not isinstance(force, bool):
        raise AgentCallValidationError("force 必须是布尔值")

    job = jobs.get_job(job_id)
    if job.get("status") != "completed" or not jobs.report_path(job_id).is_file():
        raise AgentReportNotReadyError(
            "任务必须 completed 且分析报告已生成"
        )
    agent_call = create_agent_call(
        public_job_id=job_id,
        requested_by=int(access["user_id"]),
        prompt_version=payload.get("prompt_version"),
    )
    try:
        execution_service = current_app.extensions.get(
            "agent_execution_service"
        )
        if execution_service is None:
            raise AgentExecutionUnavailableError(
                "Agent 后台执行服务当前不可用"
            )
        execution_service.enqueue(
            int(agent_call["id"]),
            job_id,
            prompt_version=str(agent_call["prompt_version"]),
        )
    except Exception as exc:
        try:
            fail_agent_call(
                int(agent_call["id"]),
                error_code="AGENT_EXECUTION_UNAVAILABLE",
                error_message="Agent 后台执行服务当前不可用，请稍后重试",
                duration_ms=0,
                tool_trace=[],
            )
        except Exception:
            current_app.logger.exception(
                "无法把调度失败的 Agent 调用 %s 标记为 failed",
                agent_call["id"],
            )
        if isinstance(exc, AgentExecutionUnavailableError):
            raise
        current_app.logger.exception(
            "Agent 调用 %s 提交后台线程失败",
            agent_call["id"],
        )
        raise AgentExecutionUnavailableError(
            "Agent 后台执行服务当前不可用"
        ) from exc
    return jsonify(ok=True, agent_call=agent_call), 202


@api_bp.get("/jobs/<job_id>/agent-calls")
def get_job_agent_calls(job_id: str):
    access = require_job_access(job_id)
    agent_calls = (
        []
        if access["is_legacy"]
        else list_agent_calls(job_id)
    )
    return jsonify(ok=True, agent_calls=agent_calls)


@api_bp.get("/agent-calls/<agent_call_id>")
def get_agent_call_detail(agent_call_id: str):
    agent_call = get_agent_call(_positive_agent_call_id(agent_call_id))
    require_job_access(str(agent_call["job_id"]))
    return jsonify(ok=True, agent_call=agent_call)


@api_bp.post("/jobs/<job_id>/rough-cut")
def rough_cut(job_id: str):
    jobs, _, _ = _services()
    access = require_job_access(job_id)
    job = jobs.get_job(job_id)
    if job.get("status") != "completed":
        raise JobStateConflictError("只有 completed 任务可以生成粗剪视频")
    if not jobs.report_path(job_id).is_file():
        raise JobStateConflictError("分析报告尚未生成，不能生成粗剪视频")
    report = jobs.read_report(job_id)
    payload = _json_object(optional=True)
    unexpected = set(payload) - {"start_time", "end_time", "output_ratio"}
    if unexpected:
        raise FileValidationError(
            f"不支持的粗剪字段：{', '.join(sorted(unexpected))}"
        )
    recommended = report.get("recommended_clip")
    recommended = recommended if isinstance(recommended, dict) else {}
    job_settings = job.get("settings")
    job_settings = job_settings if isinstance(job_settings, dict) else {}
    ratio_value = payload.get(
        "output_ratio",
        recommended.get(
            "output_ratio",
            job_settings.get("output_ratio", "16:9"),
        ),
    )
    ratio = str(ratio_value).strip()
    if ratio not in current_app.config["ALLOWED_OUTPUT_RATIOS"]:
        raise FileValidationError("output_ratio 仅支持 16:9、9:16 或 1:1")
    duration = _duration(job, report)
    review_id: int | None = None
    clip: dict[str, Any] | None = None
    if access["is_legacy"]:
        raw_segments = report.get("segments", [])
        if raw_segments:
            try:
                segments = adapt_legacy_segments(raw_segments, duration)
            except EditorSegmentValidationError as exc:
                raise FileValidationError(str(exc)) from exc
        else:
            clip_source = dict(recommended)
            for field in ("start_time", "end_time"):
                if field in payload:
                    clip_source[field] = payload[field]
            clip_source["output_ratio"] = ratio
            clip = _validate_clip(clip_source, duration)
            segments = []
    else:
        latest_review = get_latest_review(job_id)
        if latest_review is None:
            raise JobStateConflictError("尚无审核记录，不能生成粗剪视频")
        if latest_review["status"] != "approved":
            raise JobStateConflictError("最新审核必须为 approved 才能生成粗剪视频")
        try:
            segments = validate_editor_segments(
                latest_review["segments"],
                duration,
            )
        except EditorSegmentValidationError as exc:
            raise FileValidationError(f"审核片段快照无效：{exc}") from exc
        if not segments:
            raise JobStateConflictError("最新审核没有可导出的片段")
        review_id = int(latest_review["id"])
    if not is_ffmpeg_available():
        return jsonify(ok=False, error="FFmpeg 不可用，无法生成粗剪视频"), 501

    job_dir = jobs.job_dir(job_id)
    ratio_label = ratio.replace(":", "x")
    output_path = job_dir / "result" / f"rough_cut_{ratio_label}.mp4"
    staging_path = output_path.with_name(
        f".{output_path.stem}.{uuid4().hex}.staged{output_path.suffix}"
    )
    try:
        if segments:
            result_path = create_multi_segment_rough_cut(
                jobs.get_input_video(job_id),
                staging_path,
                segments,
                ratio,
            )
            segment_ids = [str(segment["id"]) for segment in segments]
            segment_count = len(segments)
        else:
            if clip is None:
                raise RuntimeError("缺少 legacy 单片段粗剪参数")
            result_path = create_rough_cut(
                jobs.get_input_video(job_id),
                staging_path,
                clip["start_time"],
                clip["end_time"],
                ratio,
            )
            segment_ids = ["recommended_clip"]
            segment_count = 1
        result_path = Path(result_path).resolve()
        result_dir = (job_dir / "result").resolve()
        if (
            result_path != staging_path.resolve()
            or result_path.parent != result_dir
            or not result_path.is_file()
        ):
            raise RuntimeError("粗剪服务未生成有效输出文件")
    except NotImplementedError as exc:
        staging_path.unlink(missing_ok=True)
        return jsonify(ok=False, error=str(exc)), 501
    except Exception:
        staging_path.unlink(missing_ok=True)
        raise
    relative = output_path.relative_to(job_dir).as_posix()

    def update_output(current: dict[str, Any]) -> dict[str, Any]:
        output = current.get("output")
        if not isinstance(output, dict):
            output = {}
        output = {
            **output,
            "video": relative,
            "ratio": ratio,
            "segment_count": segment_count,
            "segment_ids": segment_ids,
            "review_id": review_id,
        }
        updated = {**current, "output": output}
        if clip is not None:
            updated["recommended_clip"] = clip
        return updated

    report_updated = False
    job_updated = False
    previous_rough_cut = job.get("rough_cut_file")
    try:
        jobs.update_report(job_id, update_output)
        report_updated = True
        jobs.update_job(job_id, rough_cut_file=relative)
        job_updated = True
        os.replace(result_path, output_path)
    except Exception:
        if job_updated:
            jobs.update_job(job_id, rough_cut_file=previous_rough_cut)
        if report_updated:
            jobs.write_report(job_id, report)
        raise
    finally:
        staging_path.unlink(missing_ok=True)

    return jsonify(
        ok=True,
        job_id=job_id,
        rough_cut_file=relative,
        segment_count=segment_count,
        segment_ids=segment_ids,
        review_id=review_id,
    )


@api_bp.get("/jobs/<job_id>/report")
def get_report(job_id: str):
    jobs, _, _ = _services()
    require_job_access(job_id)
    return jsonify(ok=True, report=jobs.read_report(job_id))


@api_bp.get("/jobs/<job_id>/editor")
def get_editor_contract(job_id: str):
    jobs, _, _ = _services()
    access = require_job_access(job_id)
    job = jobs.get_job_detail(job_id)
    if job.get("status") != "completed" or not job.get("report_available"):
        raise JobStateConflictError("分析报告尚未生成，不能打开剪辑预览")

    report = jobs.read_report(job_id)
    duration = _duration(job, report)
    if duration is None:
        raise FileValidationError("分析报告缺少有效的视频时长")
    source_video = jobs.get_input_video(job_id)
    job_dir = jobs.job_dir(job_id)
    source_relative = source_video.relative_to(job_dir).as_posix()
    comments, missing_comment_status = _agent_comments(job_dir)

    raw_segments = report.get("segments", [])
    try:
        segments = (
            adapt_legacy_segments(raw_segments, duration)
            if access["is_legacy"]
            else validate_editor_segments(raw_segments, duration)
        )
    except EditorSegmentValidationError as exc:
        raise FileValidationError(f"分析报告中的 {exc}") from exc
    highlights = []
    for segment in segments:
        score = segment["score"]
        segment_id = str(segment["id"])
        agent = comments.get(segment_id)
        highlights.append(
            {
                "id": segment_id,
                "order": int(segment["order"]),
                "start": float(segment["start"]),
                "end": float(segment["end"]),
                "duration": round(
                    float(segment["end"]) - float(segment["start"]),
                    6,
                ),
                "score": score,
                "source_keyframes": [
                    str(frame_id)
                    for frame_id in segment.get("source_keyframes", [])
                    if isinstance(frame_id, str)
                ],
                "agent_comment": agent["comment"] if agent else None,
                "agent_comment_status": (
                    "ready" if agent else missing_comment_status
                ),
                "agent_review_status": (
                    agent["review_status"] if agent else None
                ),
                "agent_evidence_refs": (
                    agent["evidence_refs"] if agent else []
                ),
            }
        )

    output = report.get("output")
    output = output if isinstance(output, dict) else {}
    recommended = report.get("recommended_clip")
    recommended = recommended if isinstance(recommended, dict) else {}

    def output_url(relative: Any) -> str | None:
        if not isinstance(relative, str) or not relative.strip():
            return None
        return url_for(
            "serve_job_output",
            job_id=job_id,
            filename=relative,
        )

    return jsonify(
        ok=True,
        contract_version="1.0",
        job={
            "job_id": job_id,
            "project_name": str(job.get("project_name", "")),
            "status": str(job.get("status", "")),
            "created_at": job.get("created_at"),
            "completed_at": job.get("completed_at"),
        },
        video={
            "url": url_for(
                "serve_job_output",
                job_id=job_id,
                filename=source_relative,
            ),
            "filename": str(
                job.get("original_asset_name") or source_video.name
            ),
            "duration": duration,
        },
        highlights=highlights,
        output={
            "rough_cut_url": output_url(output.get("video")),
            "contact_sheet_url": output_url(output.get("contact_sheet")),
            "ratio": output.get("ratio") or recommended.get("output_ratio"),
        },
    )
