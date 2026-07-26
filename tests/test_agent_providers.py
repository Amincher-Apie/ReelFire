import json
import unittest
from unittest.mock import patch

from agent.providers.dify import DifyChatClient
from agent.providers.ollama import ModelProviderError
from agent.service import AgentService
from agent.tools.advice_generator import AdviceGeneratorTool
from agent.tools.knowledge_retriever import KnowledgeRetrieverTool
from tests.test_agent_tools import KeywordAwareEmbedder, agent_input


class DifyProviderTests(unittest.TestCase):
    @staticmethod
    def visual_summary() -> dict:
        return {
            "evidence_refs": [
                {
                    "ref_id": "ev:segment:seg_001",
                    "type": "segment",
                    "source_id": "seg_001",
                }
            ]
        }

    @staticmethod
    def knowledge_context() -> dict:
        return {
            "results": [
                {
                    "knowledge_id": "KB-SEGMENT-001",
                    "category": "segment",
                    "title": "片段复核",
                }
            ]
        }

    def test_empty_key_is_explicitly_rejected(self) -> None:
        client = DifyChatClient(api_key="")

        with self.assertRaisesRegex(ModelProviderError, "DIFY_API_KEY"):
            client.generate(
                "job_test",
                self.visual_summary(),
                self.knowledge_context(),
            )

    def test_empty_key_degrades_inside_workflow_without_losing_comments(
        self,
    ) -> None:
        payload = agent_input()
        payload["provider"] = {
            "type": "dify",
            "model": "reelfire-chatflow-v1.0.0",
        }
        result = AgentService(
            knowledge_retriever=KnowledgeRetrieverTool(
                embedder=KeywordAwareEmbedder()
            ),
            advice_generator=AdviceGeneratorTool(
                model_client=DifyChatClient(api_key="")
            ),
        ).run(payload)

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["provider"]["type"], "rule_only")
        self.assertTrue(result["segment_comments"])
        self.assertIn(
            "model_generation_failed",
            {item["code"] for item in result["errors"]},
        )

    def test_blocking_chat_request_uses_prompt_v2_and_parses_fenced_json(
        self,
    ) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

        response_payload = {
            "answer": "```json\n{\"summary\": \"ok\"}\n```"
        }
        with patch(
            "agent.providers.dify.urlopen",
            return_value=FakeResponse(),
        ) as mocked_urlopen, patch(
            "agent.providers.dify.json.load",
            return_value=response_payload,
        ):
            result = DifyChatClient(
                base_url="https://api.dify.test/v1",
                api_key="test-placeholder-key",
                user="contract-test",
                model_label="test-dify-app",
            ).generate(
                "job_test",
                self.visual_summary(),
                self.knowledge_context(),
            )

        request = mocked_urlopen.call_args.args[0]
        request_payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request.full_url, "https://api.dify.test/v1/chat-messages")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-placeholder-key")
        self.assertEqual(request.get_header("Accept"), "application/json")
        self.assertIn("ReelFire/1.0", request.get_header("User-agent"))
        self.assertEqual(request_payload["response_mode"], "blocking")
        self.assertEqual(request_payload["user"], "contract-test")
        self.assertIn("ev:segment:seg_001", request_payload["query"])
        self.assertIn("KB-SEGMENT-001", request_payload["query"])
        self.assertEqual(result, {"summary": "ok"})

    def test_app_info_verifies_chatflow_mode_without_exposing_key(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

        with patch(
            "agent.providers.dify.urlopen",
            return_value=FakeResponse(),
        ) as mocked_urlopen, patch(
            "agent.providers.dify.json.load",
            return_value={"name": "ReelFire", "mode": "advanced-chat"},
        ):
            result = DifyChatClient(
                base_url="https://api.dify.test",
                api_key="test-placeholder-key",
            ).get_app_info()

        request = mocked_urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.dify.test/v1/info")
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(
            request.get_header("Authorization"),
            "Bearer test-placeholder-key",
        )
        self.assertEqual(result["mode"], "advanced-chat")


if __name__ == "__main__":
    unittest.main()
