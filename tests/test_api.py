from __future__ import annotations

import io
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app import create_app


class ApiTestCase(unittest.TestCase):
    MINIMAL_MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 32

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.outputs_dir = root / "outputs"
        self.app = create_app(
            {
                "TESTING": True,
                "OUTPUTS_DIR": self.outputs_dir,
                "MODELS_DIR": root / "models",
                "MODEL_PATH": root / "models" / "missing.pt",
                "MAX_CONTENT_LENGTH": 1024 * 1024,
                "BACKGROUND_WORKERS": 1,
            }
        )
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        self.app.extensions["analysis_service"].shutdown(wait=True)
        self.temporary.cleanup()

    def create_job(self, content: bytes = MINIMAL_MP4) -> str:
        response = self.client.post(
            "/api/jobs",
            data={
                "file": (io.BytesIO(content), "demo.mp4"),
                "project_name": "接口测试",
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["job_id"]

    def test_health(self) -> None:
        response = self.client.get("/api/health")
        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["model_ready"])

    def test_create_job_persists_workspace_and_metadata(self) -> None:
        job_id = self.create_job()
        job_dir = self.outputs_dir / job_id
        self.assertTrue((job_dir / "input" / "demo.mp4").is_file())
        self.assertTrue((job_dir / "keyframes").is_dir())
        self.assertTrue((job_dir / "result").is_dir())

        stored = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(stored["status"], "created")
        self.assertEqual(stored["settings"]["output_ratio"], "16:9")

        detail = self.client.get(f"/api/jobs/{job_id}")
        listing = self.client.get("/api/jobs")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.get_json()["jobs"][0]["job_id"], job_id)

    def test_create_job_without_file_returns_400(self) -> None:
        response = self.client.post("/api/jobs", data={})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()["ok"])

    def test_create_job_with_empty_file_returns_400_and_cleans_workspace(self) -> None:
        response = self.client.post(
            "/api/jobs",
            data={"file": (io.BytesIO(b""), "empty.mp4")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(list(self.outputs_dir.iterdir()), [])

    def test_create_job_with_unsupported_extension_returns_400(self) -> None:
        response = self.client.post(
            "/api/jobs",
            data={"file": (io.BytesIO(b"data"), "notes.txt")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 400)

    def test_create_job_rejects_spoofed_video_extension(self) -> None:
        response = self.client.post(
            "/api/jobs",
            data={"file": (io.BytesIO(b"\x89PNG\r\n\x1a\n"), "fake.mp4")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("文件内容", response.get_json()["error"])
        self.assertEqual(list(self.outputs_dir.iterdir()), [])

    def test_invalid_settings_return_400_without_crashing(self) -> None:
        response = self.client.post(
            "/api/jobs",
            data={
                "file": (io.BytesIO(b"data"), "demo.mp4"),
                "sample_interval": "not-a-number",
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 400)
        self.assertTrue(self.client.get("/api/health").get_json()["ok"])

    def test_get_missing_and_invalid_job_ids(self) -> None:
        missing = self.client.get("/api/jobs/20260101_000000_deadbeef")
        invalid = self.client.get("/api/jobs/not-a-job")
        traversal = self.client.get("/api/jobs/%2E%2E%2Ftest")
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(traversal.status_code, 404)
        self.assertFalse(traversal.get_json()["ok"])

    def test_delete_created_job(self) -> None:
        job_id = self.create_job()
        response = self.client.delete(f"/api/jobs/{job_id}")
        self.assertEqual(response.status_code, 200)
        self.assertFalse((self.outputs_dir / job_id).exists())

    def test_delete_queued_or_running_job_returns_409(self) -> None:
        job_id = self.create_job()
        jobs = self.app.extensions["job_service"]
        jobs.update_job(job_id, status="queued")
        response = self.client.delete(f"/api/jobs/{job_id}")
        self.assertEqual(response.status_code, 409)
        self.assertTrue((self.outputs_dir / job_id).is_dir())

    def test_analyze_corrupt_video_returns_202_then_persists_clear_failure(self) -> None:
        job_id = self.create_job()
        response = self.client.post(f"/api/jobs/{job_id}/analyze")
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.get_json()["status"], "queued")

        deadline = time.monotonic() + 3
        job = {}
        while time.monotonic() < deadline:
            job = self.client.get(f"/api/jobs/{job_id}").get_json()["job"]
            if job["status"] == "failed":
                break
            time.sleep(0.02)
        self.assertEqual(job["status"], "failed")
        self.assertIn("无法读取视频信息", job["error"])
        self.assertFalse((self.outputs_dir / job_id / "analysis_report.json").exists())

    def test_duplicate_analyze_returns_409(self) -> None:
        job_id = self.create_job()
        started = threading.Event()
        release = threading.Event()

        def blocking_analysis(*_args):
            started.set()
            release.wait(timeout=2)
            raise NotImplementedError("test release")

        with patch("services.analysis_service.analyze_video", side_effect=blocking_analysis):
            first = self.client.post(f"/api/jobs/{job_id}/analyze")
            self.assertEqual(first.status_code, 202)
            self.assertTrue(started.wait(timeout=1))
            duplicate = self.client.post(f"/api/jobs/{job_id}/analyze")
            self.assertEqual(duplicate.status_code, 409)
            release.set()

    def test_review_requires_existing_report_and_validates_boundaries(self) -> None:
        job_id = self.create_job()
        missing = self.client.patch(
            f"/api/jobs/{job_id}/review",
            json={"recommended_clip": {"start_time": 1, "end_time": 2}},
        )
        self.assertEqual(missing.status_code, 409)

        jobs = self.app.extensions["job_service"]
        jobs.write_report(job_id, {"duration": 10.0, "keyframes": []})
        jobs.update_job(job_id, status="completed", completed_at="2026-07-18T10:00:00")
        invalid = self.client.patch(
            f"/api/jobs/{job_id}/review",
            json={"recommended_clip": {"start_time": 8, "end_time": 11}},
        )
        self.assertEqual(invalid.status_code, 400)

        valid = self.client.patch(
            f"/api/jobs/{job_id}/review",
            json={
                "recommended_clip": {
                    "start_time": 2,
                    "end_time": 9,
                    "output_ratio": "9:16",
                }
            },
        )
        self.assertEqual(valid.status_code, 200)
        self.assertEqual(
            valid.get_json()["report"]["recommended_clip"]["output_ratio"],
            "9:16",
        )

        segments = self.client.patch(
            f"/api/jobs/{job_id}/review",
            json={
                "segments": [
                    {"id": "seg_001", "start": 1, "end": 7, "order": 1}
                ],
                "keyframes": [
                    {
                        "id": "kf_001",
                        "timestamp": 2,
                        "decision": "keep",
                        "label": "clutch",
                        "note": "test",
                        "order": 1,
                    }
                ],
            },
        )
        self.assertEqual(segments.status_code, 200, segments.get_json())
        report = segments.get_json()["report"]
        self.assertEqual(report["segments"][0]["start"], 1.0)
        self.assertEqual(report["recommended_clip"]["end_time"], 7.0)
        self.assertEqual(report["keyframes"][0]["decision"], "keep")

    def test_rough_cut_persists_output_in_job_and_report(self) -> None:
        job_id = self.create_job()
        jobs = self.app.extensions["job_service"]
        jobs.write_report(
            job_id,
            {
                "duration": 10.0,
                "recommended_clip": {
                    "start_time": 1.0,
                    "end_time": 8.0,
                    "output_ratio": "16:9",
                },
            },
        )
        jobs.update_job(job_id, status="completed", completed_at="2026-07-18T10:00:00")
        def fake_cut(_input, output, _start, _end, _ratio):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"mock mp4")
            return output

        with (
            patch("routes.api_routes.is_ffmpeg_available", return_value=True),
            patch("routes.api_routes.create_rough_cut", side_effect=fake_cut),
        ):
            response = self.client.post(f"/api/jobs/{job_id}/rough-cut")
        self.assertEqual(response.status_code, 200, response.get_json())
        relative = response.get_json()["rough_cut_file"]
        self.assertTrue((self.outputs_dir / job_id / relative).is_file())
        report = jobs.read_report(job_id)
        self.assertEqual(report["output"]["video"], relative)
        self.assertEqual(report["output"]["ratio"], "16:9")

    def test_startup_marks_interrupted_job_failed(self) -> None:
        job_id = self.create_job()
        jobs = self.app.extensions["job_service"]
        jobs.update_job(job_id, status="running", started_at="2026-07-18T10:00:00")
        root = Path(self.temporary.name)
        restarted = create_app(
            {
                "TESTING": True,
                "OUTPUTS_DIR": self.outputs_dir,
                "MODELS_DIR": root / "models",
                "MODEL_PATH": root / "models" / "missing.pt",
                "BACKGROUND_WORKERS": 1,
            }
        )
        try:
            recovered = restarted.extensions["job_service"].get_job(job_id)
            self.assertEqual(recovered["status"], "failed")
            self.assertIn("服务重启", recovered["error"])
        finally:
            restarted.extensions["analysis_service"].shutdown(wait=True)

    def test_corrupt_report_returns_json_500_and_service_survives(self) -> None:
        job_id = self.create_job()
        report_path = self.outputs_dir / job_id / "analysis_report.json"
        report_path.write_text("{broken", encoding="utf-8")
        response = self.client.get(f"/api/jobs/{job_id}/report")
        self.assertEqual(response.status_code, 500)
        self.assertFalse(response.get_json()["ok"])
        self.assertEqual(self.client.get("/api/health").status_code, 200)

    def test_unknown_route_and_wrong_method_use_json_errors(self) -> None:
        missing = self.client.get("/api/does-not-exist")
        wrong_method = self.client.put("/api/health")
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(wrong_method.status_code, 405)
        self.assertIsNotNone(missing.get_json())
        self.assertIsNotNone(wrong_method.get_json())


if __name__ == "__main__":
    unittest.main()
