"""Translate ReelFire CV and backend contracts without mutating source data."""

from __future__ import annotations

import copy
from typing import Any


SUPPORTED_PROVIDERS = {"ollama", "dify", "coze", "rule_only"}
BACKEND_TOOL_NAMES = {
    "report_parser": "visual_report_parser",
    "knowledge_retriever": "knowledge_retriever",
    "advice_generator": "advice_generator",
    "rule_validator": "result_validator",
}


def build_agent_input(
    analysis_report: dict[str, Any],
    *,
    provider: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Wrap the real CV ``analysis_report.json`` for the Agent service.

    The main ReelFire branch persists the report as a raw JSON object, while
    the Agent boundary also carries schema and provider metadata.  This adapter
    keeps those concerns separate and deliberately deep-copies both inputs so
    the Agent cannot modify the CV evidence owned by another module.
    """

    if not isinstance(analysis_report, dict):
        raise TypeError("analysis_report 必须是 JSON 对象")
    job_id = analysis_report.get("job_id")
    if not isinstance(job_id, str) or not job_id.strip():
        raise ValueError("analysis_report.job_id 必须是非空字符串")

    normalized_provider = copy.deepcopy(provider or {"type": "rule_only"})
    if not isinstance(normalized_provider, dict):
        raise TypeError("provider 必须是 JSON 对象")
    provider_type = normalized_provider.get("type")
    if provider_type not in SUPPORTED_PROVIDERS:
        raise ValueError("provider.type 不受支持")

    return {
        "schema_version": "1.0",
        "job_id": job_id.strip(),
        "provider": normalized_provider,
        "analysis_report": copy.deepcopy(analysis_report),
    }


def to_backend_agent_call(
    result: dict[str, Any],
    *,
    prompt_version: str = "v1",
) -> dict[str, Any]:
    """Map an Agent result to the backend ``agent_calls`` JSON contract."""

    if not isinstance(result, dict):
        raise TypeError("result 必须是 JSON 对象")
    trace = result.get("trace")
    if not isinstance(trace, dict):
        raise ValueError("result.trace 必须是 JSON 对象")

    status = _backend_status(result)
    errors = result.get("errors")
    errors = errors if isinstance(errors, list) else []
    first_error = errors[0] if errors and isinstance(errors[0], dict) else {}
    provider = result.get("provider")
    provider = provider if isinstance(provider, dict) else {}
    review = result.get("review")
    review = review if isinstance(review, dict) else {}

    tags = result.get("tags")
    tags = tags if isinstance(tags, list) else []
    suggestions = result.get("suggestions")
    suggestions = suggestions if isinstance(suggestions, list) else []
    knowledge_refs = result.get("knowledge_refs")
    knowledge_refs = (
        knowledge_refs if isinstance(knowledge_refs, list) else []
    )
    tools = trace.get("tools")
    tools = tools if isinstance(tools, list) else []

    return {
        "job_id": str(result.get("job_id", "")),
        "status": status,
        "model_name": str(provider.get("model", "")),
        "prompt_version": str(prompt_version),
        "input_summary": _input_summary(result),
        "output_summary": str(result.get("summary", ""))[:1000],
        "tool_trace": [
            {
                "tool": BACKEND_TOOL_NAMES.get(
                    str(item.get("name", "")),
                    str(item.get("name", "")),
                ),
                "status": str(item.get("status", "failed")),
                "duration_ms": max(0, int(item.get("duration_ms", 0))),
            }
            for item in tools
            if isinstance(item, dict)
        ],
        "references": copy.deepcopy(knowledge_refs),
        "result": {
            "summary": str(result.get("summary", "")),
            "labels": [
                str(item.get("name"))
                for item in tags
                if isinstance(item, dict) and item.get("name")
            ],
            "suggestions": [
                str(item.get("action") or item.get("title"))
                for item in suggestions
                if isinstance(item, dict)
                and (item.get("action") or item.get("title"))
            ],
            "review_status": (
                "pending"
                if status == "needs_review"
                else str(review.get("recommendation", "reject"))
            ),
            "reason": "；".join(
                str(reason)
                for reason in review.get("reasons", [])
                if isinstance(reason, str)
            ),
            "risk_flags": [
                str(item.get("code"))
                for item in errors
                if isinstance(item, dict) and item.get("code")
            ],
        },
        "duration_ms": max(0, int(trace.get("duration_ms", 0))),
        "error_code": first_error.get("code"),
        "error_message": first_error.get("message"),
        "created_at": trace.get("started_at"),
        "completed_at": trace.get("finished_at"),
    }


def _backend_status(result: dict[str, Any]) -> str:
    workflow_status = result.get("status")
    if workflow_status == "failed":
        return "failed"
    review = result.get("review")
    recommendation = (
        review.get("recommendation") if isinstance(review, dict) else None
    )
    if workflow_status == "degraded" or recommendation == "needs_review":
        return "needs_review"
    if workflow_status == "completed":
        return "completed"
    return "failed"


def _input_summary(result: dict[str, Any]) -> str:
    evidence_refs = result.get("evidence_refs")
    if not isinstance(evidence_refs, list):
        return "读取 CV 报告"
    report_ref = next(
        (
            item
            for item in evidence_refs
            if isinstance(item, dict) and item.get("type") == "report"
        ),
        None,
    )
    value = report_ref.get("value") if isinstance(report_ref, dict) else None
    if not isinstance(value, dict):
        return "读取 CV 报告"
    count = value.get("total_sampled_frames")
    if isinstance(count, int) and not isinstance(count, bool):
        return f"读取真实 CV 报告，共 {count} 个采样帧"
    return "读取 CV 报告"
