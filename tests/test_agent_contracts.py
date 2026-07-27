import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from agent.integrations.reelfire import (
    build_agent_input,
    merge_highlight_report,
    to_backend_agent_call,
)
from agent.service import AgentService
from agent.tools.knowledge_retriever import KnowledgeRetrieverTool
from tests.test_agent_tools import KeywordAwareEmbedder


FIXTURE = (
    Path(__file__).parent / "fixtures" / "cv_analysis_report_v1.json"
)
HIGHLIGHT_FIXTURE = (
    Path(__file__).parent / "fixtures" / "cv_highlights_v2.json"
)
OUTPUT_SCHEMA = (
    Path(__file__).parents[1]
    / "agent"
    / "schemas"
    / "agent_output.schema.json"
)


def cv_analysis_report() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def cv_highlight_report() -> dict:
    return json.loads(HIGHLIGHT_FIXTURE.read_text(encoding="utf-8"))


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
        self.assertEqual(
            result["segment_comments"][0]["segment_id"],
            "seg_001",
        )
        self.assertIn("2.0—10.0秒", result["segment_comments"][0]["comment"])
        self.assertIn(
            "画面",
            result["segment_comments"][0]["comment"],
        )
        self.assertIn(
            "具体事件与本人/队友归属还要结合原片确认",
            result["segment_comments"][0]["comment"],
        )
        self.assertNotIn("候选排序分", result["segment_comments"][0]["comment"])
        self.assertNotIn("建议", result["segment_comments"][0]["comment"])
        self.assertNotIn("置信度", result["segment_comments"][0]["comment"])
        self.assertNotIn("帧", result["segment_comments"][0]["comment"])
        self.assertEqual(
            result["segment_comments"][0]["review_status"],
            "needs_review",
        )

    def test_backend_mapping_uses_backend_status_and_tool_fields(self) -> None:
        result = self.service.run_analysis_report(
            cv_analysis_report(),
            provider={"type": "rule_only"},
        )
        backend = to_backend_agent_call(result)

        self.assertEqual(backend["job_id"], "job_contract_001")
        self.assertEqual(backend["prompt_version"], "v3")
        self.assertEqual(backend["result_path"], "agent_report.json")
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
        self.assertTrue(
            all(item["input_summary"] for item in backend["tool_trace"])
        )
        self.assertTrue(
            all(item["output_summary"] for item in backend["tool_trace"])
        )
        self.assertTrue(backend["references"])
        self.assertEqual(
            backend["result"]["segment_comments"],
            result["segment_comments"],
        )

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

    def test_cv_multi_segment_export_is_assigned_stable_editor_ids(self) -> None:
        analysis = cv_analysis_report()
        highlights = cv_highlight_report()
        original_analysis = copy.deepcopy(analysis)
        original_highlights = copy.deepcopy(highlights)

        merged = merge_highlight_report(analysis, highlights)

        self.assertEqual(analysis, original_analysis)
        self.assertEqual(highlights, original_highlights)
        self.assertEqual(
            [item["id"] for item in merged["segments"]],
            ["seg_001", "seg_002"],
        )
        self.assertEqual(
            [item["order"] for item in merged["segments"]],
            [1, 2],
        )
        self.assertNotIn("score", merged["segments"][0])
        self.assertEqual(
            merged["segments"][0]["detections_summary"][0]["track_id"],
            11,
        )

    def test_segment_comments_match_editor_contract_without_fake_score(self) -> None:
        result = self.service.run_analysis_report(
            cv_analysis_report(),
            provider={"type": "rule_only"},
            highlight_report=cv_highlight_report(),
        )

        self.assertEqual(result["status"], "completed")
        comments = result["segment_comments"]
        self.assertEqual(
            [item["segment_id"] for item in comments],
            ["seg_001", "seg_002"],
        )
        self.assertIn("敌方角色", comments[0]["comment"])
        self.assertIn("CT角色", comments[1]["comment"])
        self.assertIn("步枪", comments[1]["comment"])
        self.assertTrue(all("建议" not in item["comment"] for item in comments))
        serialized = json.dumps(comments, ensure_ascii=False)
        self.assertNotIn("击杀", serialized)
        self.assertNotIn("爆头", serialized)
        self.assertNotIn("获胜", serialized)
        for comment in comments:
            self.assertEqual(
                comment["evidence_refs"][0],
                f"ev:segment:{comment['segment_id']}",
            )
            self.assertEqual(comment["review_status"], "needs_review")
            self.assertEqual(
                comment["action_recommendation"],
                "needs_review",
            )
            self.assertEqual(
                comment["explanation"]["trigger_rule"],
                "enemy_engagement",
            )
            self.assertTrue(comment["explanation"]["detections"])
            for detection in comment["explanation"]["detections"]:
                self.assertIn("first_seen", detection)
                self.assertIn("last_seen", detection)
                self.assertIn("observed_frame_count", detection)
                self.assertIn("consecutive_frame_count", detection)
                self.assertIn("average_confidence", detection)
                self.assertIn("max_confidence", detection)
            self.assertIn(
                comment["boundary_suggestion"]["action"],
                {
                    "keep",
                    "review_start",
                    "review_end",
                    "review_both",
                    "manual_review",
                },
            )

    def test_track_count_is_not_presented_as_kill_or_confirmed_highlight(self) -> None:
        highlights = cv_highlight_report()
        segment = highlights["segments"][1]
        segment["score"] = 1.0
        segment["reason"] = "enemy_engagement_multi_kill"

        result = self.service.run_analysis_report(
            cv_analysis_report(),
            provider={"type": "rule_only"},
            highlight_report=highlights,
        )
        comment = result["segment_comments"][1]

        self.assertEqual(comment["review_status"], "needs_review")
        self.assertEqual(
            comment["explanation"]["highlight_type"],
            "角色目标出现候选",
        )
        self.assertEqual(
            comment["explanation"]["trigger_rule"],
            "enemy_engagement",
        )
        self.assertTrue(comment["comment"].startswith("7.0—11.5秒："))
        self.assertIn("具体事件与本人/队友归属还要结合原片确认", comment["comment"])
        self.assertNotIn("候选排序分", comment["comment"])
        self.assertNotIn("建议", comment["comment"])
        self.assertNotIn("优先", comment["comment"])
        self.assertNotIn("multi_kill", comment["comment"])
        self.assertNotIn("连杀", comment["comment"])

    def test_explicit_kill_events_generate_comment_style_multi_kill_copy(self) -> None:
        highlights = cv_highlight_report()
        segment = highlights["segments"][1]
        segment["score"] = 0.95
        segment["reason"] = "kill_notification"
        segment["detected_classes"].append("kill_notification")
        segment["detections_summary"].extend(
            [
                {
                    "track_id": 31,
                    "class": "kill_notification",
                    "first_seen": 8.4,
                    "last_seen": 8.6,
                    "detection_count": 2,
                    "confidence": 0.96,
                    "confidence_max": 0.98,
                    "confidence_min": 0.94,
                },
                {
                    "track_id": 32,
                    "class": "kill_notification",
                    "first_seen": 10.2,
                    "last_seen": 10.4,
                    "detection_count": 2,
                    "confidence": 0.95,
                    "confidence_max": 0.97,
                    "confidence_min": 0.93,
                },
            ]
        )

        result = self.service.run_analysis_report(
            cv_analysis_report(),
            provider={"type": "rule_only"},
            highlight_report=highlights,
        )
        comment = result["segment_comments"][1]

        self.assertEqual(comment["review_status"], "pass")
        self.assertIn("8.4—10.2秒", comment["comment"])
        self.assertTrue(
            any(
                term in comment["comment"]
                for term in ("2次击杀提示", "两次击杀提示")
            )
        )
        self.assertIn("连杀", comment["comment"])
        self.assertTrue(
            any(term in comment["comment"] for term in ("nice", "漂亮", "拉满"))
        )

    def test_single_kill_and_clutch_events_use_distinct_emotional_copy(self) -> None:
        cases = (
            (
                "kill_notification",
                9.1,
                ("击杀", "nice"),
                ("连杀",),
            ),
            (
                "clutch_event",
                9.4,
                ("残局",),
                ("击杀", "连杀"),
            ),
        )
        for event_class, timestamp, required, forbidden in cases:
            with self.subTest(event_class=event_class):
                highlights = cv_highlight_report()
                segment = highlights["segments"][1]
                segment["score"] = 0.95
                segment["reason"] = event_class
                segment["detected_classes"].append(event_class)
                segment["detections_summary"].append(
                    {
                        "track_id": 40,
                        "class": event_class,
                        "first_seen": timestamp,
                        "last_seen": timestamp + 0.2,
                        "detection_count": 2,
                        "confidence": 0.96,
                        "confidence_max": 0.98,
                        "confidence_min": 0.94,
                    }
                )

                result = self.service.run_analysis_report(
                    cv_analysis_report(),
                    provider={"type": "rule_only"},
                    highlight_report=highlights,
                )
                text = result["segment_comments"][1]["comment"]

                self.assertIn(f"{timestamp:.1f}秒", text)
                self.assertTrue(all(term in text for term in required))
                self.assertTrue(all(term not in text for term in forbidden))

    def test_team_tracks_generate_timed_ct_vs_t_engagement_comment(self) -> None:
        highlights = cv_highlight_report()
        segment = highlights["segments"][1]
        segment["score"] = 0.91
        segment["reason"] = "enemy_engagement"
        segment["detected_classes"].append("character_t")
        segment["detections_summary"].extend(
            [
                {
                    "track_id": 23,
                    "class": "character_ct",
                    "first_seen": 7.5,
                    "last_seen": 10.4,
                    "detection_count": 12,
                    "confidence": 0.78,
                    "confidence_max": 0.93,
                    "confidence_min": 0.61,
                },
                {
                    "track_id": 24,
                    "class": "character_t",
                    "first_seen": 7.8,
                    "last_seen": 10.5,
                    "detection_count": 11,
                    "confidence": 0.8,
                    "confidence_max": 0.94,
                    "confidence_min": 0.63,
                },
                {
                    "track_id": 25,
                    "class": "character_t",
                    "first_seen": 8.0,
                    "last_seen": 10.7,
                    "detection_count": 10,
                    "confidence": 0.79,
                    "confidence_max": 0.92,
                    "confidence_min": 0.62,
                },
                {
                    "track_id": 26,
                    "class": "character_t",
                    "first_seen": 8.3,
                    "last_seen": 10.1,
                    "detection_count": 8,
                    "confidence": 0.77,
                    "confidence_max": 0.9,
                    "confidence_min": 0.6,
                },
            ]
        )

        result = self.service.run_analysis_report(
            cv_analysis_report(),
            provider={"type": "rule_only"},
            highlight_report=highlights,
        )
        text = result["segment_comments"][1]["comment"]

        self.assertIn("7.8—10.7秒", text)
        self.assertIn("2名CT", text)
        self.assertIn("3名T", text)
        self.assertIn("2打3", text)
        self.assertIn("交火", text)
        self.assertNotIn("画面中还出现了步枪", text)
        self.assertIn("T一侧人更多", text)
        self.assertIn("CT这波压力不小", text)
        self.assertNotIn("击杀", text)

    def test_explanation_maps_keyframes_boxes_and_low_confidence(self) -> None:
        report = cv_analysis_report()
        for sample in report["samples"]:
            for detected in sample["objects"]:
                detected["confidence"] = 0.55
        for frame in report["keyframes"]:
            for detected in frame["objects"]:
                detected["confidence"] = 0.55

        result = self.service.run_analysis_report(
            report,
            provider={"type": "rule_only"},
        )
        comment = result["segment_comments"][0]

        self.assertEqual(comment["review_status"], "needs_review")
        self.assertEqual(comment["action_recommendation"], "needs_review")
        self.assertEqual(
            comment["explanation"]["keyframe_refs"],
            ["ev:keyframe:kf_001"],
        )
        self.assertTrue(comment["explanation"]["detection_box_refs"])
        self.assertTrue(
            all(
                item["consecutive_frame_count"] is None
                for item in comment["explanation"]["detections"]
            )
        )
        self.assertNotIn("击杀", json.dumps(comment, ensure_ascii=False))

    def test_highlight_export_rejects_invalid_track_boundaries(self) -> None:
        highlights = cv_highlight_report()
        highlights["segments"][0]["detections_summary"][0][
            "first_seen"
        ] = 6.5
        result = self.service.run_analysis_report(
            cv_analysis_report(),
            provider={"type": "rule_only"},
            highlight_report=highlights,
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["errors"][0]["code"], "invalid_agent_input")

    def test_duplicate_segment_order_is_rejected(self) -> None:
        highlights = cv_highlight_report()
        highlights["segments"][0]["id"] = "seg_001"
        highlights["segments"][1]["id"] = "seg_002"
        highlights["segments"][0]["order"] = 1
        highlights["segments"][1]["order"] = 1
        analysis = cv_analysis_report()
        analysis["segments"] = highlights["segments"]

        result = self.service.run_analysis_report(
            analysis,
            provider={"type": "rule_only"},
        )

        self.assertEqual(result["status"], "failed")
        self.assertIn("order", result["errors"][0]["message"])

    def test_multi_segment_result_validates_against_output_schema(self) -> None:
        result = self.service.run_analysis_report(
            cv_analysis_report(),
            provider={"type": "rule_only"},
            highlight_report=cv_highlight_report(),
        )
        schema = json.loads(OUTPUT_SCHEMA.read_text(encoding="utf-8"))

        Draft202012Validator(schema).validate(result)

    def test_multi_segment_comments_are_repeatable(self) -> None:
        first = self.service.run_analysis_report(
            cv_analysis_report(),
            provider={"type": "rule_only"},
            highlight_report=cv_highlight_report(),
        )
        second = self.service.run_analysis_report(
            cv_analysis_report(),
            provider={"type": "rule_only"},
            highlight_report=cv_highlight_report(),
        )

        self.assertEqual(first["segment_comments"], second["segment_comments"])
        self.assertEqual(first["summary"], second["summary"])
        self.assertEqual(first["review"], second["review"])


if __name__ == "__main__":
    unittest.main()
