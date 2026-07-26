"""Model provider adapters for the Agent workflow."""

from agent.providers.dify import DifyChatClient
from agent.providers.ollama import OllamaChatClient

__all__ = ["DifyChatClient", "OllamaChatClient"]
