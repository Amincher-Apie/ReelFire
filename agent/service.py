"""Orchestrate Agent tools, persist reports, and retain safe call traces."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Callable
from uuid import uuid4

from agent.tools.advice_generator import AdviceGeneratorTool
from agent.tools.knowledge_retriever import KnowledgeRetrieverTool
from agent.tools.report_parser import ReportParserTool
from agent.tools.rule_validator import OutputValidationError, RuleValidatorTool


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _duration_ms(started: float) -> int:
    return max(0, round((perf_counter() - started) * 1000))


class AgentService:
    """Run the evidence-bound workflow without changing the source CV report."""

    def __init__(
        self,
        *,
        report_parser: ReportParserTool | None = None,
        knowledge_retriever: KnowledgeRetrieverTool | None = None,
        advice_generator: AdviceGeneratorTool | None = None,
        rule_validator: RuleValidatorTool | None = None,
    ) -> None:
        self.report_parser = report_parser or ReportParserTool()
        self.knowledge_retriever = (
            knowledge_retriever or KnowledgeRetrieverTool()
        )
        self.advice_generator = advice_generator or AdviceGeneratorTool()
        self.rule_validator = rule_validator or RuleValidatorTool()

    def run(
        self,
        payload: dict[str, Any],
        *,
        output_dir: Path | None = None,
    ) -> dict[str, Any]:
        workflow_started = perf_counter()
        started_at = _utc_now()
        trace_tools: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        input_hash = self._input_hash(payload)
        provider_config = (
            payload.get("provider", {})
            if isinstance(payload, dict)
            else {}
        )
        job_id = (
            str(payload.get("job_id", "invalid"))
            if isinstance(payload, dict)
            else "invalid"
        )

        try:
            visual_summary = self._call(
                trace_tools,
                "report_parser",
                lambda: self.report_parser.run(payload),
            )
        except Exception as exc:
            errors.append(
                self._error(
                    "invalid_agent_input",
                    exc,
                    "report_parser",
                    False,
                )
            )
            trace_tools.extend(
                [
                    self._skipped("knowledge_retriever"),
                    self._skipped("advice_generator"),
                    self._skipped("rule_validator"),
                ]
            )
            result = self._failed_result(
                job_id,
                provider_config,
                started_at,
                workflow_started,
                input_hash,
                trace_tools,
                errors,
            )
            self._persist_safely(result, output_dir)
            return result

        try:
            retrieval = self._call(
                trace_tools,
                "knowledge_retriever",
                lambda: self.knowledge_retriever.run(visual_summary),
                status_getter=lambda value: str(
                    value.get("status", "completed")
                ),
            )
        except Exception as exc:
            errors.append(
                self._error(
                    "knowledge_retrieval_failed",
                    exc,
                    "knowledge_retriever",
                    True,
                )
            )
            retrieval = KnowledgeRetrieverTool().run(visual_summary)
            trace_tools[-1] = {
                "name": "knowledge_retriever",
                "status": "degraded",
                "duration_ms": trace_tools[-1]["duration_ms"],
                "detail": "检索工具失败，已使用确定性规则检索",
            }
        if retrieval.get("status") == "degraded":
            errors.append(
                {
                    "code": "knowledge_retrieval_degraded",
                    "message": str(
                        retrieval.get("degraded_reason")
                        or "知识检索已切换确定性规则"
                    )[:300],
                    "stage": "knowledge_retriever",
                    "retryable": True,
                }
            )

        try:
            generation = self._call(
                trace_tools,
                "advice_generator",
                lambda: self.advice_generator.run(
                    visual_summary,
                    retrieval,
                    requested_provider=provider_config,
                ),
                status_getter=lambda value: str(
                    value.get("status", "completed")
                ),
            )
        except Exception as exc:
            errors.append(
                self._error(
                    "advice_generation_failed",
                    exc,
                    "advice_generator",
                    True,
                )
            )
            generation = AdviceGeneratorTool().run(
                visual_summary,
                retrieval,
                requested_provider={"type": "rule_only"},
            )
            generation["status"] = "degraded"
            trace_tools[-1] = {
                "name": "advice_generator",
                "status": "degraded",
                "duration_ms": trace_tools[-1]["duration_ms"],
                "detail": "建议工具失败，已使用确定性规则生成",
            }
        if generation.get("error"):
            errors.append(generation["error"])

        validation_degraded = False
        validation_started = perf_counter()
        try:
            business = self.rule_validator.run(
                generation["draft"],
                visual_summary,
                retrieval,
            )
            trace_tools.append(
                {
                    "name": "rule_validator",
                    "status": "completed",
                    "duration_ms": _duration_ms(validation_started),
                }
            )
        except Exception as exc:
            errors.append(
                self._error(
                    "generated_output_rejected",
                    exc,
                    "rule_validator",
                    False,
                )
            )
            fallback = self.advice_generator.deterministic_draft(
                visual_summary,
                retrieval,
            )
            try:
                business = self.rule_validator.run(
                    fallback,
                    visual_summary,
                    retrieval,
                )
            except OutputValidationError as fallback_exc:
                trace_tools.append(
                    {
                        "name": "rule_validator",
                        "status": "failed",
                        "duration_ms": _duration_ms(validation_started),
                        "detail": self._safe_error(fallback_exc),
                    }
                )
                errors.append(
                    self._error(
                        "fallback_output_rejected",
                        fallback_exc,
                        "rule_validator",
                        False,
                    )
                )
                result = self._failed_result(
                    job_id,
                    generation.get("provider", provider_config),
                    started_at,
                    workflow_started,
                    input_hash,
                    trace_tools,
                    errors,
                    evidence_refs=visual_summary.get("evidence_refs", []),
                )
                self._persist_safely(result, output_dir)
                return result
            validation_degraded = True
            generation["status"] = "degraded"
            generation["provider"] = {
                "type": "rule_only",
                "model": "deterministic-v1",
                "request_id": None,
            }
            trace_tools.append(
                {
                    "name": "rule_validator",
                    "status": "degraded",
                    "duration_ms": _duration_ms(validation_started),
                    "detail": "模型草稿被拒绝，已使用确定性安全输出",
                }
            )

        degraded = (
            retrieval.get("status") == "degraded"
            or generation.get("status") == "degraded"
            or validation_degraded
        )
        result = {
            "schema_version": "1.0",
            "job_id": job_id,
            "status": "degraded" if degraded else "completed",
            "provider": generation["provider"],
            **business,
            "trace": self._trace(
                started_at,
                workflow_started,
                input_hash,
                degraded,
                trace_tools,
            ),
            "errors": errors,
        }
        self._persist_safely(result, output_dir)
        return result

    def run_analysis_report(
        self,
        analysis_report: dict[str, Any],
        *,
        provider: dict[str, Any] | None = None,
        output_dir: Path | None = None,
    ) -> dict[str, Any]:
        """Run directly from the CV module's persisted report contract."""

        from agent.integrations.reelfire import build_agent_input

        payload = build_agent_input(
            analysis_report,
            provider=provider,
        )
        return self.run(payload, output_dir=output_dir)

    @staticmethod
    def _call(
        trace_tools: list[dict[str, Any]],
        name: str,
        function: Callable[[], Any],
        *,
        status_getter: Callable[[Any], str] | None = None,
    ) -> Any:
        started = perf_counter()
        try:
            result = function()
        except Exception as exc:
            trace_tools.append(
                {
                    "name": name,
                    "status": "failed",
                    "duration_ms": _duration_ms(started),
                    "detail": AgentService._safe_error(exc),
                }
            )
            raise
        status = status_getter(result) if status_getter else "completed"
        trace_tools.append(
            {
                "name": name,
                "status": status,
                "duration_ms": _duration_ms(started),
            }
        )
        return result

    @staticmethod
    def _trace(
        started_at: str,
        workflow_started: float,
        input_hash: str,
        degraded: bool,
        tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "started_at": started_at,
            "finished_at": _utc_now(),
            "duration_ms": _duration_ms(workflow_started),
            "degraded": degraded,
            "input_summary_hash": input_hash,
            "tools": tools,
        }

    def _failed_result(
        self,
        job_id: str,
        provider: dict[str, Any],
        started_at: str,
        workflow_started: float,
        input_hash: str,
        tools: list[dict[str, Any]],
        errors: list[dict[str, Any]],
        *,
        evidence_refs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        provider_type = str(provider.get("type", "rule_only"))
        if provider_type not in {"ollama", "dify", "coze", "rule_only"}:
            provider_type = "rule_only"
        return {
            "schema_version": "1.0",
            "job_id": job_id,
            "status": "failed",
            "provider": {
                "type": provider_type,
                "model": str(provider.get("model", "")),
                "request_id": None,
            },
            "summary": "Agent 无法形成安全输出。",
            "tags": [],
            "suggestions": [],
            "review": {
                "recommendation": "reject",
                "confidence": 1.0,
                "reasons": ["输入或输出未通过安全校验"],
            },
            "evidence_refs": evidence_refs or [],
            "knowledge_refs": [],
            "trace": self._trace(
                started_at,
                workflow_started,
                input_hash,
                False,
                tools,
            ),
            "errors": errors,
        }

    @staticmethod
    def _skipped(name: str) -> dict[str, Any]:
        return {"name": name, "status": "skipped", "duration_ms": 0}

    @staticmethod
    def _error(
        code: str,
        exc: Exception,
        stage: str,
        retryable: bool,
    ) -> dict[str, Any]:
        return {
            "code": code,
            "message": AgentService._safe_error(exc),
            "stage": stage,
            "retryable": retryable,
        }

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        message = str(exc).strip().replace("\n", " ")
        if re.search(r"[A-Za-z]:[\\/]", message):
            return f"{exc.__class__.__name__}: local path omitted"
        return (message or exc.__class__.__name__)[:300]

    @staticmethod
    def _input_hash(payload: Any) -> str:
        try:
            serialized = json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        except (TypeError, ValueError):
            serialized = repr(type(payload))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @staticmethod
    def _write_json(destination: Path, data: dict[str, Any]) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(
            f".{destination.name}.{uuid4().hex}.tmp"
        )
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

    def _persist_if_requested(
        self,
        result: dict[str, Any],
        output_dir: Path | None,
    ) -> None:
        if output_dir is None:
            return
        destination = Path(output_dir)
        self._write_json(destination / "agent_report.json", result)
        self._write_json(
            destination / "agent_trace.json",
            {
                "job_id": result["job_id"],
                "status": result["status"],
                "provider": result["provider"],
                "trace": result["trace"],
                "errors": result["errors"],
            },
        )

    def _persist_safely(
        self,
        result: dict[str, Any],
        output_dir: Path | None,
    ) -> None:
        try:
            self._persist_if_requested(result, output_dir)
        except OSError as exc:
            result["errors"].append(
                self._error(
                    "agent_persistence_failed",
                    exc,
                    "persistence",
                    True,
                )
            )
            if result["status"] == "completed":
                result["status"] = "degraded"
            result["trace"]["degraded"] = result["status"] == "degraded"
