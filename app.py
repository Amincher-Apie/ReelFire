"""Application factory and command-line entry point for Day08."""

from __future__ import annotations

import argparse
import atexit
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template
from werkzeug.exceptions import MethodNotAllowed, NotFound, RequestEntityTooLarge

from config import Config
from routes.api_routes import api_bp
from services.analysis_service import AnalysisService
from services.file_service import FileService, FileValidationError
from services.job_service import (
    CorruptDataError,
    InvalidJobIdError,
    JobNotFoundError,
    JobService,
    JobStateConflictError,
)


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    app.json.ensure_ascii = False
    app.json.sort_keys = False

    outputs_dir = Path(app.config["OUTPUTS_DIR"])
    models_dir = Path(app.config["MODELS_DIR"])
    outputs_dir.mkdir(parents=True, exist_ok=True)
    models_dir.mkdir(parents=True, exist_ok=True)

    jobs = JobService(outputs_dir)
    files = FileService(app.config["ALLOWED_VIDEO_EXTENSIONS"])
    analysis = AnalysisService(jobs, app.config["BACKGROUND_WORKERS"])
    app.extensions["job_service"] = jobs
    app.extensions["file_service"] = files
    app.extensions["analysis_service"] = analysis
    jobs.recover_interrupted_jobs()
    if not app.testing:
        atexit.register(analysis.shutdown, False)

    app.register_blueprint(api_bp)

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.errorhandler(FileValidationError)
    @app.errorhandler(InvalidJobIdError)
    def handle_bad_request(exc: Exception):
        return jsonify(ok=False, error=str(exc)), 400

    @app.errorhandler(JobNotFoundError)
    def handle_not_found(exc: JobNotFoundError):
        return jsonify(ok=False, error=str(exc)), 404

    @app.errorhandler(JobStateConflictError)
    def handle_conflict(exc: JobStateConflictError):
        return jsonify(ok=False, error=str(exc)), 409

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
