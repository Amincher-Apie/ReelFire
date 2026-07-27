"""Application factory and command-line entry point for Day08."""

from __future__ import annotations

import argparse
import atexit
import secrets
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from flask import Flask, jsonify, redirect, render_template, request, send_file, url_for
from werkzeug.exceptions import MethodNotAllowed, NotFound, RequestEntityTooLarge

from config import Config
from database import init_app as init_database_app
from database import init_db
from routes.api_routes import api_bp
from routes.auth_routes import auth_bp
from services.agent_call_service import (
    AgentAlreadyRunningError,
    AgentCallNotFoundError,
    AgentCallPersistenceUnavailableError,
    AgentCallStateConflictError,
    AgentCallValidationError,
    AgentReportNotReadyError,
    recover_interrupted_agent_calls,
)
from services.agent_execution_service import AgentExecutionUnavailableError
from services.auth_service import import_legacy_users
from services.file_service import FileService, FileValidationError
from services.job_access_service import JobAccessDeniedError, require_job_access
from services.job_service import (
    CorruptDataError,
    InvalidJobIdError,
    JobCleanupPendingError,
    JobNotFoundError,
    JobPersistenceConsistencyError,
    JobService,
    JobStateConflictError,
)
from services.job_index_service import JobIndexRepository
from services.project_service import (
    ProjectAccessDeniedError,
    ProjectArchivedError,
    ProjectNotFoundError,
    ProjectNotEmptyError,
    ProjectOwnerForbiddenError,
    ProjectStateConflictError,
    ProjectValidationError,
)
from services.review_service import (
    ReviewPersistenceUnavailableError,
    ReviewValidationError,
)
from services.session_service import (
    AuthenticationRequiredError,
    require_authenticated_user_id,
)


def _create_analysis_service(
    jobs: JobService,
    max_workers: int,
    model_path: Path,
):
    from services.analysis_service import AnalysisService

    return AnalysisService(jobs, max_workers, model_path)


def _create_agent_execution_service(
    app: Flask,
    jobs: JobService,
    max_workers: int,
    provider: str,
):
    from services.agent_execution_service import AgentExecutionService

    return AgentExecutionService(
        app,
        jobs,
        max_workers=max_workers,
        provider=provider,
    )


def _safe_local_redirect(value: object, fallback: str) -> str:
    if not isinstance(value, str) or not value.startswith("/"):
        return fallback
    if value.startswith("//") or "\\" in value:
        return fallback
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc:
        return fallback
    return value


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    app.json.ensure_ascii = False
    app.json.sort_keys = False
    app.secret_key = app.config.get("SECRET_KEY") or secrets.token_hex(32)

    outputs_dir = Path(app.config["OUTPUTS_DIR"])
    models_dir = Path(app.config["MODELS_DIR"])
    outputs_dir.mkdir(parents=True, exist_ok=True)
    models_dir.mkdir(parents=True, exist_ok=True)

    init_database_app(app)
    with app.app_context():
        init_db()
        import_legacy_users(app.config["LEGACY_USERS_FILE"])

    index_repository = JobIndexRepository(
        Path(app.config["DATABASE"]),
        outputs_dir.resolve().parent,
    )
    jobs = JobService(outputs_dir, index_repository)
    jobs.cleanup_delete_tombstones()
    jobs.reconcile_job_indexes()
    jobs.recover_interrupted_jobs()
    with app.app_context():
        recover_interrupted_agent_calls()

    files = FileService(app.config["ALLOWED_VIDEO_EXTENSIONS"])
    analysis_factory = app.config.get(
        "ANALYSIS_SERVICE_FACTORY",
        _create_analysis_service,
    )
    analysis = analysis_factory(
        jobs,
        app.config["BACKGROUND_WORKERS"],
        Path(app.config["MODEL_PATH"]),
    )
    app.extensions["job_service"] = jobs
    app.extensions["job_index_repository"] = index_repository
    app.extensions["file_service"] = files
    app.extensions["analysis_service"] = analysis
    if not app.testing:
        atexit.register(analysis.shutdown, False)

    agent_execution_factory = app.config.get(
        "AGENT_EXECUTION_SERVICE_FACTORY",
        _create_agent_execution_service,
    )
    agent_execution = agent_execution_factory(
        app,
        jobs,
        app.config["AGENT_BACKGROUND_WORKERS"],
        app.config["AGENT_PROVIDER"],
    )
    app.extensions["agent_execution_service"] = agent_execution
    if hasattr(analysis, "set_segment_callback") and hasattr(
        agent_execution,
        "enqueue_segment",
    ):
        analysis.set_segment_callback(
            agent_execution.enqueue_segment,
            (
                agent_execution.finalize_segments
                if hasattr(agent_execution, "finalize_segments")
                else None
            ),
        )
    if not app.testing:
        atexit.register(agent_execution.shutdown, False)

    app.register_blueprint(api_bp)
    app.register_blueprint(auth_bp)

    public_endpoints = {
        "api.health",
        "auth.guest_login",
        "auth.login",
        "auth.register",
        "favicon",
        "login_page",
        "static",
    }

    @app.before_request
    def require_application_login():
        if request.endpoint in public_endpoints:
            return None
        try:
            require_authenticated_user_id()
        except AuthenticationRequiredError:
            if request.path.startswith("/api/"):
                raise
            next_url = request.full_path.rstrip("?")
            return redirect(url_for("login_page", next=next_url))
        return None

    @app.get("/")
    def index():
        return render_template(
            "index.html",
            initial_view="projects",
            job_id=None,
        )

    @app.get("/history")
    def history_page():
        return redirect(url_for("index"))

    @app.get("/jobs/<job_id>/analysis")
    def analysis_page(job_id: str):
        require_job_access(job_id)
        jobs.get_job(job_id)
        return render_template(
            "index.html",
            initial_view="analysis",
            job_id=job_id,
        )

    @app.get("/login")
    def login_page():
        try:
            require_authenticated_user_id()
        except AuthenticationRequiredError:
            return render_template("login.html")
        next_url = _safe_local_redirect(
            request.args.get("next"),
            url_for("index"),
        )
        return redirect(next_url)

        return render_template("login.html")

    @app.get("/jobs/<job_id>/editor")
    def editor_page(job_id: str):
        require_job_access(job_id)
        jobs.get_job(job_id)
        return render_template("editor.html", job_id=job_id)

    @app.get("/favicon.ico")
    def favicon():
        return send_file(Path(app.static_folder) / "favicon.svg", mimetype="image/svg+xml")

    @app.get("/outputs/<job_id>/<path:filename>")
    def serve_job_output(job_id: str, filename: str):
        require_job_access(job_id)
        root = jobs.job_dir(job_id).resolve()
        candidate = (root / filename).resolve()
        if root not in candidate.parents or not candidate.is_file():
            raise JobNotFoundError("任务输出文件不存在")
        return send_file(candidate)

    @app.errorhandler(FileValidationError)
    @app.errorhandler(InvalidJobIdError)
    def handle_bad_request(exc: Exception):
        return jsonify(ok=False, error=str(exc)), 400

    @app.errorhandler(AuthenticationRequiredError)
    def handle_authentication_required(exc: AuthenticationRequiredError):
        return jsonify(
            ok=False,
            error=str(exc),
            error_code="AUTH_REQUIRED",
        ), 401

    @app.errorhandler(ProjectOwnerForbiddenError)
    def handle_project_owner_forbidden(exc: ProjectOwnerForbiddenError):
        return jsonify(
            ok=False,
            error=str(exc),
            error_code="PROJECT_OWNER_FORBIDDEN",
        ), 400

    @app.errorhandler(ProjectValidationError)
    def handle_project_input_invalid(exc: ProjectValidationError):
        return jsonify(
            ok=False,
            error=str(exc),
            error_code="PROJECT_INPUT_INVALID",
        ), 400

    @app.errorhandler(ProjectNotFoundError)
    def handle_project_not_found(exc: ProjectNotFoundError):
        return jsonify(
            ok=False,
            error=str(exc),
            error_code="PROJECT_NOT_FOUND",
        ), 404

    @app.errorhandler(ProjectAccessDeniedError)
    def handle_project_access_denied(exc: ProjectAccessDeniedError):
        return jsonify(
            ok=False,
            error=str(exc),
            error_code="PROJECT_ACCESS_DENIED",
        ), 403

    @app.errorhandler(ProjectArchivedError)
    def handle_project_archived(exc: ProjectArchivedError):
        return jsonify(
            ok=False,
            error=str(exc),
            error_code="PROJECT_ARCHIVED",
        ), 409

    @app.errorhandler(ProjectNotEmptyError)
    def handle_project_not_empty(exc: ProjectNotEmptyError):
        return jsonify(
            ok=False,
            error=str(exc),
            error_code="PROJECT_NOT_EMPTY",
        ), 409

    @app.errorhandler(ProjectStateConflictError)
    def handle_project_state_conflict(exc: ProjectStateConflictError):
        return jsonify(
            ok=False,
            error=str(exc),
            error_code="PROJECT_STATE_CONFLICT",
        ), 409

    @app.errorhandler(JobAccessDeniedError)
    def handle_job_access_denied(exc: JobAccessDeniedError):
        return jsonify(
            ok=False,
            error=str(exc),
            error_code="JOB_ACCESS_DENIED",
        ), 403

    @app.errorhandler(ReviewValidationError)
    def handle_review_input_invalid(exc: ReviewValidationError):
        return jsonify(
            ok=False,
            error=str(exc),
            error_code="REVIEW_INPUT_INVALID",
        ), 400

    @app.errorhandler(ReviewPersistenceUnavailableError)
    def handle_review_persistence_unavailable(
        exc: ReviewPersistenceUnavailableError,
    ):
        return jsonify(
            ok=False,
            error=str(exc),
            error_code="REVIEW_PERSISTENCE_UNAVAILABLE",
        ), 409

    @app.errorhandler(AgentCallValidationError)
    def handle_agent_call_input_invalid(exc: AgentCallValidationError):
        return jsonify(
            ok=False,
            error=str(exc),
            error_code="AGENT_CALL_INPUT_INVALID",
        ), 400

    @app.errorhandler(AgentExecutionUnavailableError)
    def handle_agent_execution_unavailable(
        exc: AgentExecutionUnavailableError,
    ):
        return jsonify(
            ok=False,
            error=str(exc),
            error_code="AGENT_EXECUTION_UNAVAILABLE",
        ), 503

    @app.errorhandler(AgentCallPersistenceUnavailableError)
    def handle_agent_call_persistence_unavailable(
        exc: AgentCallPersistenceUnavailableError,
    ):
        return jsonify(
            ok=False,
            error=str(exc),
            error_code="AGENT_CALL_PERSISTENCE_UNAVAILABLE",
        ), 409

    @app.errorhandler(AgentAlreadyRunningError)
    def handle_agent_already_running(exc: AgentAlreadyRunningError):
        return jsonify(
            ok=False,
            error=str(exc),
            error_code="AGENT_ALREADY_RUNNING",
        ), 409

    @app.errorhandler(AgentReportNotReadyError)
    def handle_agent_report_not_ready(exc: AgentReportNotReadyError):
        return jsonify(
            ok=False,
            error=str(exc),
            error_code="REPORT_NOT_READY",
        ), 409

    @app.errorhandler(AgentCallStateConflictError)
    def handle_agent_call_state_conflict(
        exc: AgentCallStateConflictError,
    ):
        return jsonify(
            ok=False,
            error=str(exc),
            error_code="AGENT_CALL_STATE_CONFLICT",
        ), 409

    @app.errorhandler(AgentCallNotFoundError)
    def handle_agent_call_not_found(exc: AgentCallNotFoundError):
        return jsonify(
            ok=False,
            error=str(exc),
            error_code="AGENT_CALL_NOT_FOUND",
        ), 404

    @app.errorhandler(JobNotFoundError)
    def handle_not_found(exc: JobNotFoundError):
        return jsonify(ok=False, error=str(exc)), 404

    @app.errorhandler(JobStateConflictError)
    def handle_conflict(exc: JobStateConflictError):
        return jsonify(ok=False, error=str(exc)), 409

    @app.errorhandler(JobCleanupPendingError)
    def handle_job_cleanup_pending(exc: JobCleanupPendingError):
        return jsonify(
            ok=False,
            error=str(exc),
            error_code="JOB_CLEANUP_PENDING",
            cleanup_pending=True,
        ), 500

    @app.errorhandler(JobPersistenceConsistencyError)
    def handle_job_persistence_consistency(
        exc: JobPersistenceConsistencyError,
    ):
        return jsonify(
            ok=False,
            error=str(exc),
            error_code="JOB_PERSISTENCE_CONSISTENCY_ERROR",
        ), 500

    @app.errorhandler(CorruptDataError)
    def handle_corrupt_data(exc: CorruptDataError):
        return jsonify(ok=False, error=str(exc)), 500

    @app.errorhandler(RequestEntityTooLarge)
    def handle_too_large(_exc: RequestEntityTooLarge):
        return jsonify(ok=False, error="上传文件超过服务器大小限制"), 413

    @app.errorhandler(NotFound)
    def handle_route_not_found(_exc: NotFound):
        return jsonify(ok=False, error="请求的接口不存在"), 404

    @app.errorhandler(MethodNotAllowed)
    def handle_method_not_allowed(_exc: MethodNotAllowed):
        return jsonify(ok=False, error="当前接口不支持该 HTTP 方法"), 405

    @app.errorhandler(Exception)
    def handle_unexpected(exc: Exception):
        app.logger.exception("Unhandled request error", exc_info=exc)
        return jsonify(ok=False, error="服务内部错误，请查看服务日志"), 500

    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Day08 智能视频精彩片段提取后端")
    parser.add_argument("--host", default=Config.HOST, help="监听地址")
    parser.add_argument("--port", default=Config.PORT, type=int, help="监听端口")
    parser.add_argument("--debug", action="store_true", help="启用 Flask 调试模式")
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    create_app().run(
        host=arguments.host,
        port=arguments.port,
        debug=arguments.debug,
    )
