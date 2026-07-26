import copy
import unittest

from agent.tools.knowledge_retriever import KnowledgeRetrieverTool
from agent.tools.report_parser import ReportParserTool, ReportValidationError


def agent_input() -> dict:
    return {
        "schema_version": "1.0",
        "job_id": "job_mock_001",
        "provider": {"type": "ollama", "model": "qwen3"},
        "analysis_report": {
            "job_id": "job_mock_001",
            "duration": 12.0,
            "total_sampled_frames": 2,
            "samples": [
                {
                    "frame_index": 0,
                    "timestamp": 1.0,
                    "object_count": 1,
                    "object_score": 0.4,
                    "scene_change_score": 0.2,
                    "motion_score": 0.3,
                    "highlight_score": 0.32,
                    "objects": [
                        {
                            "class": "person",
                            "confidence": 0.42,
                            "bbox": [1, 2, 30, 40],
                        }
                    ],
                },
                {
                    "frame_index": 1,
                    "timestamp": 6.0,
                    "object_count": 2,
                    "object_score": 0.7,
                    "scene_change_score": 0.8,
                    "motion_score": 0.75,
                    "highlight_score": 0.735,
                    "objects": [
                        {
                            "class": "person",
                            "confidence": 0.88,
                            "bbox": [5, 8, 35, 45],
                        },
                        {
                            "class": "car",
                            "confidence": 0.81,
                            "bbox": [40, 10, 90, 55],
                        },
                    ],
                },
            ],
            "keyframes": [
                {
                    "id": "kf_001",
                    "timestamp": 6.0,
                    "object_score": 0.7,
                    "scene_change_score": 0.8,
                    "motion_score": 0.75,
                    "highlight_score": 0.735,
                    "objects": [
                        {
                            "class": "person",
                            "confidence": 0.88,
                            "bbox": [5, 8, 35, 45],
                        },
                        {
                            "class": "car",
                            "confidence": 0.81,
                            "bbox": [40, 10, 90, 55],
                        },
                    ],
                }
            ],
            "segments": [
                {
                    "id": "seg_001",
                    "start": 2.0,
                    "end": 10.0,
                    "score": 0.735,
                    "source_keyframes": ["kf_001"],
                }
            ],
            "segment_tags": {
                "total_tags": 2,
                "summary": ["person(2)", "car(1)"],
            },
            "ai_cover_prompt": "6.0 秒检测到 person 和 car。",
        },
    }


class ReportParserToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = ReportParserTool()

    def test_parser_builds_controlled_summary_and_evidence(self) -> None:
        result = self.parser.run(agent_input())

        self.assertEqual(result["job_id"], "job_mock_001")
        self.assertEqual(result["metrics"]["total_detections"], 3)
        self.assertEqual(result["metrics"]["max_object_count"], 2)
        self.assertEqual(result["metrics"]["max_confidence"], 0.88)
        self.assertEqual(
            [item["name"] for item in result["detected_classes"]],
            ["person", "car"],
        )
        self.assertEqual(result["keyframes"][0]["id"], "kf_001")
        self.assertEqual(result["segments"][0]["source_keyframes"], ["kf_001"])

        ref_ids = [item["ref_id"] for item in result["evidence_refs"]]
        self.assertEqual(len(ref_ids), len(set(ref_ids)))
        self.assertIn("ev:report", ref_ids)
        self.assertIn("ev:keyframe:kf_001", ref_ids)
        self.assertIn("ev:segment:seg_001", ref_ids)
        self.assertTrue(
            any(
                item.get("class_name") == "person"
                and item.get("confidence") == 0.88
                for item in result["evidence_refs"]
            )
        )

    def test_parser_does_not_promote_cover_prompt_to_detection_facts(self) -> None:
        payload = agent_input()
        payload["analysis_report"]["ai_cover_prompt"] = "爆头取胜，使用步枪。"
        result = self.parser.run(payload)

        self.assertNotIn(
            "爆头",
            " ".join(item["name"] for item in result["detected_classes"]),
        )
        self.assertEqual(
            result["rule_baseline"]["ai_cover_prompt"],
            "爆头取胜，使用步枪。",
        )

    def test_parser_rejects_mismatched_job_id(self) -> None:
        payload = agent_input()
        payload["analysis_report"]["job_id"] = "another_job"
        with self.assertRaisesRegex(ReportValidationError, "job_id"):
            self.parser.run(payload)

    def test_parser_rejects_invalid_segment_boundary(self) -> None:
        payload = agent_input()
        payload["analysis_report"]["segments"][0]["end"] = 13.0
        with self.assertRaisesRegex(ReportValidationError, "end"):
            self.parser.run(payload)

    def test_parser_rejects_unknown_source_keyframe(self) -> None:
        payload = agent_input()
        payload["analysis_report"]["segments"][0]["source_keyframes"] = [
            "kf_missing"
        ]
        with self.assertRaisesRegex(ReportValidationError, "不存在的关键帧"):
            self.parser.run(payload)

    def test_parser_rejects_invalid_detection_confidence(self) -> None:
        payload = agent_input()
        payload["analysis_report"]["samples"][0]["objects"][0][
            "confidence"
        ] = 1.2
        with self.assertRaisesRegex(ReportValidationError, "confidence"):
            self.parser.run(payload)

    def test_parser_accepts_cv_detection_without_track_id(self) -> None:
        payload = agent_input()
        payload["analysis_report"]["segments"][0].update(
            detected_classes=["person"],
            detections_summary=[
                {
                    "track_id": None,
                    "class": "person",
                    "confidence": 0.88,
                    "confidence_max": 0.91,
                    "confidence_min": 0.82,
                    "first_seen": 2.5,
                    "last_seen": 8.0,
                    "detection_count": 4,
                }
            ],
        )

        result = self.parser.run(payload)

        detection = result["segments"][0]["detections_summary"][0]
        self.assertIsNone(detection["track_id"])
        self.assertEqual(result["segments"][0]["detected_classes"][0]["track_count"], 0)

    def test_parser_rejects_duplicate_sample_frame_index(self) -> None:
        payload = agent_input()
        payload["analysis_report"]["samples"][1]["frame_index"] = 0
        with self.assertRaisesRegex(ReportValidationError, "frame_index"):
            self.parser.run(payload)

    def test_parser_rejects_non_finite_numbers(self) -> None:
        payload = agent_input()
        payload["analysis_report"]["keyframes"][0]["highlight_score"] = float(
            "nan"
        )
        with self.assertRaisesRegex(ReportValidationError, "有限数字"):
            self.parser.run(payload)


class KeywordAwareEmbedder:
    """Deterministic fake used to exercise the vector path without a service."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        vectors = []
        for text in texts:
            normalized = text.casefold()
            vectors.append(
                [
                    float("person" in normalized or "角色" in normalized),
                    float(
                        "low confidence" in normalized
                        or "低置信度" in normalized
                    ),
                    float("segment" in normalized or "片段" in normalized),
                    0.1,
                ]
            )
        return vectors


class BrokenEmbedder:
    def __call__(self, texts: list[str]) -> list[list[float]]:
        raise TimeoutError("local embedding timed out")


class KnowledgeRetrieverToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.summary = ReportParserTool().run(agent_input())

    def test_vector_retrieval_builds_cached_index_and_returns_top_k(self) -> None:
        embedder = KeywordAwareEmbedder()
        retriever = KnowledgeRetrieverTool(embedder=embedder)

        first = retriever.run(
            self.summary,
            query="person 低置信度片段如何审核",
        )
        second = retriever.run(
            self.summary,
            query="person 低置信度片段如何审核",
        )

        self.assertEqual(first["status"], "completed")
        self.assertEqual(first["strategy"], "hybrid_vector_rule")
        self.assertEqual(first["result_count"], 5)
        self.assertEqual(first["index"]["document_count"], 12)
        self.assertEqual(first["index"]["vector_dimension"], 4)
        identifiers = {item["knowledge_id"] for item in first["results"]}
        self.assertIn("KB-CLASS-001", identifiers)
        self.assertIn("KB-SEGMENT-001", identifiers)
        self.assertEqual(embedder.calls, 3)
        self.assertEqual(first["results"], second["results"])

    def test_retrieval_falls_back_when_embedding_is_unavailable(self) -> None:
        retriever = KnowledgeRetrieverTool(embedder=BrokenEmbedder())
        result = retriever.run(
            self.summary,
            query="person 低置信度片段如何审核",
        )

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["strategy"], "lexical_class_metric")
        self.assertIn("embedding_unavailable", result["degraded_reason"])
        identifiers = {item["knowledge_id"] for item in result["results"]}
        self.assertIn("KB-CLASS-001", identifiers)
        self.assertIn("KB-SEGMENT-001", identifiers)
        self.assertTrue(
            all(item["match_reasons"] for item in result["results"])
        )

    def test_retrieval_without_embedder_uses_deterministic_rules(self) -> None:
        retriever = KnowledgeRetrieverTool()
        result = retriever.run(self.summary)

        self.assertEqual(result["status"], "degraded")
        self.assertIsNone(result["index"])
        identifiers = {item["knowledge_id"] for item in result["results"]}
        self.assertIn("KB-CORE-001", identifiers)
        self.assertIn("KB-REVIEW-001", identifiers)

    def test_empty_detection_summary_matches_empty_rule(self) -> None:
        payload = agent_input()
        for sample in payload["analysis_report"]["samples"]:
            sample["objects"] = []
            sample["object_count"] = 0
        payload["analysis_report"]["keyframes"][0]["objects"] = []
        summary = ReportParserTool().run(payload)
        result = KnowledgeRetrieverTool().run(summary)

        identifiers = {item["knowledge_id"] for item in result["results"]}
        self.assertEqual(summary["metrics"]["total_detections"], 0)
        self.assertIn("KB-QUALITY-001", identifiers)

    def test_invalid_visual_summary_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "metrics"):
            KnowledgeRetrieverTool().run({"job_id": "job_mock_001"})


if __name__ == "__main__":
    unittest.main()
