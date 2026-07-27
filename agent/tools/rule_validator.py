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
        if not tags:
            tags = self._fallback_tags(visual_summary, evidence_ids)
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

        segment_states = {
            item["review_status"] for item in segment_comments
        }
        if "reject" in segment_states:
            review = {
                "recommendation": "reject",
                "confidence": min(review["confidence"], 0.8),
                "reasons": list(
                    dict.fromkeys(
                        [*review["reasons"], "存在低评分且证据充分的拒绝片段"]
                    )
                ),
            }
        elif "needs_review" in segment_states and review["recommendation"] == "pass":
            review = {
                "recommendation": "needs_review",
                "confidence": min(review["confidence"], 0.6),
                "reasons": list(
                    dict.fromkeys(
                        [*review["reasons"], "至少一个片段需要人工复核"]
                    )
                ),
            }

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

    def _fallback_tags(
        self,
        visual_summary: dict[str, Any],
        evidence_ids: set[str],
    ) -> list[dict[str, Any]]:
        tags = []
        for item in visual_summary.get("detected_classes", []):
            if not isinstance(item, dict):
                continue
            class_name = str(item.get("name", "")).strip()
            if not class_name:
                continue
            refs = [
                ref
                for ref in item.get("evidence_refs", [])
                if isinstance(ref, str) and ref in evidence_ids
            ]
            if not refs:
                continue
            count = item.get("count", 0)
            maximum = item.get("max_confidence", 0.0)
            if isinstance(count, bool) or not isinstance(count, int):
                continue
            if isinstance(maximum, bool) or not isinstance(maximum, (int, float)):
                continue
            tags.append(
                {
                    "name": self._class_label(class_name),
                    "description": (
                        f"目标检测出现 {count} 次，"
                        f"最高置信度 {float(maximum):.3f}；不代表具体游戏事件"
                    ),
                    "evidence_refs": list(dict.fromkeys(refs))[:6],
                }
            )
        return tags

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
            raw_classes = raw.get("detected_classes", [])
            if not isinstance(raw_classes, list):
                raise OutputValidationError(
                    f"{field}.detected_classes 必须是数组"
                )
            max_confidence = 0.0
            classes_by_name: dict[str, dict[str, Any]] = {}
            for class_index, detected in enumerate(raw_classes):
                if not isinstance(detected, dict):
                    raise OutputValidationError(
                        f"{field}.detected_classes[{class_index}] 必须是对象"
                    )
                class_name = self._string(
                    detected.get("name"),
                    f"{field}.detected_classes[{class_index}].name",
                )
                classes_by_name[class_name] = detected
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

            detection_details = self._segment_detection_details(
                raw,
                classes_by_name,
                evidence_ids,
                field,
            )
            if detection_details:
                max_confidence = max(
                    item["max_confidence"] for item in detection_details
                )
            low_confidence = not detection_details or any(
                item["average_confidence"] < 0.5
                or item["max_confidence"] < 0.7
                for item in detection_details
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
            normalized_classes = {
                item["class_name"].casefold() for item in detection_details
            }
            explicit_event = bool(
                normalized_classes
                & {
                    "kill",
                    "kill_feed",
                    "kill_notification",
                    "clutch",
                    "clutch_event",
                }
            )
            if score_value is None:
                score_reason = "CV 未提供可验证的候选排序分"
                action_text = "请对照关键帧和原视频确认是否保留"
                review_status = "needs_review"
            elif score_value >= 0.7:
                score_reason = (
                    f"CV 候选排序分为 {score_value:.3f}，"
                    "该分数不等同于已确认的精彩事件"
                )
                if explicit_event and not low_confidence:
                    action_text = "建议优先检查并确认是否保留"
                    review_status = "pass"
                else:
                    action_text = "建议回看原视频后再决定是否保留"
                    review_status = "needs_review"
            elif score_value >= 0.4:
                score_reason = (
                    f"CV 候选排序分为 {score_value:.3f}，"
                    "该分数不等同于已确认的精彩事件"
                )
                action_text = "建议结合关键帧和原视频确认是否保留"
                review_status = "needs_review"
            elif score_value < 0.25 and not low_confidence:
                score_reason = f"CV 候选排序分为 {score_value:.3f}"
                action_text = "候选优先级较低且检测稳定，建议人工确认后移出候选"
                review_status = "reject"
            else:
                score_reason = f"CV 候选排序分为 {score_value:.3f}"
                action_text = "候选优先级较低，请人工确认是否保留"
                review_status = "needs_review"

            keyframe_refs = [
                f"ev:keyframe:{source_id}"
                for source_id in raw.get("source_keyframes", [])
                if f"ev:keyframe:{source_id}" in evidence_ids
            ]
            detection_refs = list(
                dict.fromkeys(
                    ref
                    for item in detection_details
                    for ref in item["evidence_refs"]
                    if ref.startswith("ev:detection:")
                )
            )
            refs.extend(keyframe_refs)
            refs.extend(detection_refs)
            boundary = self._boundary_suggestion(
                start,
                end,
                detection_details,
            )
            highlight_type = self._highlight_type(
                raw.get("reason"),
                normalized_classes,
            )
            trigger_rule = self._safe_trigger_rule(
                raw.get("reason"),
                explicit_event=explicit_event,
            )

            description_text = self._team_engagement_comment(
                detection_details,
                trigger_rule=trigger_rule,
                segment_id=segment_id,
            ) or self._segment_description_text(
                detection_details,
                segment_id=segment_id,
            )
            event_text = self._gameplay_event_comment(
                detection_details,
                segment_id=segment_id,
            )
            tone_text = self._comment_tone(
                score_value,
                has_explicit_event=explicit_event,
                segment_id=segment_id,
            )
            evidence_scope = (
                ""
                if explicit_event
                else "具体事件与本人/队友归属还要结合原片确认。"
            )

            comments.append(
                {
                    "segment_id": segment_id,
                    "title": f"片段 {index + 1}",
                    "comment": (
                        f"{time_text}：{description_text}{event_text}"
                        f"{tone_text}{evidence_scope}"
                    ),
                    "score_reason": score_reason,
                    "review_status": review_status,
                    "action_recommendation": {
                        "pass": "adopt",
                        "needs_review": "needs_review",
                        "reject": "reject",
                    }[review_status],
                    "explanation": {
                        "highlight_type": highlight_type,
                        "trigger_rule": trigger_rule,
                        "time_range": {
                            "start": round(start, 6),
                            "end": round(end, 6),
                        },
                        "detections": detection_details,
                        "keyframe_refs": keyframe_refs,
                        "detection_box_refs": detection_refs,
                    },
                    "boundary_suggestion": boundary,
                    "evidence_refs": list(dict.fromkeys(refs))[:20],
                }
            )
        return comments

    def _segment_detection_details(
        self,
        segment: dict[str, Any],
        classes_by_name: dict[str, dict[str, Any]],
        evidence_ids: set[str],
        field: str,
    ) -> list[dict[str, Any]]:
        raw_details = segment.get("detections_summary", [])
        if not isinstance(raw_details, list):
            raise OutputValidationError(f"{field}.detections_summary 必须是数组")
        details = []
        for index, raw in enumerate(raw_details):
            owner = f"{field}.detections_summary[{index}]"
            if not isinstance(raw, dict):
                raise OutputValidationError(f"{owner} 必须是对象")
            class_name = self._string(raw.get("class"), f"{owner}.class")
            average = self._bounded_confidence(
                raw.get("confidence", 0),
                f"{owner}.confidence",
            )
            maximum = self._bounded_confidence(
                raw.get("confidence_max", average),
                f"{owner}.confidence_max",
            )
            observed = raw.get("detection_count", 0)
            if isinstance(observed, bool) or not isinstance(observed, int) or observed < 0:
                raise OutputValidationError(
                    f"{owner}.detection_count 必须是非负整数"
                )
            consecutive = raw.get("consecutive_frame_count")
            if (
                isinstance(consecutive, bool)
                or consecutive is not None
                and (not isinstance(consecutive, int) or consecutive < 0)
            ):
                raise OutputValidationError(
                    f"{owner}.consecutive_frame_count 必须是非负整数或 null"
                )
            first_seen = self._finite_number(
                raw.get("first_seen"),
                f"{owner}.first_seen",
            )
            last_seen = self._finite_number(
                raw.get("last_seen"),
                f"{owner}.last_seen",
            )
            class_refs = classes_by_name.get(class_name, {}).get(
                "evidence_refs",
                [],
            )
            refs = [
                ref
                for ref in class_refs
                if isinstance(ref, str) and ref in evidence_ids
            ]
            details.append(
                {
                    "class_name": class_name,
                    "track_id": raw.get("track_id"),
                    "first_seen": round(first_seen, 6),
                    "last_seen": round(last_seen, 6),
                    "observed_frame_count": observed,
                    "consecutive_frame_count": consecutive,
                    "average_confidence": round(average, 6),
                    "max_confidence": round(maximum, 6),
                    "evidence_refs": list(dict.fromkeys(refs)),
                }
            )

        if details:
            return details

        for class_name, raw in classes_by_name.items():
            refs = [
                ref
                for ref in raw.get("evidence_refs", [])
                if isinstance(ref, str) and ref in evidence_ids
            ]
            first_seen = raw.get("first_seen")
            last_seen = raw.get("last_seen")
            details.append(
                {
                    "class_name": class_name,
                    "track_id": None,
                    "first_seen": (
                        round(float(first_seen), 6)
                        if isinstance(first_seen, (int, float))
                        and not isinstance(first_seen, bool)
                        else None
                    ),
                    "last_seen": (
                        round(float(last_seen), 6)
                        if isinstance(last_seen, (int, float))
                        and not isinstance(last_seen, bool)
                        else None
                    ),
                    "observed_frame_count": max(
                        0,
                        int(raw.get("detection_count", 0)),
                    ),
                    "consecutive_frame_count": raw.get(
                        "consecutive_frame_count"
                    ),
                    "average_confidence": round(
                        float(raw.get("average_confidence", 0)),
                        6,
                    ),
                    "max_confidence": round(
                        float(raw.get("max_confidence", 0)),
                        6,
                    ),
                    "evidence_refs": list(dict.fromkeys(refs)),
                }
            )
        return details

    @staticmethod
    def _boundary_suggestion(
        start: float,
        end: float,
        detections: list[dict[str, Any]],
    ) -> dict[str, Any]:
        observed = [
            item
            for item in detections
            if item.get("first_seen") is not None
            and item.get("last_seen") is not None
        ]
        if not observed:
            return {
                "action": "manual_review",
                "suggested_start": None,
                "suggested_end": None,
                "reason": "缺少可验证的目标出现时间，无法自动建议边界",
            }
        first_seen = min(float(item["first_seen"]) for item in observed)
        last_seen = max(float(item["last_seen"]) for item in observed)
        review_start = first_seen - start <= 0.25
        review_end = end - last_seen <= 0.25
        if review_start and review_end:
            action = "review_both"
            reason = "目标证据同时接近片段起止边界，建议人工检查前后缓冲"
        elif review_start:
            action = "review_start"
            reason = "目标证据接近片段起点，建议人工检查前置缓冲"
        elif review_end:
            action = "review_end"
            reason = "目标证据接近片段终点，建议人工检查后置缓冲"
        else:
            action = "keep"
            reason = "目标证据位于片段边界内，当前边界可保留"
        return {
            "action": action,
            "suggested_start": round(start, 6),
            "suggested_end": round(end, 6),
            "reason": reason,
        }

    @staticmethod
    def _segment_description_text(
        detections: list[dict[str, Any]],
        *,
        segment_id: str,
    ) -> str:
        if not detections:
            return "目前没有稳定目标可用于形成画面描述。"
        event_classes = {
            "kill",
            "kill_feed",
            "kill_notification",
            "clutch",
            "clutch_event",
        }
        visual_detections = [
            item
            for item in detections
            if str(item.get("class_name", "")).casefold() not in event_classes
        ]
        if not visual_detections:
            return "画面中出现了关键事件。"
        primary = max(
            visual_detections,
            key=lambda item: (
                int(item.get("observed_frame_count", 0)),
                float(item.get("max_confidence", 0.0)),
            ),
        )
        label = RuleValidatorTool._comment_class_label(
            str(primary["class_name"])
        )
        labels = list(
            dict.fromkeys(
                RuleValidatorTool._comment_class_label(str(item["class_name"]))
                for item in visual_detections
            )
        )
        if len(labels) == 1:
            visible_targets = labels[0]
        else:
            visible_targets = "、".join(labels[:-1]) + "和" + labels[-1]
        if primary.get("first_seen") is None or primary.get("last_seen") is None:
            return RuleValidatorTool._select_comment_variant(
                segment_id,
                (
                    f"画面中出现了{visible_targets}。",
                    f"这一段能看到{visible_targets}。",
                    f"画面内容以{visible_targets}为主。",
                ),
            )
        time_range = (
            f"{float(primary['first_seen']):.1f}—"
            f"{float(primary['last_seen']):.1f}秒"
        )
        return RuleValidatorTool._select_comment_variant(
            segment_id,
            (
                f"画面中出现了{visible_targets}，其中{label}主要出现在 {time_range}。",
                f"这一段能看到{visible_targets}，{label}集中出现在 {time_range}。",
                f"画面内容以{visible_targets}为主，{label}在 {time_range}较为集中。",
            ),
        )

    @staticmethod
    def _team_engagement_comment(
        detections: list[dict[str, Any]],
        *,
        trigger_rule: str,
        segment_id: str,
    ) -> str:
        ct_tracks = RuleValidatorTool._team_tracks(
            detections,
            {"character_ct"},
        )
        t_tracks = RuleValidatorTool._team_tracks(
            detections,
            {"character_t"},
        )
        if not ct_tracks or not t_tracks:
            return ""

        ct_count = len(ct_tracks)
        t_count = len(t_tracks)
        simultaneous = RuleValidatorTool._simultaneous_window(
            list(ct_tracks.values()),
            list(t_tracks.values()),
        )
        time_text = (
            f"{simultaneous[0]:.1f}—{simultaneous[1]:.1f}秒，"
            if simultaneous is not None
            else ""
        )
        scene = (
            "交火"
            if trigger_rule.startswith("enemy_engagement")
            else "对峙"
        )
        fact_text = (
            f"{time_text}{ct_count}名CT与{t_count}名T同时出现在画面中，"
            f"形成{ct_count}打{t_count}的{scene}局面。"
        )
        if ct_count == t_count:
            reactions = (
                "双方人数相当，这波局面一下就紧起来了！",
                "人数完全对得上，这一段对抗感直接拉满！",
                "双方同屏人数相同，这波很有看点！",
            )
        elif ct_count > t_count:
            reactions = (
                "就当前画面来看，CT一侧人更多，T这波压力不小！",
                "画面里CT人数更多，这波局面相当紧张！",
                "当前同屏人数偏向CT一侧，这一段对抗感很强！",
            )
        else:
            reactions = (
                "就当前画面来看，T一侧人更多，CT这波压力不小！",
                "画面里T人数更多，这波局面相当紧张！",
                "当前同屏人数偏向T一侧，这一段对抗感很强！",
            )
        return fact_text + RuleValidatorTool._select_comment_variant(
            segment_id,
            reactions,
        )

    @staticmethod
    def _team_tracks(
        detections: list[dict[str, Any]],
        class_names: set[str],
    ) -> dict[tuple[Any, ...], dict[str, Any]]:
        tracks: dict[tuple[Any, ...], dict[str, Any]] = {}
        for index, item in enumerate(detections):
            class_name = str(item.get("class_name", "")).casefold()
            if class_name not in class_names:
                continue
            track_id = item.get("track_id")
            key = (
                (class_name, "track", str(track_id))
                if track_id is not None
                else (class_name, "row", index)
            )
            tracks[key] = item
        return tracks

    @staticmethod
    def _simultaneous_window(
        left: list[dict[str, Any]],
        right: list[dict[str, Any]],
    ) -> tuple[float, float] | None:
        left_start = [
            float(item["first_seen"])
            for item in left
            if item.get("first_seen") is not None
        ]
        left_end = [
            float(item["last_seen"])
            for item in left
            if item.get("last_seen") is not None
        ]
        right_start = [
            float(item["first_seen"])
            for item in right
            if item.get("first_seen") is not None
        ]
        right_end = [
            float(item["last_seen"])
            for item in right
            if item.get("last_seen") is not None
        ]
        if not all((left_start, left_end, right_start, right_end)):
            return None
        start = max(min(left_start), min(right_start))
        end = min(max(left_end), max(right_end))
        return (start, end) if start <= end else None

    @staticmethod
    def _gameplay_event_comment(
        detections: list[dict[str, Any]],
        *,
        segment_id: str,
    ) -> str:
        kill_classes = {"kill", "kill_feed", "kill_notification"}
        kill_events_by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
        for item in detections:
            class_name = str(item.get("class_name", "")).casefold()
            if class_name not in kill_classes:
                continue
            track_id = item.get("track_id")
            key = (
                ("track", str(track_id))
                if track_id is not None
                else ("time", class_name, item.get("first_seen"))
            )
            kill_events_by_key[key] = item
        kill_events = list(kill_events_by_key.values())
        if kill_events:
            event_times = [
                float(item["first_seen"])
                for item in kill_events
                if item.get("first_seen") is not None
            ]
            count = len(kill_events)
            if count >= 2:
                if event_times:
                    time_text = (
                        f"{min(event_times):.1f}—{max(event_times):.1f}秒"
                        if len(set(event_times)) > 1
                        else f"{event_times[0]:.1f}秒附近"
                    )
                    if count == 2:
                        return RuleValidatorTool._select_comment_variant(
                            f"{segment_id}:double-kill",
                            (
                                f"{time_text}连续出现2次击杀提示，连杀节奏直接拉满，nice！",
                                f"{time_text}接连出现2次击杀提示，这波连杀很顺，nice！",
                                f"{time_text}两次击杀提示紧接着出现，这波连杀节奏完全没断，漂亮！",
                            ),
                        )
                    return RuleValidatorTool._select_comment_variant(
                        f"{segment_id}:multi-kill",
                        (
                            f"{time_text}接连出现{count}次击杀提示，一波连杀把节奏推到顶，太炸了！",
                            f"{time_text}{count}次击杀提示连续亮起，这段真的拉满了！",
                            f"{time_text}连续{count}次击杀提示，连杀来得又快又密，nice！",
                        ),
                    )
                return RuleValidatorTool._select_comment_variant(
                    f"{segment_id}:untimed-multi-kill",
                    (
                        f"画面连续出现{count}次击杀提示，连杀节奏直接拉满，nice！",
                        f"画面接连出现{count}次击杀提示，这波连杀很顺！",
                        f"{count}次击杀提示连续亮起，节奏完全没断，漂亮！",
                    ),
                )
            if event_times:
                time_text = f"{event_times[0]:.1f}秒"
                return RuleValidatorTool._select_comment_variant(
                    f"{segment_id}:single-kill",
                    (
                        f"{time_text}出现击杀提示，nice，这波很干净！",
                        f"{time_text}击杀提示亮起，这一下很果断，nice！",
                        f"{time_text}出现击杀信息，nice，节奏瞬间被带起来了！",
                    ),
                )
            return RuleValidatorTool._select_comment_variant(
                f"{segment_id}:untimed-single-kill",
                (
                    "画面出现击杀提示，nice，这波很干净！",
                    "击杀提示亮起，这一下很果断，nice！",
                    "画面出现击杀信息，nice，节奏瞬间被带起来了！",
                ),
            )

        clutch_events = [
            item
            for item in detections
            if str(item.get("class_name", "")).casefold()
            in {"clutch", "clutch_event"}
        ]
        if clutch_events:
            first_seen = clutch_events[0].get("first_seen")
            if first_seen is not None:
                time_text = f"{float(first_seen):.1f}秒"
                return RuleValidatorTool._select_comment_variant(
                    f"{segment_id}:clutch",
                    (
                        f"{time_text}出现残局事件，压力感拉满，太极限了！",
                        f"{time_text}进入残局节点，这一波张力直接拉满！",
                        f"{time_text}出现残局信息，极限感一下就出来了！",
                    ),
                )
            return RuleValidatorTool._select_comment_variant(
                f"{segment_id}:untimed-clutch",
                (
                    "画面出现残局事件，压力感拉满，太极限了！",
                    "画面进入残局节点，这一波张力直接拉满！",
                    "画面出现残局信息，极限感一下就出来了！",
                ),
            )
        return ""

    @staticmethod
    def _comment_tone(
        score: float | None,
        *,
        has_explicit_event: bool,
        segment_id: str,
    ) -> str:
        if has_explicit_event:
            return ""
        if score is None:
            return RuleValidatorTool._select_comment_variant(
                f"{segment_id}:unscored",
                (
                    "画面信息比较集中，",
                    "主要目标比较清楚，",
                    "内容脉络比较明确，",
                ),
            )
        if score >= 0.7:
            return RuleValidatorTool._select_comment_variant(
                f"{segment_id}:high-score",
                (
                    "这段画面信息密度很高，节奏一下就起来了，nice！",
                    "这一段的节奏很紧，画面也够集中，很有看点！",
                    "这段张力不错，节奏拉满，值得重点看看！",
                ),
            )
        if score >= 0.4:
            return RuleValidatorTool._select_comment_variant(
                f"{segment_id}:medium-score",
                (
                    "这一段有一定看点，节奏还不错。",
                    "画面内容比较集中，整体节奏顺畅。",
                    "这一段状态在线，稍微润色会更有冲击力。",
                ),
            )
        return RuleValidatorTool._select_comment_variant(
            f"{segment_id}:low-score",
            (
                "这一段节奏偏平，亮点还不够突出。",
                "画面信息量不多，整体更像过渡段。",
                "这一段起伏较小，冲击力暂时弱一些。",
            ),
        )

    @staticmethod
    def _select_comment_variant(seed: str, options: tuple[str, ...]) -> str:
        index = sum((position + 1) * ord(char) for position, char in enumerate(seed))
        return options[index % len(options)]

    @staticmethod
    def _safe_trigger_rule(reason: Any, *, explicit_event: bool) -> str:
        normalized = str(reason or "").strip().casefold()
        if not normalized:
            return "CV 未提供触发规则"
        if normalized.startswith("enemy_engagement"):
            if explicit_event and "kill" in normalized:
                return normalized
            return "enemy_engagement"
        return normalized

    @staticmethod
    def _highlight_type(reason: Any, classes: set[str]) -> str:
        normalized_reason = str(reason or "").strip().casefold()
        kill_classes = {"kill", "kill_feed", "kill_notification"}
        if classes & kill_classes and "kill" in normalized_reason:
            return "击杀事件候选"
        if classes & {"clutch", "clutch_event"}:
            return "残局事件候选"
        if normalized_reason.startswith("enemy_engagement"):
            return "角色目标出现候选"
        return {
            "high_motion": "高运动强度候选",
            "scene_change": "场景变化候选",
        }.get(normalized_reason, "未分类高光候选")

    def _bounded_confidence(self, value: Any, field: str) -> float:
        result = self._finite_number(value, field)
        if not 0 <= result <= 1:
            raise OutputValidationError(f"{field} 必须位于 0 到 1")
        return result

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
    def _comment_class_label(class_name: str) -> str:
        return {
            "person": "人物",
            "car": "车辆",
            "kill": "击杀事件",
            "kill_feed": "击杀提示",
            "kill_notification": "击杀提示",
            "clutch": "残局事件",
            "clutch_event": "残局事件",
            "rifle": "步枪",
            "pistol": "手枪",
            "smg": "冲锋枪",
            "shotgun": "霰弹枪",
            "sniper": "狙击枪",
            "awp": "AWP",
            "ak47": "AK-47",
            "m4a1": "M4A1",
            "weapon_awp": "AWP",
            "weapon_ak47": "AK-47",
            "weapon_m4a1": "M4A1",
            "weapon_smg": "冲锋枪",
            "weapon_shotgun": "霰弹枪",
            "weapon_sniper": "狙击枪",
        }.get(
            class_name.casefold(),
            RuleValidatorTool._class_label(class_name),
        )

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
