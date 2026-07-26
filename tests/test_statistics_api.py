from __future__ import annotations

import copy
import io
import json
import math
import tempfile
import unittest
from pathlib import Path

from app import create_app
from database import get_db
from services.agent_call_service import (
    complete_agent_call,
    create_agent_call,
    fail_agent_call,
    mark_agent_call_running,
)
from services.statistics_service import (
    StatisticsValidationError,
    build_job_statistics,
)


class FakeAnalysisService:
    def shutdown(self, wait: bool = False) -> None:
        del wait


def fake_analysis_service_factory(*_args) -> FakeAnalysisService:
    return FakeAnalysisService()


class FakeAgentExecutionService:
    def enqueue(self, *_args, **_kwargs) -> None:
        return None

    def shutdown(self, wait: bool = False) -> None:
        del wait


def fake_agent_execution_service_factory(
    *_args,
) -> FakeAgentExecutionService:
    return FakeAgentExecutionService()


class StatisticsServiceTestCase(unittest.TestCase):
    def _build(
        self,
        report: dict,
        *,
        reviews: list[dict] | None = None,
        agent_calls: list[dict] | None = None,
    ) -> dict:
        return build_job_statistics(
            job_id="job_statistics",
            report=report,
            reviews=reviews or [],
            agent_calls=agent_calls or [],
        )

    def test_empty_business_data_returns_stable_zero_values(self) -> None:
        statistics = self._build({"duration": 0.0})

        self.assertEqual(
            statistics["timeline"],
            {
                "video_duration_seconds": 0.0,
                "sampled_frame_count": 0,
                "keyframe_count": 0,
            },
        )
        self.assertEqual(
            statistics["detections"],
            {
                "count_semantics": "sampled_detection_occurrences",
                "total_occurrences": 0,
                "confidence_observation_count": 0,
                "confidence": {
                    "minimum": None,
                    "maximum": None,
                    "average": None,
                },
                "categories": [],
            },
        )
        self.assertEqual(
            statistics["segments"],
            {
                "count": 0,
                "sum_duration_seconds": 0.0,
                "covered_duration_seconds": 0.0,
                "coverage_ratio": None,
            },
        )
        self.assertIsNone(statistics["reviews"]["latest_status"])
        self.assertIsNone(statistics["agent_calls"]["latest_status"])

    def test_detection_occurrences_confidence_and_category_sorting(self) -> None:
        report = {
            "duration": 10.0,
            "samples": [
                {
                    "objects": [
                        {"class": "person", "confidence": 0.6},
                        {"class": "car", "confidence": 0.8},
                        {"class": "", "confidence": 0.5},
                    ]
                },
                {
                    "objects": [
                        {"class": "person", "confidence": 0.9},
                        {"class": "car", "confidence": 0.4},
                        {"class": "alpha", "confidence": 0.7},
                    ]
                },
            ],
        }
        detections = self._build(report)["detections"]

        self.assertEqual(
            detections["count_semantics"],
            "sampled_detection_occurrences",
        )
        self.assertEqual(detections["total_occurrences"], 6)
        self.assertEqual(detections["confidence_observation_count"], 6)
        self.assertEqual(
            detections["confidence"],
            {"minimum": 0.4, "maximum": 0.9, "average": 0.65},
        )
        self.assertEqual(
            [item["name"] for item in detections["categories"]],
            ["car", "person", "alpha"],
        )
        self.assertEqual(
            detections["categories"][0],
            {
                "name": "car",
                "count": 2,
                "confidence_observation_count": 2,
                "confidence": {
                    "minimum": 0.4,
                    "maximum": 0.8,
                    "average": 0.6,
                },
            },
        )
        self.assertEqual(detections["categories"][1]["count"], 2)
        self.assertEqual(
            detections["categories"][1]["confidence"]["average"],
            0.75,
        )

    def test_invalid_confidences_are_excluded_not_replaced_with_zero(self) -> None:
        invalid = [True, math.nan, math.inf, -0.1, 1.1, None]
        objects = [
            {"class": "person", "confidence": value}
            for value in invalid
        ]
        objects.extend(
            [
                {"class": "person", "confidence": 0},
                {"class": "person", "confidence": 1},
            ]
        )
        detections = self._build(
            {"samples": [{"objects": objects}]}
        )["detections"]

        self.assertEqual(detections["total_occurrences"], 8)
        self.assertEqual(detections["confidence_observation_count"], 2)
        self.assertEqual(
            detections["confidence"],
            {"minimum": 0.0, "maximum": 1.0, "average": 0.5},
        )
        category = detections["categories"][0]
        self.assertEqual(category["count"], 8)
        self.assertEqual(category["confidence_observation_count"], 2)

        no_confidence = self._build(
            {
                "samples": [
                    {
                        "objects": [
                            {"class": "person", "confidence": True},
                            {"class": "person", "confidence": math.nan},
                        ]
                    }
                ]
            }
        )["detections"]
        self.assertEqual(
            no_confidence["confidence"],
            {"minimum": None, "maximum": None, "average": None},
        )

    def test_segments_sum_and_merged_coverage_are_distinct(self) -> None:
        segments = self._build(
            {
                "duration": 20.0,
                "segments": [
                    {"start": 0.0, "end": 5.0},
                    {"start": 3.0, "end": 8.0},
                    {"start": 8.0, "end": 10.0},
                    {"start": 15.0, "end": 18.0},
                    {"start": -1.0, "end": 2.0},
                    {"start": True, "end": 3.0},
                ],
            }
        )["segments"]

        self.assertEqual(segments["count"], 4)
        self.assertEqual(segments["sum_duration_seconds"], 15.0)
        self.assertEqual(segments["covered_duration_seconds"], 13.0)
        self.assertEqual(segments["coverage_ratio"], 0.65)

    def test_status_statistics_have_fixed_keys_and_existing_order(self) -> None:
        statistics = self._build(
            {},
            reviews=[
                {"status": "approved"},
                {"status": "pending"},
                {"status": "rejected"},
                {"status": "pending"},
            ],
            agent_calls=[
                {"status": "completed"},
                {"status": "failed"},
                {"status": "needs_review"},
                {"status": "running"},
                {"status": "queued"},
            ],
        )

        self.assertEqual(
            statistics["reviews"],
            {
                "history_count": 4,
                "status_counts": {
                    "pending": 2,
                    "approved": 1,
                    "rejected": 1,
                },
                "latest_status": "approved",
            },
        )
        self.assertEqual(
            statistics["agent_calls"],
            {
                "history_count": 5,
                "status_counts": {
                    "queued": 1,
                    "running": 1,
                    "completed": 1,
                    "needs_review": 1,
                    "failed": 1,
                },
                "latest_status": "completed",
            },
        )

    def test_invalid_structural_or_duration_data_is_rejected(self) -> None:
        invalid_reports = (
            {"duration": -1},
            {"duration": math.nan},
            {"duration": math.inf},
            {"duration": True},
            {"samples": None},
            {"keyframes": {}},
            {"segments": "invalid"},
            {"samples": [None]},
            {"samples": [{"objects": {}}]},
        )
        for report in invalid_reports:
            with self.subTest(report=report):
                with self.assertRaises(StatisticsValidationError):
                    self._build(report)

    def test_video_duration_fallback_and_missing_duration_are_explicit(self) -> None:
        fallback = self._build({"video": {"duration": 12.5}})
        missing = self._build(
            {"segments": [{"start": 1.0, "end": 4.0}]}
        )

        self.assertEqual(
            fallback["timeline"]["video_duration_seconds"],
            12.5,
        )
        self.assertIsNone(
            missing["timeline"]["video_duration_seconds"]
        )
        self.assertIsNone(missing["segments"]["coverage_ratio"])


class StatisticsApiTestCase(unittest.TestCase):
    MINIMAL_MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 32

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.config = {
            "TESTING": True,
            "DATABASE": self.root / "test.db",
            "SECRET_KEY": "test-secret",
            "LEGACY_USERS_FILE": self.root / "legacy.db",
            "OUTPUTS_DIR": self.root / "outputs",
            "MODELS_DIR": self.root / "models",
            "MODEL_PATH": self.root / "models" / "missing.pt",
            "BACKGROUND_WORKERS": 1,
            "ANALYSIS_SERVICE_FACTORY": fake_analysis_service_factory,
            "AGENT_EXECUTION_SERVICE_FACTORY": (
                fake_agent_execution_service_factory
            ),
        }
        self.app = create_app(self.config)
        self.owner = self.app.test_client()
        self.other = self.app.test_client()
        self.anonymous = self.app.test_client()
        self.owner_user = self._register(self.owner, "statistics-owner")
        self._register(self.other, "statistics-other")
        project = self.owner.post(
            "/api/projects",
            json={"name": "Statistics"},
        ).get_json()["project"]
        self.job_id = self._upload(self.owner, project["id"])
        self.jobs = self.app.extensions["job_service"]
        fixture = (
            Path(__file__).parent
            / "fixtures"
            / "cv_analysis_report_v1.json"
        )
        self.report = json.loads(fixture.read_text(encoding="utf-8"))
        self.report["job_id"] = self.job_id
        self.report["duration"] = 20.0
        self.report["video"]["duration"] = 20.0
        self.report["segments"] = [
            {
                "id": "seg_001",
                "order": 1,
                "start": 0.0,
                "end": 5.0,
                "score": 0.8,
                "source_keyframes": [],
            },
            {
                "id": "seg_002",
                "order": 2,
                "start": 3.0,
                "end": 8.0,
                "score": 0.7,
                "source_keyframes": [],
            },
            {
                "id": "seg_003",
                "order": 3,
                "start": 10.0,
                "end": 12.0,
                "score": 0.6,
                "source_keyframes": [],
            },
        ]
        self.jobs.write_report(self.job_id, self.report)
        self.jobs.update_job(
            self.job_id,
            status="completed",
            completed_at="2026-07-26T00:00:00",
        )
        self._create_history()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _register(self, client, username: str) -> dict:
        response = client.post(
            "/api/auth/register",
            json={"username": username, "password": "test-passphrase"},
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["user"]

    def _upload(self, client, project_id: int) -> str:
        response = client.post(
            "/api/jobs",
            data={
                "file": (io.BytesIO(self.MINIMAL_MP4), "demo.mp4"),
                "project_id": str(project_id),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["job_id"]

    def _create_history(self) -> None:
        for status in ("pending", "rejected", "pending", "approved"):
            response = self.owner.patch(
                f"/api/jobs/{self.job_id}/review",
                json={"status": status},
            )
            self.assertEqual(response.status_code, 200, response.get_json())

        with self.app.app_context():
            failed = create_agent_call(
                public_job_id=self.job_id,
                requested_by=self.owner_user["id"],
                prompt_version="v2",
            )
            fail_agent_call(
                failed["id"],
                error_code="EXPECTED",
                error_message="expected",
            )
            needs_review = create_agent_call(
                public_job_id=self.job_id,
                requested_by=self.owner_user["id"],
                prompt_version="v2",
            )
            mark_agent_call_running(needs_review["id"])
            complete_agent_call(
                needs_review["id"],
                status="needs_review",
                model_name="fake",
                output_summary="review",
                tool_trace=[],
                references=[],
                result={},
                duration_ms=1,
            )
            completed = create_agent_call(
                public_job_id=self.job_id,
                requested_by=self.owner_user["id"],
                prompt_version="v2",
            )
            mark_agent_call_running(completed["id"])
            complete_agent_call(
                completed["id"],
                status="completed",
                model_name="fake",
                output_summary="complete",
                tool_trace=[],
                references=[],
                result={},
                duration_ms=1,
            )

    def _database_snapshot(self) -> tuple[list[tuple], list[tuple]]:
        with self.app.app_context():
            connection = get_db()
            reviews = [
                tuple(row)
                for row in connection.execute(
                    "SELECT * FROM reviews ORDER BY id"
                ).fetchall()
            ]
            calls = [
                tuple(row)
                for row in connection.execute(
                    "SELECT * FROM agent_calls ORDER BY id"
                ).fetchall()
            ]
        return reviews, calls

    def test_owner_receives_real_statistics_without_side_effects(self) -> None:
        report_before = self.jobs.report_path(self.job_id).read_bytes()
        database_before = self._database_snapshot()

        response = self.owner.get(
            f"/api/jobs/{self.job_id}/statistics"
        )

        self.assertEqual(response.status_code, 200, response.get_json())
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["contract_version"], "1.0")
        statistics = payload["statistics"]
        self.assertEqual(
            set(statistics),
            {
                "job_id",
                "timeline",
                "detections",
                "segments",
                "reviews",
                "agent_calls",
            },
        )
        self.assertEqual(
            statistics["timeline"],
            {
                "video_duration_seconds": 20.0,
                "sampled_frame_count": 2,
                "keyframe_count": 1,
            },
        )
        self.assertEqual(
            statistics["detections"]["total_occurrences"],
            3,
        )
        self.assertEqual(
            statistics["detections"]["confidence"],
            {
                "minimum": 0.42,
                "maximum": 0.88,
                "average": 0.703333,
            },
        )
        self.assertEqual(
            [
                item["name"]
                for item in statistics["detections"]["categories"]
            ],
            ["person", "car"],
        )
        self.assertEqual(
            statistics["segments"],
            {
                "count": 3,
                "sum_duration_seconds": 12.0,
                "covered_duration_seconds": 10.0,
                "coverage_ratio": 0.5,
            },
        )
        self.assertEqual(
            statistics["reviews"]["status_counts"],
            {"pending": 2, "approved": 1, "rejected": 1},
        )
        self.assertEqual(
            statistics["reviews"]["latest_status"],
            "approved",
        )
        self.assertEqual(
            statistics["agent_calls"]["status_counts"],
            {
                "queued": 0,
                "running": 0,
                "completed": 1,
                "needs_review": 1,
                "failed": 1,
            },
        )
        self.assertEqual(
            statistics["agent_calls"]["latest_status"],
            "completed",
        )
        response_text = response.get_data(as_text=True)
        self.assertNotIn(str(self.root), response_text)
        self.assertNotIn("job_row_id", response_text)
        self.assertNotIn("owner_id", response_text)
        self.assertNotIn("requested_by", response_text)
        self.assertEqual(
            self.jobs.report_path(self.job_id).read_bytes(),
            report_before,
        )
        self.assertEqual(self._database_snapshot(), database_before)

    def test_authentication_and_owner_permissions_are_reused(self) -> None:
        anonymous = self.anonymous.get(
            f"/api/jobs/{self.job_id}/statistics"
        )
        forbidden = self.other.get(
            f"/api/jobs/{self.job_id}/statistics"
        )

        self.assertEqual(anonymous.status_code, 401)
        self.assertEqual(
            anonymous.get_json()["error_code"],
            "AUTH_REQUIRED",
        )
        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(
            forbidden.get_json()["error_code"],
            "JOB_ACCESS_DENIED",
        )

    def test_not_completed_and_missing_report_use_report_not_ready(self) -> None:
        project = self.owner.post(
            "/api/projects",
            json={"name": "Not Ready"},
        ).get_json()["project"]
        not_completed = self._upload(self.owner, project["id"])
        missing_report = self._upload(self.owner, project["id"])
        self.jobs.update_job(
            missing_report,
            status="completed",
            completed_at="2026-07-26T00:00:00",
        )

        responses = (
            self.owner.get(f"/api/jobs/{not_completed}/statistics"),
            self.owner.get(f"/api/jobs/{missing_report}/statistics"),
        )
        for response in responses:
            self.assertEqual(response.status_code, 409)
            self.assertEqual(
                response.get_json()["error_code"],
                "REPORT_NOT_READY",
            )

    def test_corrupt_report_returns_stable_json_error(self) -> None:
        self.jobs.report_path(self.job_id).write_bytes(b"{not-json")
        response = self.owner.get(
            f"/api/jobs/{self.job_id}/statistics"
        )

        self.assertEqual(response.status_code, 500)
        self.assertFalse(response.get_json()["ok"])
        self.assertIn("analysis_report.json", response.get_json()["error"])
        self.assertNotIn(str(self.root), response.get_data(as_text=True))

    def test_invalid_report_statistics_field_returns_stable_json_error(
        self,
    ) -> None:
        report = copy.deepcopy(self.report)
        report["duration"] = math.inf
        self.jobs.write_report(self.job_id, report)

        response = self.owner.get(
            f"/api/jobs/{self.job_id}/statistics"
        )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.get_json()["error"],
            "analysis_report.json 包含无效的统计字段",
        )


if __name__ == "__main__":
    unittest.main()
