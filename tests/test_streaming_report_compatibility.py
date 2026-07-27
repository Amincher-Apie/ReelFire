from __future__ import annotations

import copy
import json
import unittest

from services.report_data_service import build_job_report_data
from services.statistics_service import build_job_statistics


class StreamingReportCompatibilityTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.official_segment = {
            "id": "seg_official",
            "order": 1,
            "start": 2.0,
            "end": 6.0,
            "score": 0.875,
            "source_keyframes": ["kf_official"],
            "duration": 4.0,
            "peak_enemy_count": 0,
            "detected_classes": ["car", "person"],
            "enemy_classes_in_segment": [],
            "detections_summary": {
                "car": 1,
                "person": 1,
            },
            "reason": "Top-level finalized CV segment",
            "provisional": False,
            "chunk_id": "chunk_0001",
        }
        self.report = {
            "job_id": "job_streaming",
            "duration": 10.0,
            "analysis_mode": "streaming_chunks",
            "chunk_duration": 5.0,
            "sample_interval": 1.0,
            "analysis_chunks": [
                {
                    "id": "chunk_0002",
                    "status": "completed",
                    "sample_count": 99,
                    "samples": [
                        {
                            "objects": [
                                {
                                    "class": "private-progress-object",
                                    "confidence": 1.0,
                                }
                            ]
                        }
                    ],
                    "keyframes": [{"id": "kf_provisional"}],
                    "provisional_segments": [
                        {
                            "id": "seg_provisional",
                            "start": 8.0,
                            "end": 3.0,
                            "private_path": (
                                r"C:\private\provisional.json"
                            ),
                        }
                    ],
                }
            ],
            "provisional_segments": [
                {
                    "id": "seg_top_level_provisional",
                    "start": 7.0,
                    "end": 9.0,
                }
            ],
            "samples": [
                {
                    "frame_index": 0,
                    "timestamp": 2.0,
                    "objects": [
                        {"class": "car", "confidence": 0.8},
                        {"class": "person", "confidence": 0.6},
                    ],
                },
                {
                    "frame_index": 1,
                    "timestamp": 4.0,
                    "objects": [],
                },
            ],
            "keyframes": [
                {
                    "id": "kf_official",
                    "frame_index": 0,
                    "timestamp": 2.0,
                }
            ],
            "segments": [self.official_segment],
        }

    def _build_statistics(self) -> dict:
        return build_job_statistics(
            job_id="job_streaming",
            report=self.report,
            reviews=[],
            agent_calls=[],
        )

    def test_statistics_use_only_finalized_top_level_results(self) -> None:
        report_before = copy.deepcopy(self.report)

        statistics = self._build_statistics()

        self.assertEqual(statistics["timeline"]["sampled_frame_count"], 2)
        self.assertEqual(statistics["timeline"]["keyframe_count"], 1)
        self.assertEqual(statistics["detections"]["total_occurrences"], 2)
        self.assertEqual(
            [item["name"] for item in statistics["detections"]["categories"]],
            ["car", "person"],
        )
        self.assertEqual(
            statistics["segments"],
            {
                "count": 1,
                "sum_duration_seconds": 4.0,
                "covered_duration_seconds": 4.0,
                "coverage_ratio": 0.4,
            },
        )
        self.assertEqual(self.report, report_before)

    def test_report_data_excludes_streaming_progress_fields(self) -> None:
        statistics = self._build_statistics()

        report_data = build_job_report_data(
            job={
                "job_id": "job_streaming",
                "status": "completed",
                "created_at": "2026-07-27T00:00:00",
                "completed_at": "2026-07-27T00:01:00",
            },
            video={"filename": "streaming.mp4"},
            report=self.report,
            statistics=statistics,
            reviews=[],
            agent_report=None,
            agent_availability="unavailable",
            rough_cut={"available": False},
        )

        self.assertEqual(report_data["cv"]["summary"]["segment_count"], 1)
        self.assertEqual(
            report_data["cv"]["segments"],
            [
                {
                    key: value
                    for key, value in self.official_segment.items()
                    if key not in {"provisional", "chunk_id"}
                }
            ],
        )
        serialized = json.dumps(report_data, ensure_ascii=False)
        self.assertNotIn("analysis_chunks", serialized)
        self.assertNotIn("provisional_segments", serialized)
        self.assertNotIn("seg_provisional", serialized)
        self.assertNotIn(r"C:\private\provisional.json", serialized)
        self.assertNotIn('"provisional"', serialized)
        self.assertNotIn('"chunk_id"', serialized)


if __name__ == "__main__":
    unittest.main()
