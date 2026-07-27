import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import BytesIO
from io import StringIO
from urllib.error import HTTPError, URLError
from unittest.mock import patch

from agent import check_dify
from agent.integrations.reelfire import to_backend_agent_call
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
        provider_error = next(
            item
            for item in result["errors"]
            if item["code"] == "model_generation_failed"
        )
        self.assertEqual(provider_error["provider_code"], "dify_not_configured")
        self.assertEqual(provider_error["attempt_count"], 0)
        self.assertFalse(provider_error["retryable"])
        risk_flags = to_backend_agent_call(result)["result"]["risk_flags"]
        self.assertIn("model_generation_failed", risk_flags)
        self.assertIn("dify_not_configured", risk_flags)

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

    def test_parse_answer_strips_dify_reasoning_block(self) -> None:
        result = DifyChatClient._parse_answer(
            '<think>internal reasoning must not enter the contract</think>'
            '{"summary":"ok","review":{"recommendation":"needs_review"}}'
        )

        self.assertEqual(result["summary"], "ok")
        self.assertEqual(result["review"]["recommendation"], "needs_review")

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
        self.assertEqual(request.get_header("Accept"), "application/json")
        self.assertIn("ReelFire/1.0", request.get_header("User-agent"))
        self.assertEqual(result["mode"], "advanced-chat")

    def test_auth_failure_is_classified_and_never_retried(self) -> None:
        error = HTTPError(
            "https://api.dify.test/v1/info",
            401,
            "Unauthorized",
            {},
            BytesIO(b'{"message":"invalid token"}'),
        )
        client = DifyChatClient(
            base_url="https://api.dify.test",
            api_key="test-placeholder-key",
            max_attempts=3,
            retry_base_seconds=0,
        )

        with patch("agent.providers.dify.urlopen", side_effect=error) as mocked:
            with self.assertRaises(ModelProviderError) as raised:
                client.get_app_info()

        self.assertEqual(mocked.call_count, 1)
        self.assertEqual(raised.exception.provider_code, "dify_auth_failed")
        self.assertEqual(raised.exception.status_code, 401)
        self.assertFalse(raised.exception.retryable)
        self.assertEqual(raised.exception.attempt_count, 1)

    def test_http_error_detail_redacts_configured_key(self) -> None:
        secret = "test-secret-value-12345"
        error = HTTPError(
            "https://api.dify.test/v1/info",
            400,
            "Bad Request",
            {},
            BytesIO(
                (
                    '{"authorization":"Bearer '
                    + secret
                    + '","api_key":"'
                    + secret
                    + '"}'
                ).encode("utf-8")
            ),
        )
        client = DifyChatClient(
            base_url="https://api.dify.test",
            api_key=secret,
            max_attempts=1,
        )

        with patch("agent.providers.dify.urlopen", side_effect=error):
            with self.assertRaises(ModelProviderError) as raised:
                client.get_app_info()

        self.assertNotIn(secret, str(raised.exception))
        self.assertIn("[redacted]", str(raised.exception))
        self.assertEqual(
            raised.exception.provider_code,
            "dify_request_rejected",
        )

    def test_rate_limit_retries_once_then_returns_answer(self) -> None:
        class FakeResponse:
            headers = {"x-request-id": "req-success"}

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

        rate_limit = HTTPError(
            "https://api.dify.test/v1/chat-messages",
            429,
            "Too Many Requests",
            {"x-request-id": "req-rate-limit"},
            BytesIO(b'{"message":"slow down"}'),
        )
        sleeps: list[float] = []
        client = DifyChatClient(
            base_url="https://api.dify.test",
            api_key="test-placeholder-key",
            max_attempts=3,
            retry_base_seconds=0.1,
            sleep_fn=sleeps.append,
            jitter_fn=lambda: 0.5,
        )

        with patch(
            "agent.providers.dify.urlopen",
            side_effect=[rate_limit, FakeResponse()],
        ) as mocked_urlopen, patch(
            "agent.providers.dify.json.load",
            return_value={"answer": '{"summary":"ok"}'},
        ):
            result = client.generate(
                "job_test",
                self.visual_summary(),
                self.knowledge_context(),
            )

        self.assertEqual(result, {"summary": "ok"})
        self.assertEqual(mocked_urlopen.call_count, 2)
        self.assertEqual(client.last_attempt_count, 2)
        self.assertEqual(client.last_request_id, "req-success")
        self.assertEqual(sleeps, [0.1])

    def test_network_failure_exhausts_bounded_retries(self) -> None:
        sleeps: list[float] = []
        client = DifyChatClient(
            base_url="https://api.dify.test",
            api_key="test-placeholder-key",
            max_attempts=3,
            retry_base_seconds=0.1,
            sleep_fn=sleeps.append,
            jitter_fn=lambda: 0.5,
        )

        with patch(
            "agent.providers.dify.urlopen",
            side_effect=URLError("offline"),
        ) as mocked_urlopen:
            with self.assertRaises(ModelProviderError) as raised:
                client.get_app_info()

        self.assertEqual(mocked_urlopen.call_count, 3)
        self.assertEqual(raised.exception.provider_code, "dify_network_error")
        self.assertTrue(raised.exception.retryable)
        self.assertEqual(raised.exception.attempt_count, 3)
        self.assertEqual(sleeps, [0.1, 0.2])

    def test_server_error_retries_then_health_check_succeeds(self) -> None:
        class FakeResponse:
            headers = {}

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

        unavailable = HTTPError(
            "https://api.dify.test/v1/info",
            503,
            "Service Unavailable",
            {},
            BytesIO(b'{"message":"temporary"}'),
        )
        client = DifyChatClient(
            base_url="https://api.dify.test",
            api_key="test-placeholder-key",
            max_attempts=2,
            retry_base_seconds=0,
            sleep_fn=lambda delay: None,
        )
        with patch(
            "agent.providers.dify.urlopen",
            side_effect=[unavailable, FakeResponse()],
        ) as mocked_urlopen, patch(
            "agent.providers.dify.json.load",
            return_value={"name": "ReelFire", "mode": "advanced-chat"},
        ):
            result = client.get_app_info()

        self.assertEqual(mocked_urlopen.call_count, 2)
        self.assertEqual(client.last_attempt_count, 2)
        self.assertEqual(result["mode"], "advanced-chat")

    def test_contract_error_is_not_retried(self) -> None:
        class FakeResponse:
            headers = {}

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

        client = DifyChatClient(
            base_url="https://api.dify.test",
            api_key="test-placeholder-key",
            max_attempts=3,
            retry_base_seconds=0,
        )
        with patch(
            "agent.providers.dify.urlopen",
            return_value=FakeResponse(),
        ) as mocked_urlopen, patch(
            "agent.providers.dify.json.load",
            return_value={"answer": "not-json"},
        ):
            with self.assertRaises(ModelProviderError) as raised:
                client.generate(
                    "job_test",
                    self.visual_summary(),
                    self.knowledge_context(),
                )

        self.assertEqual(mocked_urlopen.call_count, 1)
        self.assertEqual(raised.exception.provider_code, "dify_contract_error")
        self.assertFalse(raised.exception.retryable)
        self.assertEqual(raised.exception.attempt_count, 1)

    def test_health_check_reports_structured_auth_failure(self) -> None:
        output = StringIO()
        with patch("agent.check_dify.DifyChatClient") as client_type:
            client_type.return_value.get_app_info.side_effect = ModelProviderError(
                "Dify authentication failed (HTTP 401)",
                provider_code="dify_auth_failed",
                status_code=401,
                attempt_count=1,
            )
            with redirect_stderr(output):
                exit_code = check_dify.main()

        result = json.loads(output.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertFalse(result["ok"])
        self.assertEqual(result["provider_error_code"], "dify_auth_failed")
        self.assertEqual(result["status_code"], 401)
        self.assertFalse(result["retryable"])

    def test_health_check_reports_app_mode_mismatch(self) -> None:
        output = StringIO()
        with patch("agent.check_dify.DifyChatClient") as client_type:
            client = client_type.return_value
            client.get_app_info.return_value = {
                "name": "Wrong app",
                "mode": "workflow",
            }
            client.api_endpoint.return_value = (
                "https://api.dify.test/v1/chat-messages"
            )
            client.last_attempt_count = 1
            with redirect_stdout(output):
                exit_code = check_dify.main()

        result = json.loads(output.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertFalse(result["ok"])
        self.assertEqual(
            result["provider_error_code"],
            "dify_app_mode_mismatch",
        )
        self.assertFalse(result["retryable"])


if __name__ == "__main__":
    unittest.main()
