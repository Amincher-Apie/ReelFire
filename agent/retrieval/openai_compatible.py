"""Embedding requests for OpenAI-compatible HTTP endpoints."""

from __future__ import annotations

import json
import logging
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from agent.retrieval.ollama_topk import EmbeddingServiceError


LOGGER = logging.getLogger(__name__)


def request_openai_compatible_embeddings(
    base_url: str,
    model: str,
    texts: list[str],
    *,
    api_key: str = "",
    timeout: float = 180,
) -> list[list[float]]:
    """Return vectors from an OpenAI-compatible ``/embeddings`` endpoint."""

    endpoint = base_url.rstrip("/")
    if not endpoint.endswith("/embeddings"):
        endpoint += "/embeddings"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "ReelFire/1.0",
    }
    if api_key.strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"
    request = Request(
        endpoint,
        data=json.dumps(
            {
                "model": model,
                "input": texts,
                "encoding_format": "float",
            },
            ensure_ascii=False,
        ).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    started = time.monotonic()
    try:
        with urlopen(request, timeout=timeout) as response:
            payload: Any = json.load(response)
    except HTTPError as exc:
        LOGGER.warning(
            "embedding_request_failed provider=openai_compatible "
            "endpoint=post:embeddings duration_ms=%d status=%d "
            "retryable=%s",
            int((time.monotonic() - started) * 1000),
            int(exc.code),
            str(exc.code == 429 or exc.code >= 500).lower(),
        )
        raise EmbeddingServiceError(
            f"OpenAI-compatible embedding request returned HTTP {exc.code}"
        ) from exc
    except (URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", None)
        errno = getattr(reason, "errno", None) or getattr(exc, "errno", None)
        LOGGER.warning(
            "embedding_request_failed provider=openai_compatible "
            "endpoint=post:embeddings duration_ms=%d exception_type=%s "
            "reason_type=%s errno=%s retryable=true",
            int((time.monotonic() - started) * 1000),
            type(exc).__name__,
            type(reason).__name__ if reason is not None else "none",
            errno if isinstance(errno, int) else "-",
        )
        raise EmbeddingServiceError(
            f"OpenAI-compatible embedding request failed: {exc}"
        ) from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise EmbeddingServiceError(
            "OpenAI-compatible embedding response was not valid JSON"
        ) from exc

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list) or len(data) != len(texts):
        raise EmbeddingServiceError(
            "OpenAI-compatible endpoint returned an invalid embedding count"
        )
    ordered = sorted(
        data,
        key=lambda item: item.get("index", -1) if isinstance(item, dict) else -1,
    )
    vectors = [
        item.get("embedding")
        for item in ordered
        if isinstance(item, dict)
    ]
    if (
        len(vectors) != len(texts)
        or not vectors
        or not all(isinstance(vector, list) and vector for vector in vectors)
    ):
        raise EmbeddingServiceError(
            "OpenAI-compatible endpoint returned invalid embeddings"
        )
    dimension = len(vectors[0])
    if any(
        len(vector) != dimension
        or any(
            isinstance(value, bool) or not isinstance(value, (int, float))
            for value in vector
        )
        for vector in vectors
    ):
        raise EmbeddingServiceError(
            "OpenAI-compatible endpoint returned inconsistent vectors"
        )
    return [[float(value) for value in vector] for vector in vectors]
