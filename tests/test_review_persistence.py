from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import create_app
from database import get_db


class FakeAnalysisService:
    def shutdown(self, wait: bool = False) -> None:
        del wait


def fake_analysis_service_factory(*_args) -> FakeAnalysisService:
    return FakeAnalysisService()


class ReviewPersistenceTestCase(unittest.TestCase):
    MINIMAL_MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 32

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.outputs_dir = self.root / "outputs"
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE": self.root / "test.db",
                "SECRET_KEY": "test-secret-key",
                "LEGACY_USERS_FILE": self.root / "legacy-users.db",
                "OUTPUTS_DIR": self.outputs_dir,
                "MODELS_DIR": self.root / "models",
                "MODEL_PATH": self.root / "models" / "missing.pt",
                "BACKGROUND_WORKERS": 1,
                "ANALYSIS_SERVICE_FACTORY": fake_analysis_service_factory,
            }
        )
        self.owner = self.app.test_client()
        self.other = self.app.test_client()
        self.anonymous = self.app.test_client()
        self.owner_user = self._register(self.owner, "review-owner")
        self._register(self.other, "review-other")
        project = self._create_project(self.owner)
        self.job_id = self._upload_project_job(self.owner, project["id"])
        self.jobs = self.app.extensions["job_service"]
        self._write_initial_report(self.job_id)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _register(self, client, username: str) -> dict:
        response = client.post(
            "/api/auth/register",
            json={"username": username, "password": "test-passphrase"},
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["user"]

    def _create_project(self, client) -> dict:
        response = client.post("/api/projects", json={"name": "Review Project"})
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["project"]

    def _upload_project_job(self, client, project_id: int) -> str:
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

    def _upload_legacy_job(self) -> str:
        response = self.owner.post(
            "/api/jobs",
            data={
                "file": (io.BytesIO(self.MINIMAL_MP4), "legacy.mp4"),
                "project_name": "Legacy",
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        job_id = response.get_json()["job_id"]
        self._write_initial_report(job_id)
        return job_id

    def _write_initial_report(self, job_id: str) -> None:
        self.jobs.write_report(
            job_id,
            {
                "duration": 20.0,
                "keyframes": [],
                "segments": [],
                "recommended_clip": {
                    "start_time": 1.0,
                    "end_time": 4.0,
                    "output_ratio": "16:9",
                },
                "output": {},
            },
        )

    def _review_count(self) -> int:
        with self.app.app_context():
            row = get_db().execute(
                "SELECT COUNT(*) AS count FROM reviews"
            ).fetchone()
            return int(row["count"])

    def test_owner_creates_approved_review_with_relationship_and_json(self) -> None:
        response = self.owner.patch(
            f"/api/jobs/{self.job_id}/review",
            json={
                "status": "approved",
                "labels": [" 精彩击杀 ", "", "精彩击杀", "教学"],
                "note": " 人工确认 ",
                "segments": [
                    {
                        "id": "seg_001",
                        "start": 2.0,
                        "end": 6.0,
                        "order": 1,
                        "score": 0.9,
                    }
                ],
                "keyframes": [
                    {"timestamp": 3.0, "keep": True, "label": "关键帧"}
                ],
            },
        )

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertIn("report", response.get_json())
        latest = self.owner.get(
            f"/api/jobs/{self.job_id}/review/latest"
        ).get_json()["review"]
        self.assertEqual(latest["status"], "approved")
        self.assertEqual(latest["labels"], ["精彩击杀", "教学"])
        self.assertEqual(latest["note"], "人工确认")
        self.assertEqual(latest["segments"][0]["id"], "seg_001")
        self.assertTrue(latest["keyframes"][0]["keep"])
        self.assertNotIn("job_row_id", latest)

        with self.app.app_context():
            row = get_db().execute(
                """
                SELECT reviews.job_row_id, reviews.reviewer_id, jobs.id AS job_id
                FROM reviews
                JOIN jobs ON jobs.id = reviews.job_row_id
                WHERE jobs.public_job_id = ?
                """,
                (self.job_id,),
            ).fetchone()
        self.assertEqual(row["job_row_id"], row["job_id"])
        self.assertEqual(row["reviewer_id"], self.owner_user["id"])

    def test_pending_and_rejected_append_history_and_latest_is_newest(self) -> None:
        for status in ("pending", "rejected"):
            response = self.owner.patch(
                f"/api/jobs/{self.job_id}/review",
                json={"status": status},
            )
            self.assertEqual(response.status_code, 200, response.get_json())

        history_response = self.owner.get(
            f"/api/jobs/{self.job_id}/reviews"
        )
        latest_response = self.owner.get(
            f"/api/jobs/{self.job_id}/review/latest"
        )
        history = history_response.get_json()["reviews"]

        self.assertEqual(history_response.status_code, 200)
        self.assertEqual(
            [review["status"] for review in history],
            ["rejected", "pending"],
        )
        self.assertGreater(history[0]["id"], history[1]["id"])
        self.assertEqual(latest_response.get_json()["review"], history[0])
        self.assertEqual(history[0]["segments"], [])
        self.assertEqual(history[0]["keyframes"], [])
        with self.app.app_context():
            rows = get_db().execute(
                """
                SELECT segments_json, keyframes_json
                FROM reviews
                ORDER BY id
                """
            ).fetchall()
        self.assertTrue(all(row["segments_json"] is None for row in rows))
        self.assertTrue(all(row["keyframes_json"] is None for row in rows))

    def test_indexed_job_without_reviews_returns_empty_results(self) -> None:
        history = self.owner.get(f"/api/jobs/{self.job_id}/reviews")
        latest = self.owner.get(
            f"/api/jobs/{self.job_id}/review/latest"
        )

        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.get_json(), {"ok": True, "reviews": []})
        self.assertEqual(latest.status_code, 200)
        self.assertEqual(latest.get_json(), {"ok": True, "review": None})

    def test_invalid_status_returns_stable_error_without_changes(self) -> None:
        report_before = self.jobs.report_path(self.job_id).read_bytes()
        for status in (
            "pass",
            "failed",
            "reviewing",
            "keep",
            "skip",
            "",
            None,
            "APPROVED",
        ):
            with self.subTest(status=status):
                response = self.owner.patch(
                    f"/api/jobs/{self.job_id}/review",
                    json={"status": status},
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(
                    response.get_json()["error_code"],
                    "REVIEW_INPUT_INVALID",
                )
        self.assertEqual(self._review_count(), 0)
        self.assertEqual(
            self.jobs.report_path(self.job_id).read_bytes(),
            report_before,
        )

    def test_labels_and_note_validation(self) -> None:
        invalid_payloads = (
            {"status": "approved", "labels": "not-a-list"},
            {"status": "approved", "labels": [1]},
            {"status": "approved", "labels": ["x" * 51]},
            {
                "status": "approved",
                "labels": [f"label-{index}" for index in range(21)],
            },
            {"status": "approved", "note": 42},
            {"status": "approved", "note": "x" * 2001},
            {"labels": ["missing-status"]},
            {"note": "missing-status"},
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                response = self.owner.patch(
                    f"/api/jobs/{self.job_id}/review",
                    json=payload,
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(
                    response.get_json()["error_code"],
                    "REVIEW_INPUT_INVALID",
                )
        self.assertEqual(self._review_count(), 0)

    def test_other_user_and_anonymous_cannot_read_or_write_reviews(self) -> None:
        report_before = self.jobs.report_path(self.job_id).read_bytes()
        cases = (
            (
                self.other.patch(
                    f"/api/jobs/{self.job_id}/review",
                    json={"status": "approved"},
                ),
                403,
                "JOB_ACCESS_DENIED",
            ),
            (
                self.other.get(f"/api/jobs/{self.job_id}/reviews"),
                403,
                "JOB_ACCESS_DENIED",
            ),
            (
                self.other.get(f"/api/jobs/{self.job_id}/review/latest"),
                403,
                "JOB_ACCESS_DENIED",
            ),
            (
                self.anonymous.patch(
                    f"/api/jobs/{self.job_id}/review",
                    json={"status": "approved"},
                ),
                401,
                "AUTH_REQUIRED",
            ),
            (
                self.anonymous.get(f"/api/jobs/{self.job_id}/reviews"),
                401,
                "AUTH_REQUIRED",
            ),
        )
        for response, status_code, error_code in cases:
            self.assertEqual(response.status_code, status_code)
            self.assertEqual(response.get_json()["error_code"], error_code)
        self.assertEqual(self._review_count(), 0)
        self.assertEqual(
            self.jobs.report_path(self.job_id).read_bytes(),
            report_before,
        )

    def test_legacy_file_review_remains_compatible_without_status(self) -> None:
        job_id = self._upload_legacy_job()
        update = self.owner.patch(
            f"/api/jobs/{job_id}/review",
            json={
                "recommended_clip": {
                    "start_time": 4.0,
                    "end_time": 8.0,
                    "output_ratio": "16:9",
                }
            },
        )

        self.assertEqual(update.status_code, 200, update.get_json())
        self.assertEqual(
            update.get_json()["report"]["recommended_clip"]["start_time"],
            4.0,
        )
        self.assertEqual(
            self.owner.get(
                f"/api/jobs/{job_id}/reviews"
            ).get_json()["reviews"],
            [],
        )
        self.assertIsNone(
            self.owner.get(
                f"/api/jobs/{job_id}/review/latest"
            ).get_json()["review"]
        )

    def test_legacy_status_is_rejected_before_report_update(self) -> None:
        job_id = self._upload_legacy_job()
        report_before = self.jobs.report_path(job_id).read_bytes()

        response = self.owner.patch(
            f"/api/jobs/{job_id}/review",
            json={
                "status": "approved",
                "recommended_clip": {
                    "start_time": 5.0,
                    "end_time": 9.0,
                    "output_ratio": "16:9",
                },
            },
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.get_json()["error_code"],
            "REVIEW_PERSISTENCE_UNAVAILABLE",
        )
        self.assertEqual(
            self.jobs.report_path(job_id).read_bytes(),
            report_before,
        )

    def test_sqlite_insert_failure_leaves_report_unchanged(self) -> None:
        report_before = self.jobs.report_path(self.job_id).read_bytes()
        with self.app.app_context():
            get_db().execute(
                """
                CREATE TRIGGER reject_review
                BEFORE INSERT ON reviews
                BEGIN
                    SELECT RAISE(ABORT, 'forced review failure');
                END
                """
            )
            get_db().commit()

        response = self.owner.patch(
            f"/api/jobs/{self.job_id}/review",
            json={
                "status": "approved",
                "recommended_clip": {
                    "start_time": 6.0,
                    "end_time": 10.0,
                    "output_ratio": "16:9",
                },
            },
        )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(self._review_count(), 0)
        self.assertEqual(
            self.jobs.report_path(self.job_id).read_bytes(),
            report_before,
        )

    def test_report_write_failure_rolls_back_inserted_review(self) -> None:
        report_before = self.jobs.report_path(self.job_id).read_bytes()
        with patch.object(
            self.jobs,
            "update_report",
            side_effect=OSError("forced report failure"),
        ):
            response = self.owner.patch(
                f"/api/jobs/{self.job_id}/review",
                json={"status": "approved"},
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(self._review_count(), 0)
        self.assertEqual(
            self.jobs.report_path(self.job_id).read_bytes(),
            report_before,
        )


if __name__ == "__main__":
    unittest.main()
