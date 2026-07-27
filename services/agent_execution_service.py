"""Execute Agent calls without exposing partial results to the Editor."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Any, Callable

from agent.integrations import to_backend_agent_call
from agent.providers import DifyChatClient, OllamaChatClient
from agent.service import AgentService
from agent.tools import (
    AdviceGeneratorTool,
    KnowledgeRetrieverTool,
    build_embedder_from_env,
)
from services.agent_call_service import (
    complete_agent_call,
    fail_agent_call,
    mark_agent_call_running,
)
from services.job_service import CorruptDataError, JobService

if TYPE_CHECKING:
    from flask import Flask


LOGGER = logging.getLogger(__name__)
FINAL_FILENAMES = ("agent_report.json", "agent_trace.json")


class AgentExecutionUnavailableError(RuntimeError):
    """Raised when the managed executor cannot accept a new call."""


class AgentOutputValidationError(RuntimeError):
    """Raised when a staged Agent result is unsafe or incomplete."""


class AgentFileRecoveryError(RuntimeError):
    """Raised when old formal files could not be fully restored."""


class AgentExecutionService:
    """Run queued calls and publish each validated result as one file pair."""

    def __init__(
        self,
        app: Flask,
        jobs: JobService,
        *,
        max_workers: int = 1,
        provider: str = "rule_only",
        workflow_factory: Callable[
            [], tuple[AgentService, dict[str, str]]
        ]
        | None = None,
        executor_factory: Callable[..., Any] = ThreadPoolExecutor,
    ) -> None:
        if provider not in {"dify", "ollama", "rule_only"}:
            raise ValueError(
                "AGENT_PROVIDER 仅支持 dify、ollama 或 rule_only"
            )
        if isinstance(max_workers, bool) or int(max_workers) < 1:
            raise ValueError("AGENT_BACKGROUND_WORKERS 必须是正整数")
        self.app = app
        self.jobs = jobs
        self.provider = provider
        self._workflow_factory = workflow_factory
        self._executor = executor_factory(
            max_workers=int(max_workers),
            thread_name_prefix="reelfire-agent",
        )
        self._active: set[int] = set()
        self._active_lock = threading.Lock()
        self._shutdown = False

    def enqueue(
        self,
        agent_call_id: int,
        job_id: str,
        *,
        prompt_version: str,
    ):
        """Submit exactly once, without changing database state on rejection."""
        with self._active_lock:
            if self._shutdown:
                raise AgentExecutionUnavailableError(
                    "Agent 后台执行服务已关闭"
                )
            if agent_call_id in self._active:
                raise AgentExecutionUnavailableError(
                    "Agent 调用已在执行"
                )
            self._active.add(agent_call_id)
        try:
            future = self._executor.submit(
                self._run,
                agent_call_id,
                job_id,
                prompt_version,
            )
        except Exception as exc:
            with self._active_lock:
                self._active.discard(agent_call_id)
            raise AgentExecutionUnavailableError(
                "Agent 后台执行服务当前不可用"
            ) from exc
        return future

    def _run(
        self,
        agent_call_id: int,
        job_id: str,
        prompt_version: str,
    ) -> None:
        started = perf_counter()
        staging_dir: Path | None = None
        try:
            with self.app.app_context():
                mark_agent_call_running(
                    agent_call_id,
                    model_name=self._configured_model_name(),
                    input_summary="读取真实 CV analysis_report.json",
                )
                report = self.jobs.read_report(job_id)
                service, provider_config = self._build_service()
                staging_dir = self._create_staging_dir(
                    job_id,
                    agent_call_id,
                )
                result = service.run_analysis_report(
                    report,
                    provider=provider_config,
                    output_dir=staging_dir,
                )
                backend = to_backend_agent_call(
                    result,
                    prompt_version=prompt_version,
                    result_path="agent_report.json",
                )
                if backend.get("job_id") != job_id:
                    raise AgentOutputValidationError(
                        "Agent 输出 job_id 与当前任务不一致"
                    )
                if backend["status"] == "failed":
                    fail_agent_call(
                        agent_call_id,
                        error_code=backend.get("error_code")
                        or "AGENT_EXECUTION_FAILED",
                        error_message=self._safe_error_message(
                            backend.get("error_message"),
                            "Agent 未生成安全结果",
                        ),
                        duration_ms=backend["duration_ms"],
                        tool_trace=backend["tool_trace"],
                    )
                    return

                self._validate_staged_files(staging_dir, job_id)
                self._publish_and_complete(
                    staging_dir,
                    job_id,
                    agent_call_id,
                    backend,
                )
        except Exception as exc:
            LOGGER.exception("Agent 调用 %s 执行失败", agent_call_id)
            with self.app.app_context():
                try:
                    error_code, error_message = self._failure_details(exc)
                    fail_agent_call(
                        agent_call_id,
                        error_code=error_code,
                        error_message=error_message,
                        duration_ms=max(
                            0,
                            int((perf_counter() - started) * 1000),
                        ),
                    )
                except Exception:
                    LOGGER.exception(
                        "无法写回 Agent 调用 %s 的失败状态",
                        agent_call_id,
                    )
        finally:
            if staging_dir is not None:
                self._cleanup_staging(staging_dir)
            with self._active_lock:
                self._active.discard(agent_call_id)

    def _configured_model_name(self) -> str:
        if self.provider == "dify":
            return os.getenv(
                "DIFY_MODEL_LABEL",
                "reelfire-chatflow-v1.0.0",
            )
        if self.provider == "ollama":
            return os.getenv("OLLAMA_MODEL") or "ollama-unconfigured"
        return "deterministic-v1"

    def _build_service(self) -> tuple[AgentService, dict[str, str]]:
        if self._workflow_factory is not None:
            return self._workflow_factory()

        client: DifyChatClient | OllamaChatClient | None = None
        if self.provider == "dify":
            client = DifyChatClient()
        elif self.provider == "ollama":
            client = OllamaChatClient()
        embedder = (
            build_embedder_from_env()
            if self.provider != "rule_only"
            else None
        )
        model = client.model if client is not None else "deterministic-v1"
        service = AgentService(
            knowledge_retriever=KnowledgeRetrieverTool(embedder=embedder),
            advice_generator=AdviceGeneratorTool(model_client=client),
        )
        return service, {"type": self.provider, "model": model}

    def _create_staging_dir(
        self,
        job_id: str,
        agent_call_id: int,
    ) -> Path:
        runs_dir = self.jobs.job_dir(job_id) / ".agent_runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        staging_dir = runs_dir / f"{agent_call_id}-{uuid.uuid4().hex}"
        staging_dir.mkdir()
        return staging_dir

    @staticmethod
    def _read_json_object(path: Path) -> dict[str, Any]:
        if not path.is_file() or path.stat().st_size == 0:
            raise AgentOutputValidationError(
                f"{path.name} 缺失或为空"
            )
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise AgentOutputValidationError(
                f"{path.name} 不是合法 JSON"
            ) from exc
        if not isinstance(value, dict):
            raise AgentOutputValidationError(
                f"{path.name} 必须是 JSON 对象"
            )
        return value

    def _validate_staged_files(
        self,
        staging_dir: Path,
        job_id: str,
    ) -> None:
        job_dir = self.jobs.job_dir(job_id).resolve()
        resolved_staging = staging_dir.resolve()
        try:
            resolved_staging.relative_to(job_dir)
        except ValueError as exc:
            raise AgentOutputValidationError(
                "Agent staging 目录不安全"
            ) from exc
        if resolved_staging.parent.name != ".agent_runs":
            raise AgentOutputValidationError(
                "Agent staging 目录不在允许位置"
            )

        for filename in FINAL_FILENAMES:
            candidate = (resolved_staging / filename).resolve()
            if candidate.parent != resolved_staging:
                raise AgentOutputValidationError(
                    f"{filename} 路径不安全"
                )
            value = self._read_json_object(candidate)
            if value.get("job_id") != job_id:
                raise AgentOutputValidationError(
                    f"{filename} 的 job_id 与当前任务不一致"
                )

    def _publish_and_complete(
        self,
        staging_dir: Path,
        job_id: str,
        agent_call_id: int,
        backend: dict[str, Any],
    ) -> None:
        job_dir = self.jobs.job_dir(job_id)
        backups: dict[str, Path] = {}
        published: set[str] = set()
        try:
            for filename in FINAL_FILENAMES:
                final_path = job_dir / filename
                if final_path.exists():
                    backup_path = staging_dir / f".previous-{filename}"
                    os.replace(final_path, backup_path)
                    backups[filename] = backup_path
            for filename in FINAL_FILENAMES:
                os.replace(
                    staging_dir / filename,
                    job_dir / filename,
                )
                published.add(filename)

            complete_agent_call(
                agent_call_id,
                status=backend["status"],
                model_name=backend["model_name"],
                output_summary=backend["output_summary"],
                tool_trace=backend["tool_trace"],
                references=backend["references"],
                result=backend["result"],
                duration_ms=backend["duration_ms"],
            )
            for backup_path in backups.values():
                try:
                    backup_path.unlink(missing_ok=True)
                except OSError:
                    LOGGER.exception(
                        "清理已完成 Agent 调用的旧文件备份失败"
                    )
        except Exception as publish_error:
            try:
                self._restore_previous_files(
                    job_dir,
                    backups,
                    published,
                )
            except AgentFileRecoveryError as recovery_error:
                raise recovery_error from publish_error
            raise

    @staticmethod
    def _restore_previous_files(
        job_dir: Path,
        backups: dict[str, Path],
        published: set[str],
    ) -> None:
        failed_restores = []
        for filename in reversed(FINAL_FILENAMES):
            final_path = job_dir / filename
            try:
                if filename in published:
                    final_path.unlink(missing_ok=True)
                backup_path = backups.get(filename)
                if backup_path is not None and backup_path.exists():
                    os.replace(backup_path, final_path)
            except OSError:
                failed_restores.append(filename)
                LOGGER.exception(
                    "恢复旧 Agent 正式文件失败：%s",
                    filename,
                )
        if failed_restores:
            raise AgentFileRecoveryError(
                "Agent 正式文件恢复未完成，旧备份已保留供人工恢复"
            )

    @classmethod
    def _safe_error(cls, exc: Exception) -> str:
        return cls._safe_error_message(
            str(exc),
            "Agent 执行失败，请重新运行",
        )

    @staticmethod
    def _safe_error_message(value: object, fallback: str) -> str:
        if not isinstance(value, str) or not value.strip():
            return fallback
        message = " ".join(value.split())[:1000]
        sensitive = re.compile(
            r"(?:[A-Za-z]:[\\/]|/(?:[^/\s]+/)+|"
            r"authorization|bearer\s+|api[_-]?key|token|secret)",
            re.IGNORECASE,
        )
        return fallback if sensitive.search(message) else message

    @classmethod
    def _failure_details(cls, exc: Exception) -> tuple[str, str]:
        if isinstance(exc, CorruptDataError):
            return (
                "AGENT_REPORT_INVALID",
                "analysis_report.json 损坏，Agent 无法执行",
            )
        if isinstance(exc, AgentOutputValidationError):
            return (
                "AGENT_OUTPUT_INVALID",
                cls._safe_error(exc),
            )
        if isinstance(exc, AgentFileRecoveryError):
            return (
                "AGENT_FILE_RECOVERY_FAILED",
                "Agent 正式文件恢复未完成，旧备份已保留供人工恢复",
            )
        return (
            "AGENT_EXECUTION_FAILED",
            cls._safe_error(exc),
        )

    @staticmethod
    def _cleanup_staging(staging_dir: Path) -> bool:
        preserved_backups = any(
            (staging_dir / f".previous-{filename}").exists()
            for filename in FINAL_FILENAMES
        )
        if preserved_backups:
            LOGGER.error(
                "Agent staging 含未恢复的旧文件备份，已保留供人工恢复"
            )
            return False
        runs_dir = staging_dir.parent
        shutil.rmtree(staging_dir, ignore_errors=True)
        try:
            runs_dir.rmdir()
        except OSError:
            pass
        return True

    def shutdown(self, wait: bool = True) -> None:
        """Reject future calls and safely close the executor once."""
        with self._active_lock:
            if self._shutdown:
                return
            self._shutdown = True
        self._executor.shutdown(wait=wait, cancel_futures=False)
