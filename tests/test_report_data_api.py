from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from app import create_app
from database import get_db
from services.agent_call_service import (
    complete_agent_call,
    create_agent_call,
    mark_agent_call_running,
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


class ReportDataApiTestCase(unittest.TestCase):
    MINIMAL_MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 32

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.app = create_app(
            {
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
        )
        self.owner = self.app.test_client()
        self.other = self.app.test_client()
        self.anonymous = self.app.test_client()
        self.owner_user = self._register(self.owner, "report-owner")
        self._register(self.other, "report-other")
        project = self.owner.post(
            "/api/projects",
            json={"name": "Report data"},
        ).get_json()["project"]
        self.project_id = project["id"]
        self.job_id = self._upload(self.owner, self.project_id)
        self.jobs = self.app.extensions["job_service"]

        fixture = (
            Path(__file__).parent
            / "fixtures"
            / "cv_analysis_report_v1.json"
        )
        report = json.loads(fixture.read_text(encoding="utf-8"))
        report["job_id"] = self.job_id
        report["duration"] = 20.0
        report["video"]["duration"] = 20.0
        report["model"]["path"] = str(self.root / "private-model.pt")
        report["segments"] = [
            {
                "id": "seg_cv_001",
                "order": 1,
                "start": 1.0,
                "end": 5.0,
                "score": 0.8,
                "source_keyframes": ["kf_001"],
                "reason": "CV evidence",
            },
            {
                "id": "seg_cv_002",
                "order": 2,
                "start": 4.0,
                "end": 8.0,
                "score": 0.7,
                "source_keyframes": [],
            },
        ]
        self.report = report
        self.jobs.write_report(self.job_id, report)
        self.jobs.update_job(
            self.job_id,
            status="completed",
            completed_at="2026-07-26T00:00:00",
            workspace_path=str(self.root),
            owner_id=self.owner_user["id"],
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
        pending = self.owner.patch(
            f"/api/jobs/{self.job_id}/review",
            json={"status": "pending"},
        )
        self.assertEqual(pending.status_code, 200, pending.get_json())
        review_segments = [
            {
                "id": "seg_review_001",
                "order": 1,
                "start": 10.0,
                "end": 15.0,
                "score": 0.9,
                "source_keyframes": [],
            }
        ]
        approved = self.owner.patch(
            f"/api/jobs/{self.job_id}/review",
            json={
                "status": "approved",
                "labels": ["approved-label"],
                "note": "latest note",
                "segments": review_segments,
            },
        )
        self.assertEqual(approved.status_code, 200, approved.get_json())

        # Keep the current CV report distinct from the immutable review snapshot.
        self.jobs.write_report(self.job_id, self.report)
        with self.app.app_context():
            call = create_agent_call(
                public_job_id=self.job_id,
                requested_by=self.owner_user["id"],
                prompt_version="v2",
            )
            mark_agent_call_running(call["id"])
            complete_agent_call(
                call["id"],
                status="completed",
                model_name="private-provider",
                output_summary="completed",
                tool_trace=[],
                references=[],
                result={
                    "segment_comments": [
                        {
                            "segment_id": "seg_cv_001",
                            "comment": "database-only comment",
                        }
                    ],
                    "private_path": str(self.root),
                },
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

    def _json_snapshot(self) -> dict[str, bytes]:
        job_dir = self.jobs.job_dir(self.job_id)
        return {
            path.relative_to(job_dir).as_posix(): path.read_bytes()
            for path in job_dir.rglob("*.json")
            if path.is_file()
        }

    def _write_agent_report(self) -> Path:
        path = self.jobs.agent_report_path(self.job_id)
        path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "job_id": self.job_id,
                    "status": "completed",
                    "provider": {
                        "type": "dify",
                        "model": "private-model",
                        "base_url": "http://private-provider.invalid",
                    },
                    "summary": "official summary",
                    "segment_comments": [
                        {
                            "segment_id": "seg_cv_001",
                            "title": "Segment one",
                            "comment": "official comment",
                            "score_reason": "evidence",
                            "review_status": "pass",
                            "evidence_refs": ["ev:segment:seg_cv_001"],
                        }
                    ],
                    "knowledge_refs": [
                        {
                            "knowledge_id": "KB-CORE-001",
                            "category": "review_policy",
                            "title": "Core rule",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return path

    def test_owner_receives_complete_whitelisted_contract_without_writes(
        self,
    ) -> None:
        self._write_agent_report()
        json_before = self._json_snapshot()
        database_before = self._database_snapshot()

        response = self.owner.get(
            f"/api/jobs/{self.job_id}/report-data"
        )
        statistics_response = self.owner.get(
            f"/api/jobs/{self.job_id}/statistics"
        )

        self.assertEqual(response.status_code, 200, response.get_json())
        payload = response.get_json()
        self.assertEqual(payload["contract_version"], "1.0")
        report_data = payload["report_data"]
        self.assertEqual(
            set(report_data),
            {
                "job",
                "video",
                "statistics",
                "cv",
                "agent",
                "review",
                "rough_cut",
            },
        )
        self.assertEqual(
            report_data["statistics"],
            statistics_response.get_json()["statistics"],
        )
        self.assertEqual(
            [item["id"] for item in report_data["cv"]["segments"]],
            ["seg_cv_001", "seg_cv_002"],
        )
        self.assertEqual(
            report_data["review"]["latest"]["segments"][0]["id"],
            "seg_review_001",
        )
        self.assertEqual(
            report_data["review"]["latest"]["status"],
            "approved",
        )
        self.assertEqual(
            report_data["review"]["status_counts"],
            {"pending": 1, "approved": 1, "rejected": 0},
        )
        self.assertEqual(
            report_data["agent"]["segment_comments"][0]["comment"],
            "official comment",
        )
        self.assertEqual(
            report_data["video"],
            {"filename": "demo.mp4", "duration_seconds": 20.0},
        )

        serialized = response.get_data(as_text=True)
        for forbidden in (
            str(self.root),
            "owner_id",
            "reviewer_id",
            "requested_by",
            "project_id",
            "asset_id",
            "job_row_id",
            "api_key",
            "private-provider.invalid",
            "database-only comment",
        ):
            self.assertNotIn(forbidden, serialized)
        self.assertEqual(self._json_snapshot(), json_before)
        self.assertEqual(self._database_snapshot(), database_before)

    def test_agent_call_result_is_not_used_without_official_report(
        self,
    ) -> None:
        response = self.owner.get(
            f"/api/jobs/{self.job_id}/report-data"
        )

        self.assertEqual(response.status_code, 200, response.get_json())
        agent = response.get_json()["report_data"]["agent"]
        self.assertEqual(agent["availability"], "unavailable")
        self.assertIsNone(agent["status"])
        self.assertIsNone(agent["summary"])
        self.assertEqual(agent["segment_comments"], [])
        self.assertEqual(agent["knowledge_refs"], [])
        self.assertEqual(agent["calls"]["history_count"], 1)
        self.assertNotIn(
            "database-only comment",
            response.get_data(as_text=True),
        )

    def test_corrupt_or_wrong_job_agent_report_is_invalid_not_fatal(
        self,
    ) -> None:
        path = self.jobs.agent_report_path(self.job_id)
        for content in (
            "{not-json",
            json.dumps(
                {
                    "job_id": "wrong-job",
                    "status": "completed",
                    "segment_comments": [],
                    "knowledge_refs": [],
                }
            ),
        ):
            with self.subTest(content=content):
                path.write_text(content, encoding="utf-8")
                response = self.owner.get(
                    f"/api/jobs/{self.job_id}/report-data"
                )
                self.assertEqual(
                    response.status_code, 200, response.get_json()
                )
                agent = response.get_json()["report_data"]["agent"]
                self.assertEqual(agent["availability"], "invalid")
                self.assertEqual(agent["segment_comments"], [])

    def test_video_filename_is_cross_platform_safe_basename(self) -> None:
        for original_name in (
            r"C:\private\assets\demo.mp4",
            "/srv/private/assets/demo.mp4",
        ):
            with self.subTest(original_name=original_name):
                self.jobs.update_job(
                    self.job_id,
                    original_asset_name=original_name,
                )
                response = self.owner.get(
                    f"/api/jobs/{self.job_id}/report-data"
                )
                self.assertEqual(
                    response.status_code, 200, response.get_json()
                )
                self.assertEqual(
                    response.get_json()["report_data"]["video"]["filename"],
                    "demo.mp4",
                )
                self.assertNotIn(
                    "private",
                    response.get_data(as_text=True),
                )

        for invalid_name in (None, "", "/", "\\", ".", ".."):
            with self.subTest(invalid_name=invalid_name):
                self.jobs.update_job(
                    self.job_id,
                    original_asset_name=invalid_name,
                )
                response = self.owner.get(
                    f"/api/jobs/{self.job_id}/report-data"
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.get_json()["report_data"]["video"]["filename"],
                    "demo.mp4",
                )

    def test_unsafe_agent_summary_degrades_only_agent_block(self) -> None:
        path = self._write_agent_report()
        report = json.loads(path.read_text(encoding="utf-8"))
        unsafe = r"path=C:\private\report.json"
        report["summary"] = unsafe
        path.write_text(json.dumps(report), encoding="utf-8")

        response = self.owner.get(
            f"/api/jobs/{self.job_id}/report-data"
        )

        self.assertEqual(response.status_code, 200, response.get_json())
        agent = response.get_json()["report_data"]["agent"]
        self.assertEqual(agent["availability"], "invalid")
        self.assertIsNone(agent["status"])
        self.assertIsNone(agent["summary"])
        self.assertEqual(agent["segment_comments"], [])
        self.assertEqual(agent["knowledge_refs"], [])
        self.assertEqual(agent["calls"]["history_count"], 1)
        self.assertNotIn(unsafe, response.get_data(as_text=True))
        self.assertNotIn("C:\\private", response.get_data(as_text=True))

    def test_unsafe_agent_comment_degrades_only_agent_block(self) -> None:
        path = self._write_agent_report()
        report = json.loads(path.read_text(encoding="utf-8"))
        unsafe = "/srv/private/report.json"
        report["segment_comments"][0]["comment"] = unsafe
        path.write_text(json.dumps(report), encoding="utf-8")

        response = self.owner.get(
            f"/api/jobs/{self.job_id}/report-data"
        )

        self.assertEqual(response.status_code, 200, response.get_json())
        agent = response.get_json()["report_data"]["agent"]
        self.assertEqual(agent["availability"], "invalid")
        self.assertIsNone(agent["status"])
        self.assertEqual(agent["segment_comments"], [])
        self.assertEqual(agent["calls"]["history_count"], 1)
        self.assertNotIn(unsafe, response.get_data(as_text=True))

    def test_forbidden_agent_field_degrades_only_agent_block(self) -> None:
        path = self._write_agent_report()
        report = json.loads(path.read_text(encoding="utf-8"))
        report["provider"]["api_key"] = "must-not-leak"
        path.write_text(json.dumps(report), encoding="utf-8")

        response = self.owner.get(
            f"/api/jobs/{self.job_id}/report-data"
        )

        self.assertEqual(response.status_code, 200, response.get_json())
        agent = response.get_json()["report_data"]["agent"]
        self.assertEqual(agent["availability"], "invalid")
        self.assertIsNone(agent["summary"])
        self.assertEqual(agent["calls"]["history_count"], 1)
        self.assertNotIn(
            "must-not-leak",
            response.get_data(as_text=True),
        )

    def test_rough_cut_requires_existing_safe_file_and_protected_url(
        self,
    ) -> None:
        relative = "result/rough_cut_16x9.mp4"
        self.jobs.update_job(self.job_id, rough_cut_file=relative)

        missing = self.owner.get(
            f"/api/jobs/{self.job_id}/report-data"
        ).get_json()["report_data"]["rough_cut"]
        self.assertEqual(
            missing,
            {
                "available": False,
                "filename": None,
                "download_url": None,
            },
        )

        output_path = self.jobs.job_dir(self.job_id) / relative
        output_path.write_bytes(b"rough-cut")
        response = self.owner.get(
            f"/api/jobs/{self.job_id}/report-data"
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        rough_cut = response.get_json()["report_data"]["rough_cut"]
        self.assertTrue(rough_cut["available"])
        self.assertEqual(rough_cut["filename"], "rough_cut_16x9.mp4")
        self.assertEqual(
            rough_cut["download_url"],
            f"/outputs/{self.job_id}/{relative}",
        )
        download = self.owner.get(rough_cut["download_url"])
        try:
            self.assertEqual(download.status_code, 200)
            self.assertEqual(download.data, b"rough-cut")
        finally:
            download.close()

    def test_authentication_and_owner_permissions_are_reused(self) -> None:
        anonymous = self.anonymous.get(
            f"/api/jobs/{self.job_id}/report-data"
        )
        forbidden = self.other.get(
            f"/api/jobs/{self.job_id}/report-data"
        )

        self.assertEqual(anonymous.status_code, 401)
        self.assertEqual(
            anonymous.get_json()["error_code"], "AUTH_REQUIRED"
        )
        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(
            forbidden.get_json()["error_code"], "JOB_ACCESS_DENIED"
        )

    def test_report_readiness_and_corrupt_report_errors_are_stable(
        self,
    ) -> None:
        not_completed = self._upload(self.owner, self.project_id)
        missing_report = self._upload(self.owner, self.project_id)
        self.jobs.update_job(
            missing_report,
            status="completed",
            completed_at="2026-07-26T00:00:00",
        )
        for job_id in (not_completed, missing_report):
            response = self.owner.get(
                f"/api/jobs/{job_id}/report-data"
            )
            self.assertEqual(response.status_code, 409)
            self.assertEqual(
                response.get_json()["error_code"], "REPORT_NOT_READY"
            )

        self.jobs.report_path(self.job_id).write_bytes(b"{not-json")
        corrupt = self.owner.get(
            f"/api/jobs/{self.job_id}/report-data"
        )
        self.assertEqual(corrupt.status_code, 500)
        self.assertFalse(corrupt.get_json()["ok"])
        self.assertIn("analysis_report.json", corrupt.get_json()["error"])
        self.assertNotIn(
            str(self.root), corrupt.get_data(as_text=True)
        )

    def test_empty_optional_data_returns_200_zero_values(self) -> None:
        job_id = self._upload(self.owner, self.project_id)
        report = {
            "job_id": job_id,
            "duration": 0.0,
            "samples": [],
            "keyframes": [],
            "segments": [],
            "output": {},
        }
        self.jobs.write_report(job_id, report)
        self.jobs.update_job(
            job_id,
            status="completed",
            completed_at="2026-07-26T00:00:00",
        )

        response = self.owner.get(f"/api/jobs/{job_id}/report-data")

        self.assertEqual(response.status_code, 200, response.get_json())
        data = response.get_json()["report_data"]
        self.assertEqual(data["cv"]["segments"], [])
        self.assertIsNone(data["review"]["latest"])
        self.assertEqual(data["review"]["history_count"], 0)
        self.assertEqual(
            data["review"]["status_counts"],
            {"pending": 0, "approved": 0, "rejected": 0},
        )
        self.assertEqual(data["agent"]["availability"], "unavailable")
        self.assertEqual(data["agent"]["calls"]["history_count"], 0)
        self.assertFalse(data["rough_cut"]["available"])


if __name__ == "__main__":
    unittest.main()
