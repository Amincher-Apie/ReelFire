"""Check that local credentials target the expected ReelFire Chatflow app."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from agent.providers import DifyChatClient
from agent.providers.ollama import ModelProviderError


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_MODE = "advanced-chat"


def main() -> int:
    load_dotenv(ROOT / ".env", override=False)
    client = DifyChatClient()
    try:
        info = client.get_app_info()
    except ModelProviderError as exc:
        print(
            json.dumps(
                {"ok": False, "error": str(exc)},
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1

    mode = str(info.get("mode", ""))
    result = {
        "ok": mode == EXPECTED_MODE,
        "name": str(info.get("name", "")),
        "mode": mode,
        "expected_mode": EXPECTED_MODE,
        "chat_endpoint": client.api_endpoint("chat-messages"),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
