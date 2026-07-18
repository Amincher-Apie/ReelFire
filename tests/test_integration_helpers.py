from __future__ import annotations

import unittest

import numpy as np

from services.analysis_service import _annotate_frame, _bounded_clip, _select_keyframes


class ClipBoundaryTestCase(unittest.TestCase):
    def test_center_clip(self) -> None:
        self.assertEqual(_bounded_clip(50, 100, 30), (38.0, 68.0))

    def test_clip_near_start_keeps_target_duration(self) -> None:
        self.assertEqual(_bounded_clip(1, 100, 30), (0.0, 30.0))

    def test_clip_near_end_keeps_target_duration(self) -> None:
        self.assertEqual(_bounded_clip(99, 100, 30), (70.0, 100.0))

    def test_target_longer_than_video_uses_full_video(self) -> None:
        self.assertEqual(_bounded_clip(5, 10, 30), (0.0, 10.0))

    def test_invalid_duration_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _bounded_clip(0, 0, 30)


class KeyframeSelectionTestCase(unittest.TestCase):
    def test_nearby_high_scores_are_deduplicated(self) -> None:
        samples = [
            {"timestamp": 10.0, "highlight_score": 0.9},
            {"timestamp": 11.0, "highlight_score": 0.8},
            {"timestamp": 20.0, "highlight_score": 0.7},
        ]
        selected = _select_keyframes(samples, maximum=10, minimum_gap=5.0)
        self.assertEqual([item["timestamp"] for item in selected], [10.0, 20.0])


class DetectionAnnotationTestCase(unittest.TestCase):
    def test_draws_detection_without_mutating_source(self) -> None:
        source = np.zeros((80, 120, 3), dtype=np.uint8)
        annotated = _annotate_frame(
            source,
            [
                {
                    "bbox": [10, 20, 90, 70],
                    "class": "person",
                    "confidence": 0.91,
                }
            ],
        )
        self.assertFalse(np.any(source))
        self.assertTrue(np.any(annotated))


if __name__ == "__main__":
    unittest.main()
