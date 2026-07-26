from __future__ import annotations

import io
import json
import math
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from app import create_app
from database import get_db
from services.editor_input_validation import (
    EditorSegmentValidationError,
    adapt_legacy_segments,
    validate_editor_segments,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "cv_segments_v1.json"


class FakeAnalysisService:
    def shutdown(self, wait: bool = False) -> None:
        del wait


def fake_analysis_service_factory(*_args) -> FakeAnalysisService:
    return FakeAnalysisService()


def load_segments() -> list[dict]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


class EditorSegmentValidationTestCase(unittest.TestCase):
    def test_valid_cv_segments_are_sorted_copied_and_preserve_extensions(self) -> None:
        source = load_segments()
        original = deepcopy(source)

        result = validate_editor_segments(source, 30.0)

        self.assertEqual([item["id"] for item in result], [
            "seg_001",
            "seg_002",
            "seg_003",
        ])
        self.assertEqual([item["order"] for item in result], [1, 2, 3])
        self.assertEqual(result[0]["detected_classes"], ["enemy"])
        self.assertEqual(result[0]["detections_summary"][0]["track_id"], 7)
        self.assertEqual(result[1]["peak_enemy_count"], 2)
        self.assertEqual(result[2]["reason"], "enemy_engagement")
        self.assertEqual(source, original)
        self.assertIsNot(result[0], source[1])
        self.assertIsNot(
            result[0]["detections_summary"],
            source[1]["detections_summary"],
        )

    def test_empty_segments_and_boundary_scores_are_valid(self) -> None:
        self.assertEqual(validate_editor_segments([], 30.0), [])
        segments = load_segments()
        segments[0]["score"] = 0
        segments[1]["score"] = 1

        result = validate_editor_segments(segments, 30.0)

        self.assertEqual(result[0]["score"], 1.0)
        self.assertEqual(result[1]["score"], 0.0)
        self.assertEqual(result[0]["source_keyframes"], [])

    def test_invalid_segments_are_rejected(self) -> None:
        valid = {
            "id": "seg_001",
            "order": 1,
            "start": 1.0,
            "end": 2.0,
            "score": 0.5,
            "source_keyframes": [],
        }
        cases: list[tuple[str, object]] = [
            ("segments not array", {}),
            ("segment not object", ["bad"]),
            ("missing id", [{key: value for key, value in valid.items() if key != "id"}]),
            ("empty id", [{**valid, "id": "  "}]),
            ("duplicate id", [valid, {**valid, "order": 2}]),
            (
                "missing order",
                [{key: value for key, value in valid.items() if key != "order"}],
            ),
            ("bool order", [{**valid, "order": True}]),
            ("zero order", [{**valid, "order": 0}]),
            ("negative order", [{**valid, "order": -1}]),
            ("float order", [{**valid, "order": 1.0}]),
            ("duplicate order", [valid, {**valid, "id": "seg_002"}]),
            ("bool start", [{**valid, "start": False}]),
            ("bool end", [{**valid, "end": True}]),
            ("nan start", [{**valid, "start": math.nan}]),
            ("infinite end", [{**valid, "end": math.inf}]),
            ("negative start", [{**valid, "start": -0.1}]),
            ("equal bounds", [{**valid, "start": 2.0, "end": 2.0}]),
            ("reversed bounds", [{**valid, "start": 3.0, "end": 2.0}]),
            ("end after video", [{**valid, "end": 31.0}]),
            (
                "missing score",
                [{key: value for key, value in valid.items() if key != "score"}],
            ),
            ("bool score", [{**valid, "score": True}]),
            ("negative score", [{**valid, "score": -0.1}]),
            ("score above one", [{**valid, "score": 1.1}]),
            (
                "missing source keyframes",
                [
                    {
                        key: value
                        for key, value in valid.items()
                        if key != "source_keyframes"
                    }
                ],
            ),
            ("null source keyframes", [{**valid, "source_keyframes": None}]),
            ("object source keyframes", [{**valid, "source_keyframes": {}}]),
            ("numeric source keyframe", [{**valid, "source_keyframes": [1]}]),
            ("empty source keyframe", [{**valid, "source_keyframes": [" "]}]),
        ]

        for label, value in cases:
            with self.subTest(label=label):
                with self.assertRaises(EditorSegmentValidationError):
                    validate_editor_segments(value, 30.0)

    def test_legacy_adapter_is_explicit_and_deterministic(self) -> None:
        legacy = [{"start": 1, "end": 2}]

        with self.assertRaises(EditorSegmentValidationError):
            validate_editor_segments(legacy, 10.0)

        first = adapt_legacy_segments(legacy, 10.0)
        second = adapt_legacy_segments(legacy, 10.0)
        self.assertEqual(first, second)
        self.assertEqual(
            first,
            [
                {
                    "id": "seg_001",
                    "order": 1,
                    "start": 1.0,
                    "end": 2.0,
                    "score": None,
                    "source_keyframes": [],
                }
            ],
        )
        self.assertEqual(adapt_legacy_segments(legacy, None), first)


class EditorSegmentApiTestCase(unittest.TestCase):
    MINIMAL_MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 32

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE": root / "test.db",
                "SECRET_KEY": "test-secret-key",
                "LEGACY_USERS_FILE": root / "legacy-users.db",
                "OUTPUTS_DIR": root / "outputs",
                "MODELS_DIR": root / "models",
                "MODEL_PATH": root / "models" / "missing.pt",
                "BACKGROUND_WORKERS": 1,
                "ANALYSIS_SERVICE_FACTORY": fake_analysis_service_factory,
            }
        )
        self.client = self.app.test_client()
        register = self.client.post(
            "/api/auth/register",
            json={"username": "segment-owner", "password": "test-passphrase"},
        )
        self.assertEqual(register.status_code, 201, register.get_json())
        project = self.client.post(
            "/api/projects",
            json={"name": "Segment Validation"},
        )
        self.assertEqual(project.status_code, 201, project.get_json())
        upload = self.client.post(
            "/api/jobs",
            data={
                "file": (io.BytesIO(self.MINIMAL_MP4), "demo.mp4"),
                "project_id": str(project.get_json()["project"]["id"]),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(upload.status_code, 201, upload.get_json())
        self.job_id = upload.get_json()["job_id"]
        self.jobs = self.app.extensions["job_service"]
        self._write_report(load_segments())

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write_report(self, segments: object) -> None:
        self.jobs.write_report(
            self.job_id,
            {
                "duration": 30.0,
                "segments": segments,
                "recommended_clip": {
                    "start_time": 1.0,
                    "end_time": 6.0,
                    "output_ratio": "16:9",
                },
                "output": {},
            },
        )
        self.jobs.update_job(
            self.job_id,
            status="completed",
            completed_at="2026-07-26T12:00:00",
        )

    def _review_count(self) -> int:
        with self.app.app_context():
            row = get_db().execute(
                "SELECT COUNT(*) AS count FROM reviews"
            ).fetchone()
            return int(row["count"])

    def test_editor_returns_three_sorted_highlights(self) -> None:
        response = self.client.get(f"/api/jobs/{self.job_id}/editor")

        self.assertEqual(response.status_code, 200, response.get_json())
        payload = response.get_json()
        self.assertIn("highlights", payload)
        self.assertNotIn("segments", payload)
        self.assertEqual(len(payload["highlights"]), 3)
        self.assertEqual(
            [item["id"] for item in payload["highlights"]],
            ["seg_001", "seg_002", "seg_003"],
        )
        self.assertEqual(payload["highlights"][0]["source_keyframes"], [])
        self.assertEqual(payload["highlights"][0]["score"], 1.0)
        self.assertEqual(payload["highlights"][2]["score"], 0.0)

    def test_patch_review_uses_the_same_rules_and_preserves_extensions(self) -> None:
        response = self.client.patch(
            f"/api/jobs/{self.job_id}/review",
            json={"segments": load_segments()},
        )

        self.assertEqual(response.status_code, 200, response.get_json())
        segments = response.get_json()["report"]["segments"]
        self.assertEqual([item["order"] for item in segments], [1, 2, 3])
        self.assertEqual(segments[0]["detections_summary"][0]["track_id"], 7)
        self.assertEqual(segments[1]["peak_enemy_count"], 2)

    def test_invalid_new_report_is_not_automatically_legacy(self) -> None:
        invalid = load_segments()
        del invalid[0]["id"]
        self._write_report(invalid)
        before = self.jobs.report_path(self.job_id).read_bytes()

        response = self.client.get(f"/api/jobs/{self.job_id}/editor")

        self.assertEqual(response.status_code, 400, response.get_json())
        self.assertIn(".id 必须存在", response.get_json()["error"])
        self.assertEqual(self.jobs.report_path(self.job_id).read_bytes(), before)

    def test_invalid_patch_does_not_write_report_or_review(self) -> None:
        before = self.jobs.report_path(self.job_id).read_bytes()
        invalid = load_segments()
        invalid[0]["score"] = math.inf

        response = self.client.patch(
            f"/api/jobs/{self.job_id}/review",
            json={"status": "approved", "segments": invalid},
        )

        self.assertEqual(response.status_code, 400, response.get_json())
        self.assertEqual(
            response.get_json()["error_code"],
            "REVIEW_INPUT_INVALID",
        )
        self.assertEqual(self._review_count(), 0)
        self.assertEqual(self.jobs.report_path(self.job_id).read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
