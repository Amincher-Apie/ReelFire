"""Execute ReelFire Agent calls and persist their real lifecycle."""

from __future__ import annotations

import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Any

from agent.integrations import to_backend_agent_call
from agent.providers import DifyChatClient, OllamaChatClient
from agent.service import AgentService
from agent.tools import AdviceGeneratorTool, KnowledgeRetrieverTool, OllamaEmbedder
from services.agent_call_service import (
    complete_agent_call,
    fail_agent_call,
    mark_agent_call_running,
)
from services.job_service import JobService

if TYPE_CHECKING:
    from flask import Flask


LOGGER = logging.getLogger(__name__)


class AgentExecutionService:
    """Run queued Agent calls in-process with an isolated Flask context."""

    def __init__(
        self,
        app: Flask,
        jobs: JobService,
        *,
        max_workers: int = 1,
        provider: str = "rule_only",
    ) -> None:
        if provider not in {"dify", "ollama", "rule_only"}:
            raise ValueError("AGENT_PROVIDER 仅支持 dify、ollama 或 rule_only")
        self.app = app
        self.jobs = jobs
        self.provider = provider
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, int(max_workers)),
            thread_name_prefix="reelfire-agent",
        )
        self._active: set[int] = set()
        self._active_lock = threading.Lock()

    def enqueue(
        self,
        agent_call_id: int,
        job_id: str,
        *,
        prompt_version: str,
    ) -> None:
        with self._active_lock:
            if agent_call_id in self._active:
                raise RuntimeError("Agent 调用已在执行")
            self._active.add(agent_call_id)
        try:
            self._executor.submit(
                self._run,
                agent_call_id,
                job_id,
                prompt_version,
            )
        except RuntimeError:
            with self._active_lock:
                self._active.discard(agent_call_id)
            with self.app.app_context():
                fail_agent_call(
                    agent_call_id,
                    error_code="AGENT_SCHEDULER_UNAVAILABLE",
                    error_message="Agent 后台调度器不可用",
                    duration_ms=0,
                    tool_trace=[],
                )
            raise

    def _run(
        self,
        agent_call_id: int,
        job_id: str,
        prompt_version: str,
    ) -> None:
        started = perf_counter()
        try:
            with self.app.app_context():
                report = self.jobs.read_report(job_id)
                service, provider_config = self._build_service()
                mark_agent_call_running(
                    agent_call_id,
                    model_name=provider_config["model"],
                    input_summary="读取真实 CV analysis_report.json",
                )
                result = service.run_analysis_report(
                    report,
                    provider=provider_config,
                    output_dir=self.jobs.job_dir(job_id),
                )
                backend = to_backend_agent_call(
                    result,
                    prompt_version=prompt_version,
                )
                if backend["status"] == "failed":
                    fail_agent_call(
                        agent_call_id,
                        error_code=backend.get("error_code")
                        or "AGENT_EXECUTION_FAILED",
                        error_message=backend.get("error_message")
                        or "Agent 未生成安全结果",
                        duration_ms=backend["duration_ms"],
                        tool_trace=backend["tool_trace"],
                    )
                else:
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
        except Exception as exc:
            LOGGER.exception("Agent 调用 %s 执行失败", agent_call_id)
            with self.app.app_context():
                try:
                    fail_agent_call(
                        agent_call_id,
                        error_code="AGENT_EXECUTION_FAILED",
                        error_message=self._safe_error(exc),
                        duration_ms=max(0, int((perf_counter() - started) * 1000)),
                    )
                except Exception:
                    LOGGER.exception("无法写回 Agent 调用 %s 的失败状态", agent_call_id)
        finally:
            with self._active_lock:
                self._active.discard(agent_call_id)

    def _build_service(self) -> tuple[AgentService, dict[str, str]]:
        client: DifyChatClient | OllamaChatClient | None = None
        if self.provider == "dify":
            client = DifyChatClient()
        elif self.provider == "ollama":
            client = OllamaChatClient()
        embedder = OllamaEmbedder() if os.getenv("OLLAMA_EMBED_MODEL") else None
        model = client.model if client is not None else "deterministic-v1"
        service = AgentService(
            knowledge_retriever=KnowledgeRetrieverTool(embedder=embedder),
            advice_generator=AdviceGeneratorTool(model_client=client),
        )
        return service, {"type": self.provider, "model": model}

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        message = str(exc).strip().replace("\n", " ")
        return (message or exc.__class__.__name__)[:1000]

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=False)
