"""Build a small in-memory knowledge index with Ollama embeddings.

The command performs real embedding calls, calculates cosine similarity, and
writes compact acceptance evidence without storing the full vectors.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_KNOWLEDGE_PATH = ROOT / "agent" / "knowledge" / "media_review_rules.json"
DEFAULT_JSON_OUTPUT = ROOT / "docs" / "evidence" / "ollama_topk_results.json"
DEFAULT_MARKDOWN_OUTPUT = (
    ROOT / "docs" / "evidence" / "OLLAMA_KNOWLEDGE_ACCEPTANCE.md"
)
DEFAULT_QUERIES = (
    "画面没有检测到目标时如何审核？",
    "person 低置信度时如何处理？",
)


class EmbeddingServiceError(RuntimeError):
    """Raised when the configured Ollama embedding service is unavailable."""


def build_entry_text(entry: dict[str, Any]) -> str:
    """Create the exact text sent to the embedding model for one rule."""

    parts = [
        f"知识条目 ID：{entry['knowledge_id']}",
        f"标题：{entry['title']}",
        f"分类：{entry['category']}",
        f"关键词：{'、'.join(entry['keywords'])}",
        f"审核建议：{entry['review_recommendation']}",
        f"摘要规则：{entry['summary_guidance']}",
        "操作建议：" + "；".join(entry["suggestions"]),
        "使用边界：" + "；".join(entry["limitations"]),
    ]
    return "\n".join(parts)


def cosine_similarity(left: list[float], right: list[float]) -> float:
    """Return cosine similarity for two non-empty vectors."""

    if not left or len(left) != len(right):
        raise ValueError("vectors must be non-empty and have equal dimensions")
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        raise ValueError("zero-length vectors cannot be compared")
    return dot / (left_norm * right_norm)


def _request_json(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise EmbeddingServiceError(
            f"Ollama returned HTTP {exc.code}: {detail}"
        ) from exc
    except (URLError, TimeoutError) as exc:
        raise EmbeddingServiceError(f"Ollama request failed: {exc}") from exc


def request_embeddings(
    base_url: str,
    model: str,
    texts: list[str],
    timeout: float = 180,
) -> list[list[float]]:
    """Generate embeddings through Ollama's local `/api/embed` endpoint."""

    data = _request_json(
        f"{base_url.rstrip('/')}/api/embed",
        {"model": model, "input": texts},
        timeout,
    )
    embeddings = data.get("embeddings")
    if not isinstance(embeddings, list) or len(embeddings) != len(texts):
        raise EmbeddingServiceError("Ollama returned an invalid embedding count")
    if not embeddings or not embeddings[0]:
        raise EmbeddingServiceError("Ollama returned empty embeddings")
    dimension = len(embeddings[0])
    if any(len(vector) != dimension for vector in embeddings):
        raise EmbeddingServiceError("Ollama returned inconsistent vector dimensions")
    return embeddings


def retrieve_top_k(
    entries: list[dict[str, Any]],
    entry_vectors: list[list[float]],
    query_vector: list[float],
    top_k: int,
    min_similarity: float,
) -> list[dict[str, Any]]:
    """Rank knowledge entries by cosine similarity."""

    ranked = []
    for entry, vector in zip(entries, entry_vectors):
        similarity = cosine_similarity(query_vector, vector)
        ranked.append(
            {
                "knowledge_id": entry["knowledge_id"],
                "title": entry["title"],
                "similarity": round(similarity, 6),
                "passes_threshold": similarity >= min_similarity,
                "match_reasons": ["ollama_embedding", "cosine_similarity"],
            }
        )
    ranked.sort(key=lambda item: item["similarity"], reverse=True)
    results = ranked[:top_k]
    for rank, result in enumerate(results, start=1):
        result["rank"] = rank
    return results


def run_acceptance(
    knowledge_path: Path,
    base_url: str,
    model: str,
    queries: list[str],
) -> dict[str, Any]:
    """Run real document and query embedding calls and return evidence."""

    raw = knowledge_path.read_bytes()
    knowledge = json.loads(raw.decode("utf-8"))["knowledge_base"]
    entries = knowledge["entries"]
    retrieval = knowledge["retrieval"]
    top_k = int(retrieval["vector_search"]["top_k"])
    min_similarity = float(retrieval["vector_search"]["min_similarity"])

    entry_texts = [build_entry_text(entry) for entry in entries]
    entry_vectors = request_embeddings(base_url, model, entry_texts)
    query_vectors = request_embeddings(base_url, model, queries)

    query_results = []
    for query, vector in zip(queries, query_vectors):
        query_results.append(
            {
                "query": query,
                "results": retrieve_top_k(
                    entries,
                    entry_vectors,
                    vector,
                    top_k,
                    min_similarity,
                ),
            }
        )

    return {
        "status": "passed",
        "provider": "ollama",
        "model": model,
        "embedding_endpoint": f"{base_url.rstrip('/')}/api/embed",
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "knowledge_source": "agent/knowledge/media_review_rules.json",
        "knowledge_sha256": hashlib.sha256(raw).hexdigest(),
        "document_count": len(entries),
        "vector_dimension": len(entry_vectors[0]),
        "metric": "cosine",
        "top_k": top_k,
        "min_similarity": min_similarity,
        "queries": query_results,
    }


def write_markdown_report(result: dict[str, Any], path: Path) -> None:
    """Write a human-readable acceptance record from the JSON evidence."""

    lines = [
        "# 本地 Ollama 知识库 Embedding 与 Top-K 验收记录",
        "",
        "## 真实运行配置",
        "",
        "| 项目 | 实际值 |",
        "|---|---|",
        f"| 状态 | `{result['status']}` |",
        f"| 提供方 | `{result['provider']}` |",
        f"| Embedding 模型 | `{result['model']}` |",
        f"| 接口 | `{result['embedding_endpoint']}` |",
        f"| 知识条目数 | `{result['document_count']}` |",
        f"| 向量维度 | `{result['vector_dimension']}` |",
        f"| 相似度算法 | `{result['metric']}` |",
        f"| Top-K | `{result['top_k']}` |",
        f"| 最低分 | `{result['min_similarity']}` |",
        f"| 执行时间（UTC） | `{result['executed_at']}` |",
        f"| 源文件 SHA-256 | `{result['knowledge_sha256']}` |",
        "",
        "## 真实查询结果",
        "",
    ]
    for index, query in enumerate(result["queries"], start=1):
        lines.extend(
            [
                f"### 查询 {index}",
                "",
                f"`{query['query']}`",
                "",
                "| 排名 | 知识条目 | 标题 | 余弦相似度 | 通过阈值 |",
                "|---:|---|---|---:|---|",
            ]
        )
        for item in query["results"]:
            threshold = "是" if item["passes_threshold"] else "否"
            lines.append(
                f"| {item['rank']} | `{item['knowledge_id']}` | "
                f"{item['title']} | `{item['similarity']:.6f}` | {threshold} |"
            )
        lines.append("")

    lines.extend(
        [
            "## 复现命令",
            "",
            "```powershell",
            "$env:OLLAMA_BASE_URL='http://127.0.0.1:11435'",
            "$env:OLLAMA_EMBED_MODEL='qwen3-embedding:0.6b'",
            "python agent/retrieval/ollama_topk.py",
            "```",
            "",
            "结果由脚本调用本机 Ollama `/api/embed` 实时生成，未人工填写相似度。",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run real Ollama embeddings and Top-K retrieval."
    )
    parser.add_argument(
        "--knowledge",
        type=Path,
        default=DEFAULT_KNOWLEDGE_PATH,
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
    )
    parser.add_argument(
        "--model",
        default=os.getenv("OLLAMA_EMBED_MODEL"),
        help="Embedding model name; defaults to OLLAMA_EMBED_MODEL.",
    )
    parser.add_argument(
        "--query",
        action="append",
        dest="queries",
        help="Acceptance query; repeat for multiple queries.",
    )
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=DEFAULT_MARKDOWN_OUTPUT,
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.model:
        raise SystemExit("Set OLLAMA_EMBED_MODEL or pass --model.")
    result = run_acceptance(
        args.knowledge,
        args.base_url,
        args.model,
        args.queries or list(DEFAULT_QUERIES),
    )
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_markdown_report(result, args.markdown_output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
