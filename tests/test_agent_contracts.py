import copy
import json
import unittest
from pathlib import Path

from agent.integrations.reelfire import (
    build_agent_input,
    to_backend_agent_call,
)
from agent.service import AgentService
from agent.tools.knowledge_retriever import KnowledgeRetrieverTool
from tests.test_agent_tools import KeywordAwareEmbedder


FIXTURE = (
    Path(__file__).parent / "fixtures" / "cv_analysis_report_v1.json"
)


def cv_analysis_report() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class ReelFireContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = AgentService(
            knowledge_retriever=KnowledgeRetrieverTool(
                embedder=KeywordAwareEmbedder()
            )
        )

    def test_real_cv_report_shape_is_wrapped_without_mutation(self) -> None:
        report = cv_analysis_report()
        original = copy.deepcopy(report)

        payload = build_agent_input(
            report,
            provider={"type": "rule_only"},
        )

        self.assertEqual(report, original)
        self.assertIsNot(payload["analysis_report"], report)
        self.assertEqual(payload["job_id"], "job_contract_001")
        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(payload["provider"], {"type": "rule_only"})

    def test_agent_runs_from_current_cv_analysis_report_contract(self) -> None:
        result = self.service.run_analysis_report(
            cv_analysis_report(),
            provider={"type": "rule_only"},
        )

        self.assertEqual(result["job_id"], "job_contract_001")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["provider"]["type"], "rule_only")
        self.assertIn("person(2)", result["summary"])
        self.assertEqual(len(result["evidence_refs"]), 8)
        self.assertEqual(result["trace"]["tools"][0]["status"], "completed")

    def test_backend_mapping_uses_backend_status_and_tool_fields(self) -> None:
        result = self.service.run_analysis_report(
            cv_analysis_report(),
            provider={"type": "rule_only"},
        )
        backend = to_backend_agent_call(result, prompt_version="v1")

        self.assertEqual(backend["job_id"], "job_contract_001")
        self.assertEqual(backend["status"], "needs_review")
        self.assertEqual(
            backend["input_summary"],
            "读取真实 CV 报告，共 2 个采样帧",
        )
        self.assertEqual(
            [item["tool"] for item in backend["tool_trace"]],
            [
                "visual_report_parser",
                "knowledge_retriever",
                "advice_generator",
                "result_validator",
            ],
        )
        self.assertEqual(backend["result"]["review_status"], "pending")
        self.assertTrue(backend["references"])

    def test_failed_agent_result_maps_to_failed_backend_call(self) -> None:
        report = cv_analysis_report()
        report["duration"] = 0
        result = self.service.run_analysis_report(
            report,
            provider={"type": "rule_only"},
        )
        backend = to_backend_agent_call(result)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(backend["status"], "failed")
        self.assertEqual(backend["error_code"], "invalid_agent_input")
        self.assertEqual(
            backend["tool_trace"][1]["status"],
            "skipped",
        )

    def test_adapter_rejects_missing_job_id_and_unknown_provider(self) -> None:
        report = cv_analysis_report()
        report.pop("job_id")
        with self.assertRaisesRegex(ValueError, "job_id"):
            build_agent_input(report)

        report = cv_analysis_report()
        with self.assertRaisesRegex(ValueError, "provider.type"):
            build_agent_input(
                report,
                provider={"type": "unknown"},
            )


if __name__ == "__main__":
    unittest.main()
