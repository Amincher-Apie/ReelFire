"""Execute Agent calls without exposing partial results to the Editor."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
import uuid
from copy import deepcopy
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
        self._active_segments: set[tuple[str, str]] = set()
        self._active_lock = threading.Lock()
        self._segment_report_lock = threading.Lock()
        self._final_segment_maps: dict[str, dict[str, str]] = {}
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

    def enqueue_segment(
        self,
        job_id: str,
        analysis_report: dict[str, Any],
    ):
        """Queue one provisional segment without blocking the YOLO producer."""

        raw_segments = analysis_report.get("segments")
        if not isinstance(raw_segments, list) or len(raw_segments) != 1:
            raise AgentExecutionUnavailableError(
                "Segment Agent input must contain exactly one segment"
            )
        segment_id = str(raw_segments[0].get("id", "")).strip()
        if not segment_id:
            raise AgentExecutionUnavailableError(
                "Segment Agent input is missing segment id"
            )
        key = (job_id, segment_id)
        with self._active_lock:
            if self._shutdown:
                raise AgentExecutionUnavailableError(
                    "Agent background service is closed"
                )
            if key in self._active_segments:
                return None
            self._active_segments.add(key)
        try:
            return self._executor.submit(
                self._run_segment,
                job_id,
                segment_id,
                analysis_report,
            )
        except Exception as exc:
            with self._active_lock:
                self._active_segments.discard(key)
            raise AgentExecutionUnavailableError(
                "Segment Agent queue is unavailable"
            ) from exc

    def _run_segment(
        self,
        job_id: str,
        segment_id: str,
        analysis_report: dict[str, Any],
    ) -> None:
        key = (job_id, segment_id)
        try:
            with self.app.app_context():
                service, provider_config = self._build_service()
                result = service.run_analysis_report(
                    analysis_report,
                    provider=provider_config,
                )
                if result.get("status") == "failed":
                    LOGGER.warning(
                        "Segment Agent failed job=%s segment=%s",
                        job_id,
                        segment_id,
                    )
                    return
                comments = result.get("segment_comments")
                if (
                    not isinstance(comments, list)
                    or len(comments) != 1
                    or comments[0].get("segment_id") != segment_id
                ):
                    raise AgentOutputValidationError(
                        "Segment Agent output did not match its segment"
                    )
                self._merge_segment_result(job_id, result)
        except Exception:
            LOGGER.exception(
                "Segment Agent execution failed job=%s segment=%s",
                job_id,
                segment_id,
            )
        finally:
            with self._active_lock:
                self._active_segments.discard(key)

    def _merge_segment_result(
        self,
        job_id: str,
        result: dict[str, Any],
        *,
        replace_non_streaming: bool = False,
    ) -> None:
        with self._segment_report_lock:
            path = self.jobs.agent_report_path(job_id)
            existing: dict[str, Any] = {}
            if path.is_file():
                try:
                    candidate = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError):
                    candidate = {}
                if isinstance(candidate, dict):
                    existing = candidate
            if existing and existing.get("streaming") is not True:
                if not replace_non_streaming:
                    return
                existing = {}

            comments_by_id = {
                str(item.get("segment_id")): item
                for item in existing.get("segment_comments", [])
                if isinstance(item, dict) and item.get("segment_id")
            }
            for item in result.get("segment_comments", []):
                if isinstance(item, dict) and item.get("segment_id"):
                    provisional_id = str(item["segment_id"])
                    target_id = self._final_segment_maps.get(
                        job_id,
                        {},
                    ).get(provisional_id, provisional_id)
                    comments_by_id[target_id] = {
                        **item,
                        "segment_id": target_id,
                    }
            comments = list(comments_by_id.values())
            degraded = (
                result.get("status") == "degraded"
                or existing.get("status") == "degraded"
            )
            merged = {
                "schema_version": "1.0",
                "job_id": job_id,
                "status": "degraded" if degraded else "completed",
                "streaming": True,
                "completed_segment_count": len(comments),
                "provider": result.get("provider", {}),
                "summary": f"已完成 {len(comments)} 个候选片段的 Agent 分析。",
                "tags": result.get("tags", []),
                "suggestions": result.get("suggestions", []),
                "segment_comments": comments,
                "review": result.get("review"),
                "evidence_refs": result.get("evidence_refs", []),
                "knowledge_refs": result.get("knowledge_refs", []),
                "trace": result.get("trace", {}),
                "errors": result.get("errors", []),
            }
            self.jobs.write_agent_report(job_id, merged)

    @staticmethod
    def _single_segment_report(
        report: dict[str, Any],
        segment: dict[str, Any],
    ) -> dict[str, Any]:
        """Limit a retry request to one segment and its local frame evidence."""

        start = float(segment.get("start", 0.0))
        end = float(segment.get("end", start))
        partial = deepcopy(report)
        partial["segments"] = [deepcopy(segment)]
        for field in ("samples", "keyframes"):
            values = report.get(field)
            if not isinstance(values, list):
                continue
            partial[field] = [
                deepcopy(item)
                for item in values
                if isinstance(item, dict)
                and start <= float(item.get("timestamp", -1.0)) <= end
            ]
        if isinstance(partial.get("samples"), list):
            partial["total_sampled_frames"] = len(partial["samples"])
        return partial

    def _run_segmented_report(
        self,
        service: AgentService,
        provider_config: dict[str, str],
        report: dict[str, Any],
        staging_dir: Path,
    ) -> dict[str, Any]:
        """Run a completed report as independent, incrementally published calls."""

        job_id = str(report.get("job_id", "")).strip()
        segments = report.get("segments")
        if not isinstance(segments, list) or len(segments) <= 1:
            return service.run_analysis_report(
                report,
                provider=provider_config,
                output_dir=staging_dir,
            )

        existing: dict[str, Any] = {}
        existing_path = self.jobs.agent_report_path(job_id)
        if existing_path.is_file():
            try:
                candidate = json.loads(existing_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                candidate = {}
            if isinstance(candidate, dict) and candidate.get("streaming") is True:
                existing = candidate
        completed_ids = {
            str(item.get("segment_id"))
            for item in existing.get("segment_comments", [])
            if isinstance(item, dict) and item.get("segment_id")
        }
        pending_segments = [
            segment
            for segment in segments
            if isinstance(segment, dict)
            and str(segment.get("id", "")).strip() not in completed_ids
        ]

        last_result: dict[str, Any] | None = None
        replace_non_streaming = not bool(existing)
        for segment in pending_segments:
            segment_id = str(segment.get("id", "")).strip()
            if not segment_id:
                raise AgentOutputValidationError(
                    "Agent 分片输入缺少 segment id"
                )
            partial = self._single_segment_report(report, segment)
            result = service.run_analysis_report(
                partial,
                provider=provider_config,
            )
            if result.get("status") == "failed":
                return result
            comments = result.get("segment_comments")
            if (
                not isinstance(comments, list)
                or len(comments) != 1
                or comments[0].get("segment_id") != segment_id
            ):
                raise AgentOutputValidationError(
                    "Agent 分片输出与输入片段不匹配"
                )
            self._merge_segment_result(
                job_id,
                result,
                replace_non_streaming=replace_non_streaming,
            )
            replace_non_streaming = False
            last_result = result

        merged_path = self.jobs.agent_report_path(job_id)
        if not merged_path.is_file():
            raise AgentOutputValidationError("Agent 分片结果未生成")
        merged = self._read_json_object(merged_path)
        if last_result is not None:
            merged["trace"] = last_result.get("trace", merged.get("trace", {}))
        staging_dir.joinpath("agent_report.json").write_text(
            json.dumps(merged, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        staging_dir.joinpath("agent_trace.json").write_text(
            json.dumps(
                {
                    "job_id": job_id,
                    "status": merged.get("status"),
                    "provider": merged.get("provider", {}),
                    "trace": merged.get("trace", {}),
                    "errors": merged.get("errors", []),
                    "streaming": True,
                    "completed_segment_count": merged.get(
                        "completed_segment_count",
                        0,
                    ),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return merged

    def finalize_segments(
        self,
        job_id: str,
        segments: list[dict[str, Any]],
    ) -> None:
        """Map provisional Agent comments onto final reconciled segment IDs."""

        mapping: dict[str, str] = {}
        for segment in segments:
            final_id = str(segment.get("id", "")).strip()
            if not final_id:
                continue
            agent_segment_id = str(
                segment.get("agent_segment_id", "")
            ).strip()
            if agent_segment_id:
                mapping[agent_segment_id] = final_id
            for source_id in segment.get("source_segment_ids", []):
                normalized = str(source_id).strip()
                if normalized:
                    mapping[normalized] = final_id
        with self._segment_report_lock:
            self._final_segment_maps[job_id] = mapping
            path = self.jobs.agent_report_path(job_id)
            if not path.is_file():
                return
            try:
                report = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                return
            if not isinstance(report, dict) or report.get("streaming") is not True:
                return
            remapped: dict[str, dict[str, Any]] = {}
            for item in report.get("segment_comments", []):
                if not isinstance(item, dict) or not item.get("segment_id"):
                    continue
                current_id = str(item["segment_id"])
                target_id = mapping.get(current_id, current_id)
                remapped[target_id] = {**item, "segment_id": target_id}
            report["segment_comments"] = list(remapped.values())
            report["completed_segment_count"] = len(remapped)
            self.jobs.write_agent_report(job_id, report)

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
                    input_summary="读取 CV 报告并逐片段执行 Agent",
                )
                report = self.jobs.read_report(job_id)
                service, provider_config = self._build_service()
                staging_dir = self._create_staging_dir(
                    job_id,
                    agent_call_id,
                )
                result = self._run_segmented_report(
                    service,
                    provider_config,
                    report,
                    staging_dir,
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
