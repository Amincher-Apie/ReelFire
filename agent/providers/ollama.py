"""Local Ollama JSON generation adapter."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROMPT_PATH = ROOT / "agent" / "prompts" / "review_agent_v2.md"


class ModelProviderError(RuntimeError):
    """Raised when a configured model provider cannot return business JSON."""

    def __init__(
        self,
        message: str,
        *,
        provider_code: str = "model_provider_error",
        retryable: bool = False,
        status_code: int | None = None,
        attempt_count: int = 1,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.provider_code = provider_code
        self.retryable = retryable
        self.status_code = status_code
        self.attempt_count = attempt_count
        self.request_id = request_id


class OllamaChatClient:
    """Generate a business draft through Ollama's local `/api/chat` endpoint."""

    provider_type = "ollama"

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        *,
        prompt_path: Path = DEFAULT_PROMPT_PATH,
        timeout: float = 120,
    ) -> None:
        self.base_url = base_url or os.getenv(
            "OLLAMA_BASE_URL",
            "http://127.0.0.1:11434",
        )
        self.model = model or os.getenv("OLLAMA_MODEL")
        self.timeout = timeout
        self.prompt_template = prompt_path.read_text(encoding="utf-8")
        if not self.model:
            raise ValueError("Set OLLAMA_MODEL or pass a chat model.")

    def generate(
        self,
        job_id: str,
        visual_summary: dict[str, Any],
        knowledge_context: dict[str, Any],
    ) -> dict[str, Any]:
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
        example_evidence = evidence_ids[0] if evidence_ids else "NO_EVIDENCE"
        example_knowledge = knowledge_ids[0] if knowledge_ids else "NO_KNOWLEDGE"
        prompt = (
            self.prompt_template.replace("{{job_id}}", job_id)
            .replace(
                "{{visual_summary_json}}",
                json.dumps(visual_summary, ensure_ascii=False, separators=(",", ":")),
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
        prompt = prompt.replace("EV-001", example_evidence).replace(
            "KB-CORE-001",
            example_knowledge,
        )
        prompt += (
            "\n\n只能从下列白名单复制引用，不得创建新编号：\n"
            f"evidence_ref 白名单：{json.dumps(evidence_ids, ensure_ascii=False)}\n"
            f"knowledge_id 白名单：{json.dumps(knowledge_ids, ensure_ascii=False)}\n"
        )
        request = Request(
            f"{self.base_url.rstrip('/')}/api/chat",
            data=json.dumps(
                {
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0, "num_predict": 1400},
                },
                ensure_ascii=False,
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.load(response)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ModelProviderError(
                f"Ollama returned HTTP {exc.code}: {detail[:300]}",
                provider_code="ollama_http_error",
                retryable=exc.code == 429 or 500 <= exc.code < 600,
                status_code=exc.code,
            ) from exc
        except (URLError, TimeoutError) as exc:
            raise ModelProviderError(
                f"Ollama request failed: {exc}",
                provider_code="ollama_unavailable",
                retryable=True,
            ) from exc

        content = payload.get("message", {}).get("content")
        if not isinstance(content, str) or not content.strip():
            raise ModelProviderError(
                "Ollama returned an empty message",
                provider_code="ollama_contract_error",
            )
        try:
            result = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ModelProviderError(
                "Ollama returned invalid JSON",
                provider_code="ollama_contract_error",
            ) from exc
        if not isinstance(result, dict):
            raise ModelProviderError(
                "Ollama business output must be an object",
                provider_code="ollama_contract_error",
            )
        return result
