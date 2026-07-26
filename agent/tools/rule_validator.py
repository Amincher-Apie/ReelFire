"""Validate model or rule drafts against controlled evidence and knowledge."""

from __future__ import annotations

from typing import Any


FORBIDDEN_UNGROUNDED_TERMS = (
    "击杀",
    "爆头",
    "残局",
    "胜负",
    "获胜",
    "失败方",
    "武器名称",
    "步枪",
    "手枪",
)
FORBIDDEN_PLACEHOLDER_TERMS = (
    "仅基于证据的简短摘要",
    "真实类别或可证明的画面属性",
    "标签说明",
    "建议标题",
    "可执行的剪辑或复核动作",
)
REVIEW_STATES = {"pass", "needs_review", "reject"}
PRIORITIES = {"high", "medium", "low"}


class OutputValidationError(ValueError):
    """Raised when a generated draft cannot be grounded safely."""


class RuleValidatorTool:
    """Enforce output structure, references, review state and fact boundaries."""

    name = "rule_validator"

    def run(
        self,
        draft: dict[str, Any],
        visual_summary: dict[str, Any],
        retrieval: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(draft, dict):
            raise OutputValidationError("Agent 草稿必须是 JSON 对象")

        evidence = visual_summary.get("evidence_refs", [])
        evidence_ids = {
            item.get("ref_id")
            for item in evidence
            if isinstance(item, dict) and item.get("ref_id")
        }
        knowledge_results = retrieval.get("results", [])
        knowledge_by_id = {
            item["knowledge_id"]: item
            for item in knowledge_results
            if isinstance(item, dict) and item.get("knowledge_id")
        }

        summary = self._string(draft.get("summary"), "summary")
        self._reject_ungrounded_text(summary, "summary")
        tags = self._validate_tags(draft.get("tags"), evidence_ids)
        suggestions = self._validate_suggestions(
            draft.get("suggestions"),
            evidence_ids,
            set(knowledge_by_id),
        )
        review = self._validate_review(draft.get("review"))
        segment_comments = self._build_segment_comments(
            visual_summary,
            evidence_ids,
        )

        if not visual_summary.get("detected_classes"):
            if review["recommendation"] != "needs_review":
                raise OutputValidationError(
                    "空检测结果必须返回 needs_review"
                )
        if retrieval.get("status") == "degraded":
            if review["recommendation"] == "pass":
                raise OutputValidationError(
                    "知识检索降级时不能自动返回 pass"
                )
        if not knowledge_results and review["recommendation"] == "pass":
            raise OutputValidationError("知识库未命中时不能自动返回 pass")

        return {
            "summary": summary,
            "tags": tags,
            "suggestions": suggestions,
            "segment_comments": segment_comments,
            "review": review,
            "evidence_refs": list(evidence),
            "knowledge_refs": [
                {
                    "knowledge_id": item["knowledge_id"],
                    "category": str(item["category"]),
                    "title": str(item["title"]),
                }
                for item in knowledge_results
            ],
        }

    def _validate_tags(
        self,
        raw_tags: Any,
        evidence_ids: set[str],
    ) -> list[dict[str, Any]]:
        if not isinstance(raw_tags, list):
            raise OutputValidationError("tags 必须是数组")
        tags = []
        for index, raw in enumerate(raw_tags):
            field = f"tags[{index}]"
            if not isinstance(raw, dict):
                raise OutputValidationError(f"{field} 必须是对象")
            name = self._string(raw.get("name"), f"{field}.name")
            description = self._string(
                raw.get("description", ""),
                f"{field}.description",
                allow_empty=True,
            )
            self._reject_ungrounded_text(name, f"{field}.name")
            self._reject_ungrounded_text(description, f"{field}.description")
            refs = self._validate_refs(
                raw.get("evidence_refs"),
                evidence_ids,
                f"{field}.evidence_refs",
                require_non_empty=True,
            )
            tags.append(
                {
                    "name": name,
                    "description": description,
                    "evidence_refs": refs,
                }
            )
        return tags

    def _validate_suggestions(
        self,
        raw_suggestions: Any,
        evidence_ids: set[str],
        knowledge_ids: set[str],
    ) -> list[dict[str, Any]]:
        if not isinstance(raw_suggestions, list) or not raw_suggestions:
            raise OutputValidationError("suggestions 必须是非空数组")
        suggestions = []
        seen_ids = set()
        for index, raw in enumerate(raw_suggestions):
            field = f"suggestions[{index}]"
            if not isinstance(raw, dict):
                raise OutputValidationError(f"{field} 必须是对象")
            suggestion_id = self._string(
                raw.get("suggestion_id"),
                f"{field}.suggestion_id",
            )
            if suggestion_id in seen_ids:
                raise OutputValidationError("suggestion_id 不能重复")
            seen_ids.add(suggestion_id)
            title = self._string(raw.get("title"), f"{field}.title")
            action = self._string(raw.get("action"), f"{field}.action")
            self._reject_ungrounded_text(title, f"{field}.title")
            self._reject_ungrounded_text(action, f"{field}.action")
            priority = raw.get("priority")
            if priority not in PRIORITIES:
                raise OutputValidationError(f"{field}.priority 不合法")
            evidence_refs = self._validate_refs(
                raw.get("evidence_refs"),
                evidence_ids,
                f"{field}.evidence_refs",
                require_non_empty=True,
            )
            knowledge_refs = self._validate_refs(
                raw.get("knowledge_refs"),
                knowledge_ids,
                f"{field}.knowledge_refs",
                require_non_empty=False,
            )
            suggestions.append(
                {
                    "suggestion_id": suggestion_id,
                    "title": title,
                    "action": action,
                    "priority": priority,
                    "evidence_refs": evidence_refs,
                    "knowledge_refs": knowledge_refs,
                }
            )
        return suggestions

    def _build_segment_comments(
        self,
        visual_summary: dict[str, Any],
        evidence_ids: set[str],
    ) -> list[dict[str, Any]]:
        raw_segments = visual_summary.get("segments", [])
        if not isinstance(raw_segments, list):
            raise OutputValidationError("visual_summary.segments 必须是数组")
        comments = []
        seen_ids = set()
        for index, raw in enumerate(raw_segments):
            field = f"visual_summary.segments[{index}]"
            if not isinstance(raw, dict):
                raise OutputValidationError(f"{field} 必须是对象")
            segment_id = self._string(raw.get("id"), f"{field}.id")
            if segment_id in seen_ids:
                raise OutputValidationError("segment_comments.segment_id 不能重复")
            seen_ids.add(segment_id)
            start = self._finite_number(raw.get("start"), f"{field}.start")
            end = self._finite_number(raw.get("end"), f"{field}.end")
            if start < 0 or start >= end:
                raise OutputValidationError(f"{field} 时间边界非法")

            segment_ref = f"ev:segment:{segment_id}"
            if segment_ref not in evidence_ids:
                raise OutputValidationError(
                    f"{field} 缺少对应片段证据"
                )
            refs = [segment_ref]
            class_parts = []
            raw_classes = raw.get("detected_classes", [])
            if not isinstance(raw_classes, list):
                raise OutputValidationError(
                    f"{field}.detected_classes 必须是数组"
                )
            max_confidence = 0.0
            for class_index, detected in enumerate(raw_classes):
                if not isinstance(detected, dict):
                    raise OutputValidationError(
                        f"{field}.detected_classes[{class_index}] 必须是对象"
                    )
                class_name = self._string(
                    detected.get("name"),
                    f"{field}.detected_classes[{class_index}].name",
                )
                label = self._class_label(class_name)
                track_count = detected.get("track_count", 0)
                if (
                    isinstance(track_count, int)
                    and not isinstance(track_count, bool)
                    and track_count > 0
                ):
                    class_parts.append(f"{track_count}个{label}")
                else:
                    class_parts.append(label)
                confidence = detected.get("max_confidence", 0)
                if isinstance(confidence, (int, float)) and not isinstance(
                    confidence,
                    bool,
                ):
                    max_confidence = max(max_confidence, float(confidence))
                class_refs = detected.get("evidence_refs", [])
                if isinstance(class_refs, list):
                    refs.extend(
                        ref
                        for ref in class_refs
                        if isinstance(ref, str) and ref in evidence_ids
                    )

            score = raw.get("score")
            score_value = None
            if score is not None:
                score_value = self._finite_number(score, f"{field}.score")
                if not 0 <= score_value <= 1:
                    raise OutputValidationError(
                        f"{field}.score 必须位于 0 到 1"
                    )

            time_text = f"{start:.1f}—{end:.1f}秒"
            if class_parts:
                fact_text = "检测到" + "、".join(class_parts)
            else:
                fact_text = "未检出可用于评论的稳定目标类别"
            if score_value is None:
                score_reason = "CV 未提供可验证的片段评分"
                action_text = "建议结合关键帧人工复核"
                review_status = "needs_review"
            elif score_value >= 0.7:
                score_reason = f"CV 精彩度评分为 {score_value:.3f}"
                action_text = "评分较高，建议优先复核"
                review_status = (
                    "pass" if max_confidence >= 0.7 else "needs_review"
                )
            elif score_value >= 0.4:
                score_reason = f"CV 精彩度评分为 {score_value:.3f}"
                action_text = "评分中等，建议结合关键帧复核"
                review_status = "needs_review"
            else:
                score_reason = f"CV 精彩度评分为 {score_value:.3f}"
                action_text = "评分较低，建议人工确认是否保留"
                review_status = "needs_review"

            comments.append(
                {
                    "segment_id": segment_id,
                    "title": f"片段 {index + 1}",
                    "comment": (
                        f"{time_text}{fact_text}；{score_reason}，{action_text}。"
                    ),
                    "score_reason": score_reason,
                    "review_status": review_status,
                    "evidence_refs": list(dict.fromkeys(refs))[:20],
                }
            )
        return comments

    def _validate_review(self, raw_review: Any) -> dict[str, Any]:
        if not isinstance(raw_review, dict):
            raise OutputValidationError("review 必须是对象")
        recommendation = raw_review.get("recommendation")
        if recommendation not in REVIEW_STATES:
            raise OutputValidationError("review.recommendation 不合法")
        confidence = raw_review.get("confidence")
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0 <= float(confidence) <= 1
        ):
            raise OutputValidationError("review.confidence 必须位于 0 到 1")
        reasons = raw_review.get("reasons")
        if not isinstance(reasons, list) or not reasons:
            raise OutputValidationError("review.reasons 必须是非空数组")
        normalized_reasons = [
            self._string(reason, f"review.reasons[{index}]")
            for index, reason in enumerate(reasons)
        ]
        for index, reason in enumerate(normalized_reasons):
            self._reject_ungrounded_text(reason, f"review.reasons[{index}]")
        return {
            "recommendation": recommendation,
            "confidence": round(float(confidence), 6),
            "reasons": normalized_reasons,
        }

    @staticmethod
    def _validate_refs(
        raw_refs: Any,
        allowed: set[str],
        field: str,
        *,
        require_non_empty: bool,
    ) -> list[str]:
        if not isinstance(raw_refs, list):
            raise OutputValidationError(f"{field} 必须是数组")
        refs = []
        for index, raw_ref in enumerate(raw_refs):
            if not isinstance(raw_ref, str) or not raw_ref:
                raise OutputValidationError(f"{field}[{index}] 必须是非空字符串")
            if raw_ref not in allowed:
                raise OutputValidationError(f"{field} 包含无效引用 {raw_ref}")
            if raw_ref not in refs:
                refs.append(raw_ref)
        if require_non_empty and not refs:
            raise OutputValidationError(f"{field} 不能为空")
        return refs

    @staticmethod
    def _string(value: Any, field: str, *, allow_empty: bool = False) -> str:
        if not isinstance(value, str):
            raise OutputValidationError(f"{field} 必须是字符串")
        result = value.strip()
        if not allow_empty and not result:
            raise OutputValidationError(f"{field} 不能为空")
        if len(result) > 2000:
            raise OutputValidationError(f"{field} 过长")
        return result

    @staticmethod
    def _finite_number(value: Any, field: str) -> float:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
        ):
            raise OutputValidationError(f"{field} 必须是数字")
        result = float(value)
        if result != result or result in {float("inf"), float("-inf")}:
            raise OutputValidationError(f"{field} 必须是有限数字")
        return result

    @staticmethod
    def _class_label(class_name: str) -> str:
        return {
            "character_ct": "CT角色",
            "character_t": "T角色",
            "enemy": "敌方角色",
            "weapon": "武器",
            "weapon_rifle": "步枪",
            "weapon_pistol": "手枪",
        }.get(class_name.casefold(), class_name)

    @staticmethod
    def _reject_ungrounded_text(value: str, field: str) -> None:
        matched = [term for term in FORBIDDEN_UNGROUNDED_TERMS if term in value]
        if matched:
            raise OutputValidationError(
                f"{field} 包含无证据事件或实体"
            )
        placeholder = [
            term for term in FORBIDDEN_PLACEHOLDER_TERMS if term in value
        ]
        if placeholder:
            raise OutputValidationError(f"{field} 仍包含示例占位文本")
