"""Generate an evidence-backed business draft with a deterministic fallback."""

from __future__ import annotations

from typing import Any, Protocol


class ModelClient(Protocol):
    provider_type: str
    model: str

    def generate(
        self,
        job_id: str,
        visual_summary: dict[str, Any],
        knowledge_context: dict[str, Any],
    ) -> dict[str, Any]: ...


class AdviceGeneratorTool:
    """Use a model when configured and retain a fully testable rule fallback."""

    name = "advice_generator"

    def __init__(self, model_client: ModelClient | None = None) -> None:
        self.model_client = model_client

    def run(
        self,
        visual_summary: dict[str, Any],
        retrieval: dict[str, Any],
        *,
        requested_provider: dict[str, Any],
    ) -> dict[str, Any]:
        provider_type = str(requested_provider.get("type", "rule_only"))
        requested_model = str(requested_provider.get("model", ""))
        if provider_type != "rule_only" and self.model_client is not None:
            try:
                draft = self.model_client.generate(
                    str(visual_summary["job_id"]),
                    visual_summary,
                    retrieval,
                )
                return {
                    "status": "completed",
                    "attempt_count": int(
                        getattr(self.model_client, "last_attempt_count", 1)
                    ),
                    "provider": {
                        "type": self.model_client.provider_type,
                        "model": self.model_client.model,
                        "request_id": getattr(
                            self.model_client,
                            "last_request_id",
                            None,
                        ),
                    },
                    "draft": draft,
                    "error": None,
                }
            except Exception as exc:
                provider_code = str(
                    getattr(exc, "provider_code", "model_provider_error")
                )
                attempt_count = max(
                    0,
                    int(getattr(exc, "attempt_count", 1)),
                )
                return {
                    "status": "degraded",
                    "attempt_count": attempt_count,
                    "provider": {
                        "type": "rule_only",
                        "model": "deterministic-v1",
                        "request_id": getattr(exc, "request_id", None),
                    },
                    "draft": self.deterministic_draft(
                        visual_summary,
                        retrieval,
                    ),
                    "error": {
                        "code": "model_generation_failed",
                        "message": self._safe_error(exc),
                        "stage": self.name,
                        "retryable": bool(
                            getattr(exc, "retryable", True)
                        ),
                        "provider_code": provider_code,
                        "attempt_count": attempt_count,
                    },
                }

        status = "completed"
        error = None
        if provider_type != "rule_only":
            status = "degraded"
            error = {
                "code": "model_provider_not_configured",
                "message": f"{provider_type} 未配置，已切换规则生成",
                "stage": self.name,
                "retryable": False,
                "provider_code": f"{provider_type}_not_configured",
                "attempt_count": 0,
            }
        return {
            "status": status,
            "attempt_count": 0,
            "provider": {
                "type": "rule_only",
                "model": requested_model or "deterministic-v1",
                "request_id": None,
            },
            "draft": self.deterministic_draft(visual_summary, retrieval),
            "error": error,
        }

    def deterministic_draft(
        self,
        visual_summary: dict[str, Any],
        retrieval: dict[str, Any],
    ) -> dict[str, Any]:
        classes = visual_summary.get("detected_classes", [])
        metrics = visual_summary.get("metrics", {})
        evidence = visual_summary.get("evidence_refs", [])
        evidence_ids = {item["ref_id"] for item in evidence}
        report_ref = "ev:report" if "ev:report" in evidence_ids else next(
            iter(evidence_ids),
            "",
        )
        score_refs = [
            item["ref_id"] for item in evidence if item.get("type") == "score"
        ]
        segment_refs = [
            item["ref_id"] for item in evidence if item.get("type") == "segment"
        ]

        tags = []
        class_evidence: dict[str, list[str]] = {}
        for item in classes:
            refs = [
                ref
                for ref in item.get("evidence_refs", [])
                if ref in evidence_ids
            ]
            if not refs and report_ref:
                refs = [report_ref]
            class_evidence[str(item["name"]).casefold()] = refs
            tags.append(
                {
                    "name": str(item["name"]),
                    "description": (
                        f"检测 {int(item['count'])} 次，"
                        f"最高置信度 {float(item['max_confidence']):.3f}"
                    ),
                    "evidence_refs": refs[:6],
                }
            )

        suggestions = []
        for index, item in enumerate(retrieval.get("results", [])[:3], start=1):
            refs = self._references_for_result(
                item,
                class_evidence,
                score_refs,
                segment_refs,
                report_ref,
            )
            recommendation = item.get("review_recommendation")
            priority = {
                "reject": "high",
                "needs_review": "medium",
                "pass": "low",
            }.get(recommendation, "medium")
            actions = item.get("suggestions", [])
            action = str(actions[0]) if actions else str(
                item.get("summary_guidance", "人工复核当前素材")
            )
            suggestions.append(
                {
                    "suggestion_id": f"SUG-{index:03d}",
                    "title": str(item["title"]),
                    "action": action,
                    "priority": priority,
                    "evidence_refs": refs,
                    "knowledge_refs": [str(item["knowledge_id"])],
                }
            )

        total_detections = int(metrics.get("total_detections", 0))
        max_highlight = float(metrics.get("max_highlight_score", 0.0))
        if classes:
            class_text = "、".join(
                f"{item['name']}({item['count']})" for item in classes
            )
            summary = (
                f"共采样 {visual_summary.get('total_sampled_frames', 0)} 帧，"
                f"检测到 {class_text}；最高精彩度 {max_highlight:.3f}，"
                f"候选片段 {visual_summary.get('segment_count', 0)} 个。"
            )
        else:
            summary = (
                f"共采样 {visual_summary.get('total_sampled_frames', 0)} 帧，"
                "没有可靠目标类别证据；"
                f"最高精彩度 {max_highlight:.3f}，需人工复核。"
            )

        active_recommendations = [
            item.get("review_recommendation")
            for item in retrieval.get("results", [])
            if any(
                reason.startswith(("class:", "metric:"))
                for reason in item.get("match_reasons", [])
            )
        ]
        review = "pass"
        reasons = ["检测证据和知识规则可追溯"]
        confidence = min(0.95, float(metrics.get("max_confidence", 0.0)))
        if "reject" in active_recommendations:
            review = "reject"
            reasons = ["命中不通过规则，需要停止自动通过"]
        elif (
            total_detections == 0
            or "needs_review" in active_recommendations
            or retrieval.get("status") == "degraded"
        ):
            review = "needs_review"
            reasons = ["检测证据不足、存在低置信度条件或检索已降级"]
            confidence = min(confidence, 0.45)
        if not retrieval.get("results"):
            review = "needs_review"
            reasons = ["知识库未命中，必须人工复核"]
            confidence = min(confidence, 0.35)

        if not suggestions and report_ref:
            suggestions.append(
                {
                    "suggestion_id": "SUG-001",
                    "title": "人工复核素材",
                    "action": "检查原始素材、关键帧和候选片段后再确认审核状态",
                    "priority": "high",
                    "evidence_refs": [report_ref],
                    "knowledge_refs": [],
                }
            )

        return {
            "summary": summary,
            "tags": tags,
            "suggestions": suggestions,
            "review": {
                "recommendation": review,
                "confidence": round(max(0.0, confidence), 6),
                "reasons": reasons,
            },
        }

    @staticmethod
    def _references_for_result(
        result: dict[str, Any],
        class_evidence: dict[str, list[str]],
        score_refs: list[str],
        segment_refs: list[str],
        report_ref: str,
    ) -> list[str]:
        references: list[str] = []
        reasons = result.get("match_reasons", [])
        for reason in reasons:
            if reason.startswith("class:"):
                references.extend(
                    class_evidence.get(reason.split(":", 1)[1].casefold(), [])
                )
            elif reason.startswith("metric:"):
                references.extend(score_refs[:1])
        if any(reason == "always_apply" for reason in reasons):
            references.extend(segment_refs[:1] or ([report_ref] if report_ref else []))
        if not references:
            references.extend(score_refs[:1] or ([report_ref] if report_ref else []))
        return list(dict.fromkeys(reference for reference in references if reference))

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        message = str(exc).strip().replace("\n", " ")
        return (message or exc.__class__.__name__)[:300]
