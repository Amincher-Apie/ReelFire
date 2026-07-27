import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from agent.tools.feedback_analyzer import (
    FeedbackAnalyzerTool,
    FeedbackValidationError,
)


ROOT = Path(__file__).parents[1]
EVENT_SCHEMA = ROOT / "agent" / "schemas" / "agent_feedback.schema.json"
SUMMARY_SCHEMA = (
    ROOT / "agent" / "schemas" / "agent_feedback_summary.schema.json"
)


def feedback_event(
    feedback_id: str,
    segment_id: str,
    *,
    decision: str = "adopted",
    rejection_reason: str | None = None,
    original: tuple[float, float] = (1.0, 6.0),
    final: tuple[float, float] = (1.0, 6.0),
    original_order: int = 1,
    final_order: int = 1,
    reexported: bool = False,
    recorded_at: str = "2026-07-27T10:00:00+08:00",
) -> dict:
    return {
        "schema_version": "1.0",
        "feedback_id": feedback_id,
        "job_id": "job_feedback_001",
        "segment_id": segment_id,
        "decision": decision,
        "rejection_reason": rejection_reason,
        "original_boundary": {"start": original[0], "end": original[1]},
        "final_boundary": {"start": final[0], "end": final[1]},
        "original_order": original_order,
        "final_order": final_order,
        "reexported": reexported,
        "recorded_at": recorded_at,
    }


class FeedbackAnalyzerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = FeedbackAnalyzerTool()
        self.event_schema = json.loads(EVENT_SCHEMA.read_text(encoding="utf-8"))
        self.summary_schema = json.loads(
            SUMMARY_SCHEMA.read_text(encoding="utf-8")
        )

    def test_feedback_contract_and_summary_statistics(self) -> None:
        records = [
            feedback_event(
                "fb-stale",
                "seg_001",
                decision="needs_review",
                recorded_at="2026-07-27T09:00:00+08:00",
            ),
            feedback_event(
                "fb-001",
                "seg_001",
                original=(1.0, 6.0),
                final=(0.5, 6.5),
                original_order=1,
                final_order=2,
                reexported=True,
            ),
            feedback_event(
                "fb-002",
                "seg_002",
                decision="rejected",
                rejection_reason="detection_error",
                original=(10.0, 20.0),
                final=(10.0, 20.0),
                original_order=2,
                final_order=1,
            ),
            feedback_event(
                "fb-003",
                "seg_003",
                decision="rejected",
                rejection_reason="boundary_error",
                original=(30.0, 40.0),
                final=(31.0, 39.0),
                original_order=3,
                final_order=3,
            ),
        ]
        validator = Draft202012Validator(
            self.event_schema,
            format_checker=FormatChecker(),
        )
        for record in records:
            validator.validate(record)

        result = self.tool.run(records)

        Draft202012Validator(self.summary_schema).validate(result)
        self.assertEqual(result["event_count"], 4)
        self.assertEqual(result["candidate_count"], 3)
        self.assertEqual(
            result["decision_counts"],
            {"adopted": 1, "needs_review": 0, "rejected": 2},
        )
        self.assertEqual(result["adoption_rate"], 0.333333)
        self.assertEqual(
            result["boundary_adjustments"],
            {
                "adjusted_count": 2,
                "adjustment_rate": 0.666667,
                "average_start_delta_seconds": 0.25,
                "average_end_delta_seconds": -0.25,
                "average_absolute_change_seconds": 1.5,
            },
        )
        self.assertEqual(result["order_changes"]["changed_count"], 2)
        self.assertEqual(result["reexports"]["count"], 1)
        titles = {
            item["title"] for item in result["rule_optimization_suggestions"]
        }
        self.assertIn("收紧候选生成规则", titles)
        self.assertIn("校准片段前后缓冲", titles)

    def test_empty_feedback_returns_needs_more_data(self) -> None:
        result = self.tool.run([])

        self.assertEqual(result["status"], "needs_more_data")
        self.assertEqual(result["candidate_count"], 0)
        self.assertEqual(result["adoption_rate"], 0.0)
        self.assertEqual(len(result["rule_optimization_suggestions"]), 1)

    def test_invalid_feedback_is_rejected(self) -> None:
        invalid_reason = feedback_event(
            "fb-001",
            "seg_001",
            rejection_reason="other",
        )
        with self.assertRaisesRegex(FeedbackValidationError, "仅拒绝时"):
            self.tool.run([invalid_reason])

        invalid_boundary = feedback_event("fb-002", "seg_002")
        invalid_boundary["final_boundary"] = {"start": 8.0, "end": 8.0}
        with self.assertRaisesRegex(FeedbackValidationError, "start < end"):
            self.tool.run([invalid_boundary])

        missing_timezone = feedback_event(
            "fb-003",
            "seg_003",
            recorded_at="2026-07-27T10:00:00",
        )
        with self.assertRaisesRegex(FeedbackValidationError, "必须包含时区"):
            self.tool.run([missing_timezone])

    def test_latest_feedback_uses_absolute_time_across_offsets(self) -> None:
        records = [
            feedback_event(
                "fb-later-local",
                "seg_001",
                decision="rejected",
                rejection_reason="other",
                recorded_at="2026-07-27T10:00:00+08:00",
            ),
            feedback_event(
                "fb-later-utc",
                "seg_001",
                decision="adopted",
                recorded_at="2026-07-27T03:00:00Z",
            ),
        ]

        result = self.tool.run(records)

        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["decision_counts"]["adopted"], 1)
        self.assertEqual(result["decision_counts"]["rejected"], 0)


if __name__ == "__main__":
    unittest.main()
