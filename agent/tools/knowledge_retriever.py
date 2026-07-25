"""Hybrid vector and rule retrieval for the ReelFire knowledge base."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Callable

from agent.retrieval.ollama_topk import (
    build_entry_text,
    cosine_similarity,
    request_embeddings,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_KNOWLEDGE_PATH = ROOT / "agent" / "knowledge" / "media_review_rules.json"
Embedder = Callable[[list[str]], list[list[float]]]


class OllamaEmbedder:
    """Small callable adapter around Ollama's local embedding endpoint."""

    provider = "ollama"

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 180,
    ) -> None:
        self.base_url = base_url or os.getenv(
            "OLLAMA_BASE_URL",
            "http://127.0.0.1:11434",
        )
        self.model = model or os.getenv("OLLAMA_EMBED_MODEL")
        self.timeout = timeout
        if not self.model:
            raise ValueError("Set OLLAMA_EMBED_MODEL or pass an embedding model.")

    def __call__(self, texts: list[str]) -> list[list[float]]:
        return request_embeddings(
            self.base_url,
            self.model,
            texts,
            timeout=self.timeout,
        )


class KnowledgeRetrieverTool:
    """Retrieve rules with vector similarity and deterministic rule matching."""

    name = "knowledge_retriever"

    def __init__(
        self,
        knowledge_path: Path = DEFAULT_KNOWLEDGE_PATH,
        *,
        embedder: Embedder | None = None,
    ) -> None:
        data = json.loads(knowledge_path.read_text(encoding="utf-8"))
        self.knowledge = data["knowledge_base"]
        self.entries: list[dict[str, Any]] = self.knowledge["entries"]
        self.settings = self.knowledge["retrieval"]
        self.embedder = embedder
        self._entry_vectors: list[list[float]] | None = None

    def build_index(self) -> dict[str, Any]:
        """Create and cache the in-memory vector index."""

        if self.embedder is None:
            raise RuntimeError("embedding_not_configured")
        if self._entry_vectors is None:
            vectors = self.embedder(
                [build_entry_text(entry) for entry in self.entries]
            )
            self._validate_vectors(vectors, len(self.entries))
            self._entry_vectors = vectors
        return {
            "document_count": len(self._entry_vectors),
            "vector_dimension": len(self._entry_vectors[0]),
            "metric": self.settings["vector_search"]["metric"],
        }

    def run(
        self,
        visual_summary: dict[str, Any],
        *,
        query: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(visual_summary, dict):
            raise TypeError("visual_summary must be a dictionary")
        metrics = visual_summary.get("metrics")
        classes = visual_summary.get("detected_classes")
        if not isinstance(metrics, dict) or not isinstance(classes, list):
            raise ValueError("visual_summary is missing metrics or detected_classes")

        query_text = query.strip() if isinstance(query, str) else ""
        if not query_text:
            query_text = self.build_query(visual_summary)

        vector_scores: dict[str, float] = {}
        vector_status = "completed"
        degraded_reason: str | None = None
        index_metadata: dict[str, Any] | None = None
        try:
            index_metadata = self.build_index()
            query_vectors = self.embedder([query_text]) if self.embedder else []
            self._validate_vectors(query_vectors, 1)
            query_vector = query_vectors[0]
            for entry, vector in zip(self.entries, self._entry_vectors or []):
                vector_scores[entry["knowledge_id"]] = cosine_similarity(
                    query_vector,
                    vector,
                )
        except Exception as exc:
            vector_status = "degraded"
            degraded_reason = self._degraded_reason(exc)

        class_names = {
            str(item.get("name", "")).casefold()
            for item in classes
            if isinstance(item, dict) and item.get("name")
        }
        normalized_query = query_text.casefold()
        rerank = self.settings["rule_rerank"]
        min_similarity = float(
            self.settings["vector_search"]["min_similarity"]
        )
        ranked = []
        for entry in self.entries:
            reasons = []
            rule = entry["match"]
            similarity = vector_scores.get(entry["knowledge_id"], 0.0)
            score = similarity
            if similarity >= min_similarity:
                reasons.append("vector_similarity")

            if rule.get("always_apply"):
                reasons.append("always_apply")
                score += float(rerank["keyword_match_bonus"])

            configured_classes = {
                str(value).casefold()
                for value in rule.get("detected_classes", [])
            }
            matched_classes = sorted(class_names & configured_classes)
            if matched_classes:
                reasons.extend(f"class:{name}" for name in matched_classes)
                score += float(rerank["class_match_bonus"])

            metric_reasons = self._metric_reasons(
                rule.get("metrics", []),
                metrics,
            )
            if metric_reasons:
                reasons.extend(metric_reasons)
                score += float(rerank["metric_match_bonus"])

            matched_keywords = sorted(
                {
                    str(keyword)
                    for keyword in entry.get("keywords", [])
                    if str(keyword).casefold() in normalized_query
                }
            )
            if matched_keywords:
                reasons.extend(f"keyword:{value}" for value in matched_keywords)
                score += float(rerank["keyword_match_bonus"])

            if reasons:
                ranked.append(
                    {
                        "knowledge_id": entry["knowledge_id"],
                        "category": entry["category"],
                        "title": entry["title"],
                        "review_recommendation": entry[
                            "review_recommendation"
                        ],
                        "summary_guidance": entry["summary_guidance"],
                        "suggestions": list(entry["suggestions"]),
                        "required_evidence_fields": list(
                            entry["required_evidence_fields"]
                        ),
                        "limitations": list(entry["limitations"]),
                        "similarity": round(similarity, 6),
                        "score": round(score, 6),
                        "match_reasons": reasons,
                        "_always_apply": bool(rule.get("always_apply")),
                        "_review_priority": self._review_priority(
                            entry["review_recommendation"]
                        ),
                    }
                )

        ranked.sort(
            key=lambda item: (
                -item["_review_priority"],
                -item["score"],
                -item["similarity"],
                item["knowledge_id"],
            )
        )
        top_k = int(self.settings["vector_search"]["top_k"])
        selected = self._select_with_required_rules(ranked, top_k)
        for rank, result in enumerate(selected, start=1):
            result["rank"] = rank
            result.pop("_always_apply", None)
            result.pop("_review_priority", None)

        return {
            "status": vector_status,
            "strategy": (
                "hybrid_vector_rule"
                if vector_status == "completed"
                else self.settings["fallback"]["mode"]
            ),
            "query": query_text,
            "top_k": top_k,
            "min_similarity": min_similarity,
            "index": index_metadata,
            "degraded_reason": degraded_reason,
            "result_count": len(selected),
            "results": selected,
        }

    @staticmethod
    def build_query(visual_summary: dict[str, Any]) -> str:
        class_names = [
            str(item.get("name"))
            for item in visual_summary.get("detected_classes", [])
            if isinstance(item, dict) and item.get("name")
        ]
        metrics = visual_summary.get("metrics", {})
        classes = "、".join(class_names) if class_names else "无可靠目标"
        return (
            f"媒体审核。检测类别：{classes}；"
            f"总检测数：{metrics.get('total_detections', 0)}；"
            f"最大置信度：{metrics.get('max_confidence', 0)}；"
            f"最大运动强度：{metrics.get('max_motion_score', 0)}；"
            f"最大画面变化：{metrics.get('max_scene_change_score', 0)}；"
            f"最大目标数：{metrics.get('max_object_count', 0)}；"
            "请给出有证据边界的分类、片段和审核规则。"
        )

    @staticmethod
    def _validate_vectors(
        vectors: list[list[float]],
        expected_count: int,
    ) -> None:
        if not isinstance(vectors, list) or len(vectors) != expected_count:
            raise RuntimeError("embedding_count_mismatch")
        if not vectors or not isinstance(vectors[0], list) or not vectors[0]:
            raise RuntimeError("embedding_empty")
        dimension = len(vectors[0])
        if any(
            not isinstance(vector, list)
            or len(vector) != dimension
            or not all(
                not isinstance(value, bool) and isinstance(value, (int, float))
                and math.isfinite(float(value))
                for value in vector
            )
            for vector in vectors
        ):
            raise RuntimeError("embedding_dimension_mismatch")

    @classmethod
    def _metric_reasons(
        cls,
        conditions: list[dict[str, Any]],
        metrics: dict[str, Any],
    ) -> list[str]:
        reasons = []
        for condition in conditions:
            field = condition.get("field")
            if field not in metrics:
                continue
            actual = metrics[field]
            expected = condition.get("value")
            operator = condition.get("operator")
            if cls._compare(actual, operator, expected):
                reasons.append(f"metric:{field}:{operator}:{expected}")
        return reasons

    @staticmethod
    def _compare(actual: Any, operator: Any, expected: Any) -> bool:
        if isinstance(actual, bool) or not isinstance(actual, (int, float)):
            return False
        if isinstance(expected, bool) or not isinstance(expected, (int, float)):
            return False
        operations = {
            "eq": lambda: actual == expected,
            "lt": lambda: actual < expected,
            "lte": lambda: actual <= expected,
            "gt": lambda: actual > expected,
            "gte": lambda: actual >= expected,
        }
        function = operations.get(operator)
        return bool(function and function())

    @staticmethod
    def _select_with_required_rules(
        ranked: list[dict[str, Any]],
        top_k: int,
    ) -> list[dict[str, Any]]:
        required = [item for item in ranked if item["_always_apply"]]
        selected = list(required)
        selected_ids = {item["knowledge_id"] for item in selected}

        def append_first(prefix: str) -> None:
            if len(selected) >= top_k:
                return
            for item in ranked:
                if item["knowledge_id"] in selected_ids:
                    continue
                if any(
                    reason.startswith(prefix)
                    for reason in item["match_reasons"]
                ):
                    selected.append(item)
                    selected_ids.add(item["knowledge_id"])
                    return

        # Reserve room for a directly observed class and a metric rule so that
        # generic always-apply rules cannot crowd out the report's own facts.
        append_first("class:")
        append_first("metric:")
        for item in ranked:
            if len(selected) >= top_k:
                break
            if item["knowledge_id"] not in selected_ids:
                selected.append(item)
                selected_ids.add(item["knowledge_id"])

        selected.sort(
            key=lambda item: (
                -item["_review_priority"],
                -item["score"],
                -item["similarity"],
                item["knowledge_id"],
            )
        )
        return selected[:top_k]

    @staticmethod
    def _review_priority(recommendation: str) -> int:
        return {
            "reject": 3,
            "needs_review": 2,
            "pass": 1,
        }.get(recommendation, 0)

    @staticmethod
    def _degraded_reason(exc: Exception) -> str:
        message = str(exc).strip().replace("\n", " ")
        code = message if message else exc.__class__.__name__
        return f"embedding_unavailable:{code[:160]}"
