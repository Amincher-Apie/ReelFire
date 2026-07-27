from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from app import create_app


class FakeAnalysisService:
    def shutdown(self, wait: bool = False) -> None:
        del wait


def fake_analysis_service_factory(*_args) -> FakeAnalysisService:
    return FakeAnalysisService()


class JobAccessPermissionsTestCase(unittest.TestCase):
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
        self.anonymous = self.app.test_client()
        self.client_a = self.app.test_client()
        self.client_b = self.app.test_client()
        self._register(self.client_a, "job-owner-a")
        self._register(self.client_b, "job-owner-b")
        self.project_a = self._create_project(self.client_a, "Project A")
        self.project_b = self._create_project(self.client_b, "Project B")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _register(self, client, username: str) -> None:
        response = client.post(
            "/api/auth/register",
            json={"username": username, "password": "test-passphrase"},
        )
        self.assertEqual(response.status_code, 201, response.get_json())

    def _create_project(self, client, name: str) -> dict:
        response = client.post("/api/projects", json={"name": name})
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
        jobs = self.app.extensions["job_service"]
        job_id, job_dir = jobs.reserve_workspace()
        (job_dir / "input" / "legacy.mp4").write_bytes(self.MINIMAL_MP4)
        jobs.create_job_record(
            job_id,
            "Legacy",
            "legacy.mp4",
            {},
        )
        return job_id

    def _complete_job(self, job_id: str) -> None:
        jobs = self.app.extensions["job_service"]
        jobs.write_report(
            job_id,
            {
                "duration": 12.0,
                "segments": [
                    {
                        "id": "seg_001",
                        "start": 1.0,
                        "end": 4.0,
                        "score": 0.8,
                        "order": 1,
                        "source_keyframes": [],
                    }
                ],
                "recommended_clip": {
                    "start_time": 1.0,
                    "end_time": 4.0,
                    "output_ratio": "16:9",
                },
                "output": {},
            },
        )
        jobs.update_job(
            job_id,
            status="completed",
            completed_at="2026-07-25T12:00:00",
        )

    def test_owner_can_access_detail_editor_api_and_contract_stays_v1(self) -> None:
        job_id = self._upload_project_job(self.client_a, self.project_a["id"])
        self._complete_job(job_id)

        detail = self.client_a.get(f"/api/jobs/{job_id}")
        editor = self.client_a.get(f"/api/jobs/{job_id}/editor")

        self.assertEqual(detail.status_code, 200, detail.get_json())
        self.assertEqual(editor.status_code, 200, editor.get_json())
        self.assertEqual(editor.get_json()["contract_version"], "1.0")
        self.assertEqual(editor.get_json()["job"]["job_id"], job_id)
        for internal_field in ("id", "asset_id", "job_row_id", "public_job_id"):
            self.assertNotIn(internal_field, detail.get_json()["job"])
            self.assertNotIn(internal_field, editor.get_json()["job"])

    def test_anonymous_project_job_requests_return_auth_required(self) -> None:
        job_id = self._upload_project_job(self.client_a, self.project_a["id"])
        api_requests = (
            self.anonymous.get(f"/api/jobs/{job_id}"),
            self.anonymous.get(f"/api/jobs/{job_id}/editor"),
            self.anonymous.get(f"/api/jobs/{job_id}/report"),
        )
        page_requests = (
            self.anonymous.get(f"/jobs/{job_id}/editor"),
            self.anonymous.get(f"/outputs/{job_id}/input/demo.mp4"),
        )

        for response in api_requests:
            self.assertEqual(response.status_code, 401, response.get_json())
            self.assertEqual(response.get_json()["error_code"], "AUTH_REQUIRED")
        for response in page_requests:
            self.assertEqual(response.status_code, 302)
            self.assertIn("/login?next=", response.headers["Location"])

    def test_other_user_cannot_read_or_mutate_project_job(self) -> None:
        job_id = self._upload_project_job(self.client_a, self.project_a["id"])
        jobs = self.app.extensions["job_service"]
        job_file = jobs.job_dir(job_id) / "job.json"
        before_job = job_file.read_bytes()
        before_files = {
            path.relative_to(jobs.job_dir(job_id)).as_posix()
            for path in jobs.job_dir(job_id).rglob("*")
        }

        responses = (
            self.client_b.get(f"/api/jobs/{job_id}"),
            self.client_b.get(f"/api/jobs/{job_id}/editor"),
            self.client_b.get(f"/api/jobs/{job_id}/report"),
            self.client_b.post(f"/api/jobs/{job_id}/analyze"),
            self.client_b.patch(
                f"/api/jobs/{job_id}/review",
                json={"recommended_clip": {"start_time": 1, "end_time": 2}},
            ),
            self.client_b.post(f"/api/jobs/{job_id}/rough-cut"),
            self.client_b.delete(f"/api/jobs/{job_id}"),
        )

        for response in responses:
            self.assertEqual(response.status_code, 403, response.get_json())
            self.assertEqual(
                response.get_json()["error_code"],
                "JOB_ACCESS_DENIED",
            )
        self.assertEqual(job_file.read_bytes(), before_job)
        self.assertEqual(
            {
                path.relative_to(jobs.job_dir(job_id)).as_posix()
                for path in jobs.job_dir(job_id).rglob("*")
            },
            before_files,
        )
        self.assertFalse(jobs.report_path(job_id).exists())
        self.assertEqual(jobs.get_job(job_id)["status"], "created")

    def test_editor_page_and_outputs_apply_owner_checks(self) -> None:
        job_id = self._upload_project_job(self.client_a, self.project_a["id"])

        for url in (
            f"/jobs/{job_id}/editor",
            f"/outputs/{job_id}/input/demo.mp4",
        ):
            denied = self.client_b.get(url)
            self.assertEqual(denied.status_code, 403, denied.get_json())
            self.assertEqual(
                denied.get_json()["error_code"],
                "JOB_ACCESS_DENIED",
            )

        page = self.client_a.get(f"/jobs/{job_id}/editor")
        video = self.client_a.get(f"/outputs/{job_id}/input/demo.mp4")
        partial_video = self.client_a.get(
            f"/outputs/{job_id}/input/demo.mp4",
            headers={"Range": "bytes=0-9"},
        )
        self.assertEqual(page.status_code, 200)
        self.assertEqual(video.status_code, 200)
        self.assertEqual(video.data, self.MINIMAL_MP4)
        self.assertEqual(partial_video.status_code, 206)
        self.assertEqual(partial_video.data, self.MINIMAL_MP4[:10])
        video.close()
        partial_video.close()

        traversal = self.client_a.get(
            f"/outputs/{job_id}/%2e%2e%2fjob.json"
        )
        self.assertEqual(traversal.status_code, 404)

    def test_unowned_legacy_file_job_is_not_exposed_to_accounts(self) -> None:
        job_id = self._upload_legacy_job()

        anonymous_detail = self.anonymous.get(f"/api/jobs/{job_id}")
        anonymous_page = self.anonymous.get(f"/jobs/{job_id}/editor")
        detail = self.client_a.get(f"/api/jobs/{job_id}")
        page = self.client_a.get(f"/jobs/{job_id}/editor")
        video = self.client_a.get(f"/outputs/{job_id}/input/legacy.mp4")

        self.assertEqual(anonymous_detail.status_code, 401)
        self.assertEqual(anonymous_page.status_code, 302)
        for response in (detail, page, video):
            self.assertEqual(response.status_code, 403, response.get_json())
            self.assertEqual(
                response.get_json()["error_code"],
                "JOB_ACCESS_DENIED",
            )
        video.close()

    def test_job_lists_hide_legacy_and_only_include_owned_indexed_jobs(self) -> None:
        legacy_id = self._upload_legacy_job()
        job_a = self._upload_project_job(self.client_a, self.project_a["id"])
        job_b = self._upload_project_job(self.client_b, self.project_b["id"])

        anonymous_response = self.anonymous.get("/api/jobs")
        ids_a = {
            job["job_id"]
            for job in self.client_a.get("/api/jobs").get_json()["jobs"]
        }
        ids_b = {
            job["job_id"]
            for job in self.client_b.get("/api/jobs").get_json()["jobs"]
        }

        self.assertEqual(anonymous_response.status_code, 401)
        self.assertEqual(
            anonymous_response.get_json()["error_code"],
            "AUTH_REQUIRED",
        )
        self.assertNotIn(legacy_id, ids_a | ids_b)
        self.assertEqual(ids_a, {job_a})
        self.assertEqual(ids_b, {job_b})

    def test_guest_sees_own_jobs_until_guest_identity_changes(self) -> None:
        guest = self.app.test_client()
        login = guest.post("/api/auth/guest", json={})
        self.assertEqual(login.status_code, 201, login.get_json())
        upload = guest.post(
            "/api/jobs",
            data={
                "file": (io.BytesIO(self.MINIMAL_MP4), "guest.mp4"),
                "project_name": "Guest current task",
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(upload.status_code, 201, upload.get_json())
        job_id = upload.get_json()["job_id"]

        self.assertEqual(
            [
                item["job_id"]
                for item in guest.get("/api/jobs").get_json()["jobs"]
            ],
            [job_id],
        )
        self.assertEqual(guest.get(f"/api/jobs/{job_id}").status_code, 200)

        next_guest = self.app.test_client()
        next_guest.post("/api/auth/guest", json={})
        self.assertEqual(next_guest.get("/api/jobs").get_json()["jobs"], [])
        denied = next_guest.get(f"/api/jobs/{job_id}")
        self.assertEqual(denied.status_code, 403, denied.get_json())


if __name__ == "__main__":
    unittest.main()
