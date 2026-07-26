"""Dify chat application adapter using an API key from the environment."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from agent.providers.ollama import DEFAULT_PROMPT_PATH, ModelProviderError


class DifyChatClient:
    """Generate a business draft through Dify's blocking chat API."""

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
            "dify-chat-app",
        )
        self.timeout = timeout
        self.prompt_template = prompt_path.read_text(encoding="utf-8")

    def generate(
        self,
        job_id: str,
        visual_summary: dict[str, Any],
        knowledge_context: dict[str, Any],
    ) -> dict[str, Any]:
        if not self.api_key.strip():
            raise ModelProviderError(
                "Set DIFY_API_KEY in the local .env file before online testing."
            )
        prompt = self._render_prompt(
            job_id,
            visual_summary,
            knowledge_context,
        )
        base_url = self.base_url.rstrip("/")
        endpoint = (
            f"{base_url}/chat-messages"
            if base_url.endswith("/v1")
            else f"{base_url}/v1/chat-messages"
        )
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
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.load(response)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ModelProviderError(
                f"Dify returned HTTP {exc.code}: {detail[:300]}"
            ) from exc
        except (URLError, TimeoutError) as exc:
            raise ModelProviderError(f"Dify request failed: {exc}") from exc

        answer = payload.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            raise ModelProviderError("Dify returned an empty answer")
        return self._parse_answer(answer)

    def _render_prompt(
        self,
        job_id: str,
        visual_summary: dict[str, Any],
        knowledge_context: dict[str, Any],
    ) -> str:
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

    @staticmethod
    def _parse_answer(answer: str) -> dict[str, Any]:
        normalized = answer.strip()
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
            raise ModelProviderError("Dify returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise ModelProviderError("Dify business output must be an object")
        return result
