"""Adapters between the Agent workflow and other ReelFire modules."""

from agent.integrations.reelfire import (
    build_agent_input,
    merge_highlight_report,
    to_backend_agent_call,
)

__all__ = [
    "build_agent_input",
    "merge_highlight_report",
    "to_backend_agent_call",
]
