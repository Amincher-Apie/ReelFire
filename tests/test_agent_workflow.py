import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.providers.ollama import OllamaChatClient
from agent.service import AgentService
from agent.tools.advice_generator import AdviceGeneratorTool
from agent.tools.knowledge_retriever import KnowledgeRetrieverTool
from tests.test_agent_tools import KeywordAwareEmbedder, agent_input


class ValidModelClient:
    provider_type = "ollama"
    model = "test-chat-model"

    def generate(self, job_id, visual_summary, knowledge_context):
        detection = next(
            item
            for item in visual_summary["evidence_refs"]
            if item["type"] == "detection"
        )
        knowledge = knowledge_context["results"][0]
        return {
            "summary": "检测到 person 和 car，候选片段需要结合证据审核。",
            "tags": [
                {
                    "name": "person",
                    "description": "报告中存在人物目标。",
                    "evidence_refs": [detection["ref_id"]],
                }
            ],
            "suggestions": [
                {
                    "suggestion_id": "SUG-MODEL-001",
                    "title": "核对关键帧",
                    "action": "检查检测框与候选片段的对应关系。",
                    "priority": "medium",
                    "evidence_refs": [detection["ref_id"]],
                    "knowledge_refs": [knowledge["knowledge_id"]],
                }
            ],
            "review": {
                "recommendation": "pass",
                "confidence": 0.8,
                "reasons": ["检测与知识引用均可追溯"],
            },
        }


class HallucinatingModelClient:
    provider_type = "ollama"
    model = "unsafe-test-model"

    def generate(self, job_id, visual_summary, knowledge_context):
        detection = next(
            item
            for item in visual_summary["evidence_refs"]
            if item["type"] == "detection"
        )
        knowledge = knowledge_context["results"][0]
        return {
            "summary": "玩家使用步枪完成爆头并获胜。",
            "tags": [
                {
                    "name": "爆头",
                    "description": "模型猜测的事件",
                    "evidence_refs": [detection["ref_id"]],
                }
            ],
            "suggestions": [
                {
                    "suggestion_id": "SUG-UNSAFE-001",
                    "title": "突出获胜画面",
                    "action": "把爆头时刻放在片头。",
                    "priority": "high",
                    "evidence_refs": [detection["ref_id"]],
                    "knowledge_refs": [knowledge["knowledge_id"]],
                }
            ],
            "review": {
                "recommendation": "pass",
                "confidence": 0.9,
                "reasons": ["模型推断"],
            },
        }


class PlaceholderModelClient:
    provider_type = "ollama"
    model = "placeholder-test-model"

    def generate(self, job_id, visual_summary, knowledge_context):
        evidence = visual_summary["evidence_refs"][0]["ref_id"]
        knowledge = knowledge_context["results"][0]["knowledge_id"]
        return {
            "summary": "仅基于证据的简短摘要",
            "tags": [
                {
                    "name": "真实类别或可证明的画面属性",
                    "description": "标签说明",
                    "evidence_refs": [evidence],
                }
            ],
            "suggestions": [
                {
                    "suggestion_id": "SUG-PLACEHOLDER-001",
                    "title": "建议标题",
                    "action": "可执行的剪辑或复核动作",
                    "priority": "medium",
                    "evidence_refs": [evidence],
                    "knowledge_refs": [knowledge],
                }
            ],
            "review": {
                "recommendation": "needs_review",
                "confidence": 0.0,
                "reasons": ["原因"],
            },
        }


class BrokenRetriever:
    def run(self, visual_summary):
        raise RuntimeError("retrieval backend crashed")


class EmptyRetriever:
    def run(self, visual_summary):
        return {
            "status": "completed",
            "strategy": "acceptance_empty",
            "query": "no matching rule",
            "top_k": 5,
            "result_count": 0,
            "results": [],
            "index": None,
            "degraded_reason": None,
        }


class BrokenGenerator:
    def run(self, visual_summary, retrieval, *, requested_provider):
        raise RuntimeError("generation backend crashed")


class AgentWorkflowTests(unittest.TestCase):
    def completed_service(self, model_client=None) -> AgentService:
        return AgentService(
            knowledge_retriever=KnowledgeRetrieverTool(
                embedder=KeywordAwareEmbedder()
            ),
            advice_generator=AdviceGeneratorTool(model_client=model_client),
        )

    def test_rule_only_workflow_returns_schema_shaped_output(self) -> None:
        payload = agent_input()
        payload["provider"] = {"type": "rule_only"}
        result = self.completed_service().run(payload)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["provider"]["type"], "rule_only")
        self.assertEqual(
            set(result),
            {
                "schema_version",
                "job_id",
                "status",
                "provider",
                "summary",
                "tags",
                "suggestions",
                "segment_comments",
                "review",
                "evidence_refs",
                "knowledge_refs",
                "trace",
                "errors",
            },
        )
        self.assertEqual(result["errors"], [])
        self.assertEqual(
            [item["name"] for item in result["trace"]["tools"]],
            [
                "report_parser",
                "knowledge_retriever",
                "advice_generator",
                "rule_validator",
            ],
        )
        self.assertTrue(
            all(item["status"] == "completed" for item in result["trace"]["tools"])
        )
        self.assertFalse(result["trace"]["degraded"])
        self.assertEqual(len(result["trace"]["input_summary_hash"]), 64)

    def test_valid_model_draft_is_used(self) -> None:
        result = self.completed_service(ValidModelClient()).run(agent_input())

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["provider"]["type"], "ollama")
        self.assertEqual(result["provider"]["model"], "test-chat-model")
        self.assertEqual(result["suggestions"][0]["suggestion_id"], "SUG-MODEL-001")
        self.assertEqual(
            [item["segment_id"] for item in result["segment_comments"]],
            ["seg_001"],
        )

    def test_ollama_prompt_uses_real_reference_whitelists(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

        fake_response = FakeResponse()
        fake_response_payload = {
            "message": {"content": json.dumps({"summary": "ok"})}
        }

        def load_response(response):
            self.assertIs(response, fake_response)
            return fake_response_payload

        visual_summary = {
            "evidence_refs": [
                {"ref_id": "ev:report", "type": "report", "source_id": "job"}
            ]
        }
        knowledge_context = {
            "results": [
                {
                    "knowledge_id": "KB-QUALITY-001",
                    "category": "evidence_quality",
                    "title": "空检测结果处理",
                }
            ]
        }
        with patch(
            "agent.providers.ollama.urlopen",
            return_value=fake_response,
        ) as mocked_urlopen, patch(
            "agent.providers.ollama.json.load",
            side_effect=load_response,
        ):
            result = OllamaChatClient(
                base_url="http://127.0.0.1:11435",
                model="test-model",
            ).generate("job", visual_summary, knowledge_context)

        request = mocked_urlopen.call_args.args[0]
        request_payload = json.loads(request.data.decode("utf-8"))
        prompt = request_payload["messages"][0]["content"]
        self.assertEqual(result, {"summary": "ok"})
        self.assertNotIn("EV-001", prompt)
        self.assertIn("ev:report", prompt)
        self.assertIn("KB-QUALITY-001", prompt)
        self.assertIn("白名单", prompt)

    def test_unsafe_model_draft_is_rejected_and_replaced(self) -> None:
        result = self.completed_service(HallucinatingModelClient()).run(
            agent_input()
        )

        serialized = json.dumps(result, ensure_ascii=False)
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["provider"]["type"], "rule_only")
        self.assertNotIn("爆头", serialized)
        self.assertNotIn("步枪", serialized)
        self.assertIn(
            "generated_output_rejected",
            {item["code"] for item in result["errors"]},
        )
        validator_trace = result["trace"]["tools"][-1]
        self.assertEqual(validator_trace["status"], "degraded")

    def test_placeholder_model_draft_is_rejected_and_replaced(self) -> None:
        result = self.completed_service(PlaceholderModelClient()).run(
            agent_input()
        )

        serialized = json.dumps(result, ensure_ascii=False)
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["provider"]["type"], "rule_only")
        self.assertNotIn("标签说明", serialized)
        self.assertNotIn("建议标题", serialized)
        self.assertIn(
            "generated_output_rejected",
            {item["code"] for item in result["errors"]},
        )

    def test_unconfigured_requested_provider_degrades_to_rules(self) -> None:
        result = self.completed_service().run(agent_input())

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["provider"]["type"], "rule_only")
        self.assertTrue(result["trace"]["degraded"])
        self.assertIn(
            "model_provider_not_configured",
            {item["code"] for item in result["errors"]},
        )

    def test_retriever_failure_uses_rule_fallback(self) -> None:
        payload = agent_input()
        payload["provider"] = {"type": "rule_only"}
        result = AgentService(
            knowledge_retriever=BrokenRetriever(),
        ).run(payload)

        self.assertEqual(result["status"], "degraded")
        self.assertTrue(result["knowledge_refs"])
        self.assertIn(
            "knowledge_retrieval_failed",
            {item["code"] for item in result["errors"]},
        )
        self.assertEqual(
            result["trace"]["tools"][1]["status"],
            "degraded",
        )

    def test_generator_failure_uses_rule_fallback(self) -> None:
        payload = agent_input()
        payload["provider"] = {"type": "rule_only"}
        result = AgentService(
            knowledge_retriever=KnowledgeRetrieverTool(
                embedder=KeywordAwareEmbedder()
            ),
            advice_generator=BrokenGenerator(),
        ).run(payload)

        self.assertEqual(result["status"], "degraded")
        self.assertTrue(result["suggestions"])
        self.assertIn(
            "advice_generation_failed",
            {item["code"] for item in result["errors"]},
        )
        self.assertEqual(
            result["trace"]["tools"][2]["status"],
            "degraded",
        )

    def test_invalid_input_returns_failed_and_skips_downstream_tools(self) -> None:
        payload = agent_input()
        payload["analysis_report"]["duration"] = 0
        result = self.completed_service().run(payload)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["review"]["recommendation"], "reject")
        self.assertEqual(
            [item["status"] for item in result["trace"]["tools"]],
            ["failed", "skipped", "skipped", "skipped"],
        )
        self.assertEqual(result["errors"][0]["stage"], "report_parser")

    def test_empty_detection_cannot_be_auto_passed(self) -> None:
        payload = agent_input()
        payload["provider"] = {"type": "rule_only"}
        for sample in payload["analysis_report"]["samples"]:
            sample["objects"] = []
        payload["analysis_report"]["keyframes"][0]["objects"] = []
        result = self.completed_service().run(payload)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["review"]["recommendation"], "needs_review")
        self.assertEqual(result["tags"], [])
        self.assertIn("没有可靠目标类别证据", result["summary"])

    def test_low_confidence_detection_requires_review(self) -> None:
        payload = agent_input()
        payload["provider"] = {"type": "rule_only"}
        for sample in payload["analysis_report"]["samples"]:
            for detected in sample["objects"]:
                detected["confidence"] = 0.3
        for detected in payload["analysis_report"]["keyframes"][0]["objects"]:
            detected["confidence"] = 0.3

        result = self.completed_service().run(payload)

        self.assertEqual(result["review"]["recommendation"], "needs_review")
        self.assertLessEqual(result["review"]["confidence"], 0.45)
        self.assertTrue(
            all("0.300" in item["description"] for item in result["tags"])
        )

    def test_knowledge_miss_requires_review_and_keeps_segment_comment(self) -> None:
        payload = agent_input()
        payload["provider"] = {"type": "rule_only"}
        result = AgentService(knowledge_retriever=EmptyRetriever()).run(payload)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["review"]["recommendation"], "needs_review")
        self.assertEqual(result["knowledge_refs"], [])
        self.assertEqual(
            [item["segment_id"] for item in result["segment_comments"]],
            ["seg_001"],
        )

    def test_report_and_trace_are_atomically_persisted(self) -> None:
        payload = agent_input()
        payload["provider"] = {"type": "rule_only"}
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            result = self.completed_service().run(
                payload,
                output_dir=output_dir,
            )
            report = json.loads(
                (output_dir / "agent_report.json").read_text(encoding="utf-8")
            )
            trace = json.loads(
                (output_dir / "agent_trace.json").read_text(encoding="utf-8")
            )

            self.assertEqual(report, result)
            self.assertEqual(trace["job_id"], payload["job_id"])
            self.assertNotIn("analysis_report", trace)
            self.assertNotIn("samples", trace)
            self.assertFalse(list(output_dir.glob(".*.tmp")))

    def test_persistence_failure_returns_degraded_result(self) -> None:
        payload = agent_input()
        payload["provider"] = {"type": "rule_only"}
        with tempfile.TemporaryDirectory() as directory:
            blocked_path = Path(directory) / "not_a_directory"
            blocked_path.write_text("occupied", encoding="utf-8")
            result = self.completed_service().run(
                payload,
                output_dir=blocked_path,
            )

        self.assertEqual(result["status"], "degraded")
        self.assertTrue(result["trace"]["degraded"])
        self.assertIn(
            "agent_persistence_failed",
            {item["code"] for item in result["errors"]},
        )
        self.assertNotIn(str(blocked_path), json.dumps(result, ensure_ascii=False))
        self.assertNotIn(":\\", json.dumps(result, ensure_ascii=False))

    def test_every_business_reference_resolves(self) -> None:
        payload = agent_input()
        payload["provider"] = {"type": "rule_only"}
        result = self.completed_service().run(payload)
        evidence_ids = {item["ref_id"] for item in result["evidence_refs"]}
        knowledge_ids = {
            item["knowledge_id"] for item in result["knowledge_refs"]
        }

        for tag in result["tags"]:
            self.assertTrue(set(tag["evidence_refs"]) <= evidence_ids)
        for suggestion in result["suggestions"]:
            self.assertTrue(set(suggestion["evidence_refs"]) <= evidence_ids)
            self.assertTrue(set(suggestion["knowledge_refs"]) <= knowledge_ids)
        for comment in result["segment_comments"]:
            self.assertTrue(set(comment["evidence_refs"]) <= evidence_ids)


if __name__ == "__main__":
    unittest.main()
