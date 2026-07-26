"""Command-line entry point for a real ReelFire Agent run."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from agent.providers import DifyChatClient, OllamaChatClient
from agent.service import AgentService
from agent.tools import AdviceGeneratorTool, KnowledgeRetrieverTool, OllamaEmbedder


ROOT = Path(__file__).resolve().parents[1]


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} 必须是 JSON 对象")
    return value


def _model_client(provider: str):
    if provider == "dify":
        return DifyChatClient()
    if provider == "ollama":
        return OllamaChatClient()
    return None


def _service(provider: str) -> AgentService:
    embedder = OllamaEmbedder() if os.getenv("OLLAMA_EMBED_MODEL") else None
    return AgentService(
        knowledge_retriever=KnowledgeRetrieverTool(embedder=embedder),
        advice_generator=AdviceGeneratorTool(
            model_client=_model_client(provider)
        ),
    )


def main(argv: list[str] | None = None) -> int:
    load_dotenv(ROOT / ".env", override=False)
    parser = argparse.ArgumentParser(description="Run the ReelFire Agent")
    parser.add_argument("--analysis-report", required=True, type=Path)
    parser.add_argument("--highlight-report", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--provider",
        choices=("dify", "ollama", "rule_only"),
        default=os.getenv("AGENT_PROVIDER", "dify"),
    )
    args = parser.parse_args(argv)

    analysis = _load_json(args.analysis_report)
    highlights = (
        _load_json(args.highlight_report)
        if args.highlight_report is not None
        else None
    )
    client = _model_client(args.provider)
    model = client.model if client is not None else "deterministic-v1"
    result = _service(args.provider).run_analysis_report(
        analysis,
        provider={"type": args.provider, "model": model},
        highlight_report=highlights,
        output_dir=args.output_dir,
    )
    print(
        json.dumps(
            {
                "job_id": result["job_id"],
                "status": result["status"],
                "provider": result["provider"],
                "segment_comment_count": len(result["segment_comments"]),
                "error_codes": [item["code"] for item in result["errors"]],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if result["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
