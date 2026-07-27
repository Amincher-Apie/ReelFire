"""CLI for deterministic feedback statistics and rule suggestions."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from agent.tools import FeedbackAnalyzerTool, FeedbackValidationError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze ReelFire editor feedback JSON.",
    )
    parser.add_argument(
        "feedback",
        type=Path,
        help="UTF-8 JSON file containing an array of feedback events.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional summary output path; stdout is always available.",
    )
    return parser


def _records(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise FeedbackValidationError("feedback JSON 顶层必须是数组")
    return value


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = FeedbackAnalyzerTool().run(_records(args.feedback))
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        FeedbackValidationError,
    ) as exc:
        print(f"feedback_analysis_failed: {exc}", file=sys.stderr)
        return 2
    serialized = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_name(f".{args.output.name}.tmp")
        temporary.write_text(serialized + "\n", encoding="utf-8")
        temporary.replace(args.output)
    print(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
