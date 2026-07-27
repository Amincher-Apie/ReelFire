"""Dify Cloud Chatflow adapter using an API key from the environment."""

from __future__ import annotations

import json
import logging
import os
import random
import re
import time
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from agent.providers.ollama import DEFAULT_PROMPT_PATH, ModelProviderError


LOGGER = logging.getLogger(__name__)
MAX_PROMPT_KEYFRAMES = 24
MAX_PROMPT_EVIDENCE_REFS = 320


class DifyChatClient:
    """Generate a business draft through a Dify Chatflow blocking API."""

    provider_type = "dify"

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        *,
        user: str | None = None,
        model_label: str | None = None,
        prompt_path: Path = DEFAULT_PROMPT_PATH,
        timeout: float = 120,
        max_attempts: int | None = None,
        retry_base_seconds: float | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        jitter_fn: Callable[[], float] = random.random,
    ) -> None:
        self.base_url = base_url or os.getenv(
            "DIFY_BASE_URL",
            "https://api.dify.ai",
        )
        self.api_key = api_key if api_key is not None else os.getenv(
            "DIFY_API_KEY",
            "",
        )
        self.user = user or os.getenv("DIFY_USER", "reelfire-demo")
        self.model = model_label or os.getenv(
            "DIFY_MODEL_LABEL",
            "reelfire-chatflow-v1.0.0",
        )
        self.timeout = timeout
        self.max_attempts = (
            max_attempts
            if max_attempts is not None
            else self._positive_int_env("DIFY_MAX_ATTEMPTS", 3)
        )
        if self.max_attempts < 1:
            raise ValueError("DIFY_MAX_ATTEMPTS must be at least 1.")
        self.retry_base_seconds = (
            retry_base_seconds
            if retry_base_seconds is not None
            else self._non_negative_float_env("DIFY_RETRY_BASE_SECONDS", 0.5)
        )
        if self.retry_base_seconds < 0:
            raise ValueError("DIFY_RETRY_BASE_SECONDS cannot be negative.")
        self._sleep = sleep_fn
        self._jitter = jitter_fn
        self.last_attempt_count = 0
        self.last_request_id: str | None = None
        self.prompt_template = prompt_path.read_text(encoding="utf-8")

    def generate(
        self,
        job_id: str,
        visual_summary: dict[str, Any],
        knowledge_context: dict[str, Any],
    ) -> dict[str, Any]:
        if not self.api_key.strip():
            raise ModelProviderError(
                "Set DIFY_API_KEY in the local .env file before online testing.",
                provider_code="dify_not_configured",
                attempt_count=0,
            )
        prompt = self._render_prompt(
            job_id,
            visual_summary,
            knowledge_context,
        )
        endpoint = self.api_endpoint("chat-messages")
        request = Request(
            endpoint,
            data=json.dumps(
                {
                    "inputs": {},
                    "query": prompt,
                    "response_mode": "blocking",
                    "conversation_id": "",
                    "user": self.user,
                },
                ensure_ascii=False,
            ).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": (
                    "ReelFire/1.0 "
                    "(+https://github.com/Amincher-Apie/ReelFire)"
                ),
            },
            method="POST",
        )
        payload = self._request_json(request)

        answer = payload.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            raise self._contract_error("Dify returned an empty answer")
        try:
            return self._parse_answer(answer)
        except ModelProviderError as exc:
            exc.attempt_count = self.last_attempt_count
            exc.request_id = self.last_request_id
            raise

    def get_app_info(self) -> dict[str, Any]:
        """Verify the app key and return non-secret Dify app metadata."""

        if not self.api_key.strip():
            raise ModelProviderError(
                "Set DIFY_API_KEY in the local .env file before online testing.",
                provider_code="dify_not_configured",
                attempt_count=0,
            )
        request = Request(
            self.api_endpoint("info"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
                "User-Agent": (
                    "ReelFire/1.0 "
                    "(+https://github.com/Amincher-Apie/ReelFire)"
                ),
            },
            method="GET",
        )
        payload = self._request_json(request)
        if not isinstance(payload, dict):
            raise self._contract_error("Dify app info must be an object")
        return payload

    def _request_json(self, request: Request) -> dict[str, Any]:
        """Execute one Dify request with bounded transient-error retries."""

        self.last_attempt_count = 0
        self.last_request_id = None
        endpoint_label = self._endpoint_label(request)
        for attempt in range(1, self.max_attempts + 1):
            self.last_attempt_count = attempt
            started = time.monotonic()
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    self.last_request_id = self._request_id(response)
                    try:
                        payload = json.load(response)
                    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                        raise self._contract_error(
                            "Dify returned an invalid JSON response"
                        ) from exc
            except HTTPError as exc:
                self.last_request_id = self._request_id(exc)
                error = self._http_error(exc, attempt)
                LOGGER.warning(
                    "dify_request_failed endpoint=%s attempt=%d/%d "
                    "duration_ms=%d exception_type=%s status=%d "
                    "provider_code=%s retryable=%s request_id=%s",
                    endpoint_label,
                    attempt,
                    self.max_attempts,
                    int((time.monotonic() - started) * 1000),
                    type(exc).__name__,
                    int(exc.code),
                    error.provider_code,
                    error.retryable,
                    self.last_request_id or "-",
                )
                if error.retryable and attempt < self.max_attempts:
                    self._wait_before_retry(attempt)
                    continue
                raise error from exc
            except (URLError, TimeoutError) as exc:
                reason = getattr(exc, "reason", None)
                timed_out = isinstance(exc, TimeoutError) or isinstance(
                    reason,
                    TimeoutError,
                )
                errno = getattr(reason, "errno", None)
                LOGGER.warning(
                    "dify_request_failed endpoint=%s attempt=%d/%d "
                    "duration_ms=%d exception_type=%s reason_type=%s "
                    "errno=%s timeout=%s retryable=true",
                    endpoint_label,
                    attempt,
                    self.max_attempts,
                    int((time.monotonic() - started) * 1000),
                    type(exc).__name__,
                    type(reason).__name__ if reason is not None else "none",
                    errno if isinstance(errno, int) else "-",
                    str(timed_out).lower(),
                )
                error = ModelProviderError(
                    "Dify request timed out"
                    if timed_out
                    else "Dify network request failed",
                    provider_code=(
                        "dify_timeout" if timed_out else "dify_network_error"
                    ),
                    retryable=True,
                    attempt_count=attempt,
                )
                if attempt < self.max_attempts:
                    self._wait_before_retry(attempt)
                    continue
                raise error from exc
            if not isinstance(payload, dict):
                raise self._contract_error("Dify response must be an object")
            LOGGER.info(
                "dify_request_succeeded endpoint=%s attempt=%d/%d "
                "duration_ms=%d request_id=%s",
                endpoint_label,
                attempt,
                self.max_attempts,
                int((time.monotonic() - started) * 1000),
                self.last_request_id or "-",
            )
            return payload
        raise AssertionError("unreachable Dify retry state")

    def _http_error(self, exc: HTTPError, attempt: int) -> ModelProviderError:
        status = int(exc.code)
        if status in {401, 403}:
            return ModelProviderError(
                f"Dify authentication failed (HTTP {status})",
                provider_code="dify_auth_failed",
                status_code=status,
                attempt_count=attempt,
                request_id=self.last_request_id,
            )
        retryable = status == 429 or 500 <= status < 600
        provider_code = (
            "dify_rate_limited"
            if status == 429
            else "dify_server_error"
            if 500 <= status < 600
            else "dify_request_rejected"
        )
        detail = self._safe_detail(exc.read().decode("utf-8", errors="replace"))
        message = f"Dify returned HTTP {status}"
        if detail:
            message = f"{message}: {detail}"
        return ModelProviderError(
            message,
            provider_code=provider_code,
            retryable=retryable,
            status_code=status,
            attempt_count=attempt,
            request_id=self.last_request_id,
        )

    def _contract_error(self, message: str) -> ModelProviderError:
        return ModelProviderError(
            message,
            provider_code="dify_contract_error",
            attempt_count=self.last_attempt_count,
            request_id=self.last_request_id,
        )

    def _wait_before_retry(self, attempt: int) -> None:
        delay = self.retry_base_seconds * (2 ** (attempt - 1))
        delay *= 0.5 + max(0.0, min(1.0, float(self._jitter())))
        self._sleep(delay)

    def _safe_detail(self, detail: str) -> str:
        normalized = detail.replace("\r", " ").replace("\n", " ").strip()
        if self.api_key:
            normalized = normalized.replace(self.api_key, "[redacted]")
        normalized = re.sub(
            r"(?i)bearer\s+[a-z0-9._~+\-/=]+",
            "Bearer [redacted]",
            normalized,
        )
        normalized = re.sub(
            r"(?i)\b(?:app|sk)-[a-z0-9_-]{8,}\b",
            "[redacted]",
            normalized,
        )
        return normalized[:300]

    @staticmethod
    def _request_id(response: Any) -> str | None:
        headers = getattr(response, "headers", None)
        if headers is None:
            return None
        for name in ("x-request-id", "request-id", "x-amzn-requestid"):
            value = headers.get(name)
            if value:
                return str(value)[:200]
        return None

    @staticmethod
    def _endpoint_label(request: Request) -> str:
        url = str(getattr(request, "full_url", "")).rstrip("/")
        operation = "info" if url.endswith("/info") else "chat-messages"
        return f"{request.get_method().lower()}:{operation}"

    @staticmethod
    def _positive_int_env(name: str, default: int) -> int:
        value = os.getenv(name)
        try:
            return int(value) if value is not None else default
        except ValueError as exc:
            raise ValueError(f"{name} must be an integer.") from exc

    @staticmethod
    def _non_negative_float_env(name: str, default: float) -> float:
        value = os.getenv(name)
        try:
            return float(value) if value is not None else default
        except ValueError as exc:
            raise ValueError(f"{name} must be a number.") from exc

    def api_endpoint(self, path: str) -> str:
        """Build a Dify API endpoint from a host with or without ``/v1``."""

        base_url = self.base_url.rstrip("/")
        api_base = base_url if base_url.endswith("/v1") else f"{base_url}/v1"
        return f"{api_base}/{path.lstrip('/')}"

    def _render_prompt(
        self,
        job_id: str,
        visual_summary: dict[str, Any],
        knowledge_context: dict[str, Any],
    ) -> str:
        visual_summary = self._compact_visual_summary(visual_summary)
        evidence_ids = [
            str(item["ref_id"])
            for item in visual_summary.get("evidence_refs", [])
            if isinstance(item, dict) and item.get("ref_id")
        ]
        knowledge_ids = [
            str(item["knowledge_id"])
            for item in knowledge_context.get("results", [])
            if isinstance(item, dict) and item.get("knowledge_id")
        ]
        prompt = (
            self.prompt_template.replace("{{job_id}}", job_id)
            .replace(
                "{{visual_summary_json}}",
                json.dumps(
                    visual_summary,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
            .replace(
                "{{knowledge_context_json}}",
                json.dumps(
                    knowledge_context,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
        )
        prompt += (
            "\n\n只能从下列白名单复制引用，不得创建新编号：\n"
            f"evidence_ref 白名单：{json.dumps(evidence_ids, ensure_ascii=False)}\n"
            f"knowledge_id 白名单：{json.dumps(knowledge_ids, ensure_ascii=False)}\n"
        )
        return prompt

    @classmethod
    def _compact_visual_summary(
        cls,
        visual_summary: dict[str, Any],
    ) -> dict[str, Any]:
        """Keep model context bounded while preserving every segment summary."""

        compact = {
            key: visual_summary[key]
            for key in (
                "schema_version",
                "job_id",
                "provider",
                "duration",
                "total_sampled_frames",
                "source_frame_count",
                "keyframe_count",
                "segment_count",
                "metrics",
            )
            if key in visual_summary
        }
        compact["detected_classes"] = [
            cls._compact_detected_class(item, include_refs=True)
            for item in visual_summary.get("detected_classes", [])
            if isinstance(item, dict)
        ]

        keyframes = [
            item
            for item in visual_summary.get("keyframes", [])
            if isinstance(item, dict)
        ]
        keyframes.sort(
            key=lambda item: cls._numeric_score(
                item.get("highlight_score"),
            ),
            reverse=True,
        )
        compact["keyframes"] = [
            {
                key: item[key]
                for key in (
                    "id",
                    "timestamp",
                    "highlight_score",
                    "evidence_refs",
                )
                if key in item
            }
            for item in keyframes[:MAX_PROMPT_KEYFRAMES]
        ]

        compact["segments"] = [
            cls._compact_segment(item)
            for item in visual_summary.get("segments", [])
            if isinstance(item, dict)
        ]

        baseline = visual_summary.get("rule_baseline")
        if isinstance(baseline, dict):
            segment_tags = baseline.get("segment_tags")
            if isinstance(segment_tags, dict):
                compact["rule_baseline"] = {
                    "segment_tags": {
                        key: segment_tags[key]
                        for key in ("total_tags", "summary", "ai_cover_prompt")
                        if key in segment_tags
                    }
                }

        raw_evidence = [
            item
            for item in visual_summary.get("evidence_refs", [])
            if isinstance(item, dict) and item.get("ref_id")
        ]
        evidence_by_id = {
            str(item["ref_id"]): item for item in raw_evidence
        }
        referenced_ids = cls._collect_evidence_ids(compact)
        for item in raw_evidence:
            ref_id = str(item["ref_id"])
            if ref_id not in referenced_ids:
                referenced_ids.append(ref_id)
            if len(referenced_ids) >= MAX_PROMPT_EVIDENCE_REFS:
                break
        compact["evidence_refs"] = [
            {
                key: evidence_by_id[ref_id][key]
                for key in ("ref_id", "type", "source_id")
                if key in evidence_by_id[ref_id]
            }
            for ref_id in referenced_ids[:MAX_PROMPT_EVIDENCE_REFS]
            if ref_id in evidence_by_id
        ]
        return compact

    @staticmethod
    def _numeric_score(value: Any) -> float:
        if isinstance(value, bool):
            return 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _compact_segment(item: dict[str, Any]) -> dict[str, Any]:
        compact = {
            key: item[key]
            for key in (
                "id",
                "order",
                "start",
                "end",
                "score",
                "reason",
                "peak_enemy_count",
                "enemy_classes_in_segment",
            )
            if key in item
        }
        compact["detected_classes"] = [
            DifyChatClient._compact_detected_class(detected)
            for detected in item.get("detected_classes", [])[:8]
            if isinstance(detected, dict)
        ]
        evidence_refs = item.get("evidence_refs")
        if isinstance(evidence_refs, list):
            segment_refs = [
                value
                for value in evidence_refs
                if isinstance(value, str) and value.startswith("ev:segment:")
            ]
            other_refs = [
                value
                for value in evidence_refs
                if isinstance(value, str) and value not in segment_refs
            ]
            compact["evidence_refs"] = (segment_refs + other_refs)[:4]

        detections = item.get("detections_summary")
        if isinstance(detections, list):
            compact["detections_summary"] = [
                {
                    key: detection[key]
                    for key in (
                        "class",
                        "confidence",
                        "confidence_max",
                        "detection_count",
                        "first_seen",
                        "last_seen",
                    )
                    if key in detection
                }
                for detection in detections[:8]
                if isinstance(detection, dict)
            ]
        return compact

    @staticmethod
    def _compact_detected_class(
        item: dict[str, Any],
        *,
        include_refs: bool = False,
    ) -> dict[str, Any]:
        compact = {
            key: item[key]
            for key in (
                "name",
                "count",
                "track_count",
                "max_confidence",
            )
            if key in item
        }
        if include_refs and isinstance(item.get("evidence_refs"), list):
            compact["evidence_refs"] = item["evidence_refs"][:4]
        return compact

    @staticmethod
    def _collect_evidence_ids(value: Any) -> list[str]:
        collected: list[str] = []

        def visit(candidate: Any) -> None:
            if isinstance(candidate, dict):
                for nested in candidate.values():
                    visit(nested)
            elif isinstance(candidate, list):
                for nested in candidate:
                    visit(nested)
            elif (
                isinstance(candidate, str)
                and candidate.startswith("ev:")
                and candidate not in collected
            ):
                collected.append(candidate)

        visit(value)
        return collected

    @staticmethod
    def _parse_answer(answer: str) -> dict[str, Any]:
        normalized = answer.strip()
        # Reasoning-capable models may expose their internal reasoning in the
        # blocking API even though Dify's preview renders it separately.  The
        # business contract starts after the closed think block.
        normalized = re.sub(
            r"^\s*<think>.*?</think>\s*",
            "",
            normalized,
            count=1,
            flags=re.DOTALL | re.IGNORECASE,
        )
        fenced = re.fullmatch(
            r"```(?:json)?\s*(.*?)\s*```",
            normalized,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if fenced:
            normalized = fenced.group(1)
        try:
            result = json.loads(normalized)
        except json.JSONDecodeError as exc:
            raise ModelProviderError(
                "Dify returned invalid JSON",
                provider_code="dify_contract_error",
            ) from exc
        if not isinstance(result, dict):
            raise ModelProviderError(
                "Dify business output must be an object",
                provider_code="dify_contract_error",
            )
        return result
