"""Validate editor feedback and derive deterministic Agent rule insights."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from time import perf_counter
from typing import Any


DECISIONS = {"adopted", "needs_review", "rejected"}
REJECTION_REASONS = {
    "not_highlight",
    "duplicate",
    "detection_error",
    "boundary_error",
    "other",
}


class FeedbackValidationError(ValueError):
    """Raised when a persisted editor feedback event is inconsistent."""


class FeedbackAnalyzerTool:
    """Summarize the latest feedback state for each candidate segment."""

    name = "feedback_analyzer"

    def run(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        started = perf_counter()
        if not isinstance(records, list):
            raise FeedbackValidationError("feedback records 必须是数组")
        normalized = [
            self._validate_record(record, index)
            for index, record in enumerate(records)
        ]
        latest: dict[tuple[str, str], dict[str, Any]] = {}
        for record in normalized:
            key = (record["job_id"], record["segment_id"])
            previous = latest.get(key)
            if previous is None or (
                record["recorded_at"], record["feedback_id"]
            ) >= (previous["recorded_at"], previous["feedback_id"]):
                latest[key] = record

        candidates = list(latest.values())
        decision_counts = Counter(item["decision"] for item in candidates)
        rejected = [item for item in candidates if item["decision"] == "rejected"]
        reason_counts = Counter(
            item["rejection_reason"]
            for item in rejected
            if item["rejection_reason"] is not None
        )
        adjusted = [
            item
            for item in candidates
            if item["start_adjustment_delta"] != 0
            or item["end_adjustment_delta"] != 0
        ]
        order_changed = [
            item
            for item in candidates
            if item["original_order"] != item["final_order"]
        ]
        reexported = [item for item in candidates if item["reexported"]]
        candidate_count = len(candidates)

        output = {
            "schema_version": "1.0",
            "status": "completed" if candidates else "needs_more_data",
            "event_count": len(normalized),
            "candidate_count": candidate_count,
            "decision_counts": {
                "adopted": decision_counts["adopted"],
                "needs_review": decision_counts["needs_review"],
                "rejected": decision_counts["rejected"],
            },
            "adoption_rate": self._rate(
                decision_counts["adopted"],
                candidate_count,
            ),
            "common_rejection_reasons": [
                {
                    "reason": reason,
                    "count": count,
                    "rate_among_rejections": self._rate(count, len(rejected)),
                }
                for reason, count in sorted(
                    reason_counts.items(),
                    key=lambda item: (-item[1], item[0]),
                )
            ],
            "boundary_adjustments": {
                "adjusted_count": len(adjusted),
                "adjustment_rate": self._rate(len(adjusted), candidate_count),
                "average_start_delta_seconds": self._average(
                    item["start_adjustment_delta"] for item in adjusted
                ),
                "average_end_delta_seconds": self._average(
                    item["end_adjustment_delta"] for item in adjusted
                ),
                "average_absolute_change_seconds": self._average(
                    abs(item["start_adjustment_delta"])
                    + abs(item["end_adjustment_delta"])
                    for item in adjusted
                ),
            },
            "order_changes": {
                "changed_count": len(order_changed),
                "change_rate": self._rate(len(order_changed), candidate_count),
            },
            "reexports": {
                "count": len(reexported),
                "rate": self._rate(len(reexported), candidate_count),
            },
            "rule_optimization_suggestions": self._suggestions(
                candidate_count,
                decision_counts,
                reason_counts,
                adjusted,
                reexported,
            ),
            "trace": {
                "tool": self.name,
                "status": "completed",
                "duration_ms": max(
                    0,
                    round((perf_counter() - started) * 1000),
                ),
                "source_event_count": len(normalized),
                "latest_candidate_count": candidate_count,
            },
        }
        return output

    def _validate_record(
        self,
        raw: Any,
        index: int,
    ) -> dict[str, Any]:
        field = f"feedback[{index}]"
        if not isinstance(raw, dict):
            raise FeedbackValidationError(f"{field} 必须是对象")
        if raw.get("schema_version") != "1.0":
            raise FeedbackValidationError(f"{field}.schema_version 仅支持 1.0")
        feedback_id = self._text(raw.get("feedback_id"), f"{field}.feedback_id")
        job_id = self._text(raw.get("job_id"), f"{field}.job_id")
        segment_id = self._text(raw.get("segment_id"), f"{field}.segment_id")
        decision = raw.get("decision")
        if decision not in DECISIONS:
            raise FeedbackValidationError(f"{field}.decision 不合法")
        rejection_reason = raw.get("rejection_reason")
        if decision == "rejected":
            if rejection_reason not in REJECTION_REASONS:
                raise FeedbackValidationError(
                    f"{field}.rejection_reason 不合法"
                )
        elif rejection_reason is not None:
            raise FeedbackValidationError(
                f"{field}.rejection_reason 仅拒绝时允许填写"
            )
        original = self._boundary(
            raw.get("original_boundary"),
            f"{field}.original_boundary",
        )
        final = self._boundary(
            raw.get("final_boundary"),
            f"{field}.final_boundary",
        )
        original_order = self._positive_int(
            raw.get("original_order"),
            f"{field}.original_order",
        )
        final_order = self._positive_int(
            raw.get("final_order"),
            f"{field}.final_order",
        )
        reexported = raw.get("reexported")
        if not isinstance(reexported, bool):
            raise FeedbackValidationError(f"{field}.reexported 必须是布尔值")
        recorded_at = self._timestamp(
            raw.get("recorded_at"),
            f"{field}.recorded_at",
        )
        return {
            "feedback_id": feedback_id,
            "job_id": job_id,
            "segment_id": segment_id,
            "decision": decision,
            "rejection_reason": rejection_reason,
            "original_boundary": original,
            "final_boundary": final,
            "start_adjustment_delta": round(
                final["start"] - original["start"],
                6,
            ),
            "end_adjustment_delta": round(
                final["end"] - original["end"],
                6,
            ),
            "original_order": original_order,
            "final_order": final_order,
            "reexported": reexported,
            "recorded_at": recorded_at,
        }

    @staticmethod
    def _suggestions(
        candidate_count: int,
        decisions: Counter[str],
        reasons: Counter[str],
        adjusted: list[dict[str, Any]],
        reexported: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        if candidate_count == 0:
            return [
                {
                    "suggestion_id": "FB-SUG-001",
                    "title": "继续收集审核反馈",
                    "action": "至少积累一批采用、拒绝和边界调整记录后再优化规则",
                    "basis": "当前没有可分析的候选反馈",
                    "priority": "medium",
                }
            ]
        suggestions: list[dict[str, str]] = []
        if decisions["rejected"] / candidate_count >= 0.3:
            top_reason = reasons.most_common(1)
            reason_text = top_reason[0][0] if top_reason else "未分类"
            suggestions.append(
                {
                    "suggestion_id": "FB-SUG-001",
                    "title": "收紧候选生成规则",
                    "action": "针对主要拒绝原因复核触发阈值和事件去重规则",
                    "basis": f"拒绝率较高，首要原因是 {reason_text}",
                    "priority": "high",
                }
            )
        if len(adjusted) / candidate_count >= 0.3:
            suggestions.append(
                {
                    "suggestion_id": f"FB-SUG-{len(suggestions) + 1:03d}",
                    "title": "校准片段前后缓冲",
                    "action": "结合平均起止调整量修改 CV 候选片段缓冲参数",
                    "basis": "边界调整率达到或超过 30%",
                    "priority": "high",
                }
            )
        if len(reexported) / candidate_count >= 0.3:
            suggestions.append(
                {
                    "suggestion_id": f"FB-SUG-{len(suggestions) + 1:03d}",
                    "title": "检查首次导出配置",
                    "action": "分析重新导出记录，优化默认分辨率、比例和片段顺序",
                    "basis": "重新导出率达到或超过 30%",
                    "priority": "medium",
                }
            )
        if not suggestions:
            suggestions.append(
                {
                    "suggestion_id": "FB-SUG-001",
                    "title": "保持当前规则并继续观察",
                    "action": "继续累计反馈，达到稳定样本量后再调整阈值",
                    "basis": "当前拒绝、边界调整和重新导出比例未达到触发线",
                    "priority": "low",
                }
            )
        return suggestions

    @staticmethod
    def _text(value: Any, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise FeedbackValidationError(f"{field} 必须是非空字符串")
        return value.strip()

    @staticmethod
    def _boundary(value: Any, field: str) -> dict[str, float]:
        if not isinstance(value, dict):
            raise FeedbackValidationError(f"{field} 必须是对象")
        start = FeedbackAnalyzerTool._number(value.get("start"), f"{field}.start")
        end = FeedbackAnalyzerTool._number(value.get("end"), f"{field}.end")
        if start < 0 or start >= end:
            raise FeedbackValidationError(f"{field} 必须满足 0 <= start < end")
        return {"start": round(start, 6), "end": round(end, 6)}

    @staticmethod
    def _number(value: Any, field: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise FeedbackValidationError(f"{field} 必须是数字")
        result = float(value)
        if result != result or result in {float("inf"), float("-inf")}:
            raise FeedbackValidationError(f"{field} 必须是有限数字")
        return result

    @staticmethod
    def _positive_int(value: Any, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise FeedbackValidationError(f"{field} 必须是正整数")
        return value

    @staticmethod
    def _timestamp(value: Any, field: str) -> str:
        text = FeedbackAnalyzerTool._text(value, field)
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise FeedbackValidationError(f"{field} 必须是 ISO 8601 时间") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise FeedbackValidationError(f"{field} 必须包含时区")
        return parsed.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _rate(numerator: int, denominator: int) -> float:
        return round(numerator / denominator, 6) if denominator else 0.0

    @staticmethod
    def _average(values: Any) -> float:
        items = list(values)
        return round(sum(items) / len(items), 6) if items else 0.0
