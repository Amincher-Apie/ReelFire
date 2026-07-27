from __future__ import annotations

import io
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import create_app
from database import get_db
from services.job_service import JobPersistenceConsistencyError


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


class JobConsistencyTestCase(unittest.TestCase):
    MINIMAL_MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 32

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.config = {
            "TESTING": True,
            "DATABASE": self.root / "test.db",
            "SECRET_KEY": "consistency-secret",
            "LEGACY_USERS_FILE": self.root / "legacy.db",
            "OUTPUTS_DIR": self.root / "outputs",
            "MODELS_DIR": self.root / "models",
            "MODEL_PATH": self.root / "models" / "missing.pt",
            "BACKGROUND_WORKERS": 1,
            "AGENT_BACKGROUND_WORKERS": 1,
            "ANALYSIS_SERVICE_FACTORY": fake_analysis_service_factory,
            "AGENT_EXECUTION_SERVICE_FACTORY": (
                fake_agent_execution_service_factory
            ),
        }
        self.app = create_app(self.config)
        self.owner = self.app.test_client()
        self.other = self.app.test_client()
        self.owner_id = self._register(self.owner, "consistency-owner")
        self.other_id = self._register(self.other, "consistency-other")
        response = self.owner.post(
            "/api/projects",
            json={"name": "Consistency Project"},
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        self.project_id = int(response.get_json()["project"]["id"])

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _register(self, client, username: str) -> int:
        response = client.post(
            "/api/auth/register",
            json={"username": username, "password": "test-passphrase"},
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        return int(response.get_json()["user"]["id"])

    def _upload(self, name: str = "clip.mp4") -> str:
        response = self.owner.post(
            "/api/jobs",
            data={
                "file": (io.BytesIO(self.MINIMAL_MP4), name),
                "project_id": str(self.project_id),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        return str(response.get_json()["job_id"])

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.config["DATABASE"])
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _job_row(self, job_id: str) -> sqlite3.Row | None:
        connection = self._connect()
        try:
            return connection.execute(
                "SELECT * FROM jobs WHERE public_job_id = ?",
                (job_id,),
            ).fetchone()
        finally:
            connection.close()

    def _count(self, table: str, where: str = "", params=()) -> int:
        connection = self._connect()
        try:
            row = connection.execute(
                f"SELECT COUNT(*) AS count FROM {table} {where}",
                params,
            ).fetchone()
            return int(row["count"])
        finally:
            connection.close()

    def _report(self) -> dict:
        return {
            "duration": 10.0,
            "samples": [],
            "keyframes": [],
            "segments": [
                {
                    "id": "seg_001",
                    "order": 1,
                    "start": 1.0,
                    "end": 4.0,
                    "duration": 3.0,
                    "score": 0.8,
                    "source_keyframes": [],
                    "source": "cv",
                    "source_segment_ids": [],
                    "review": "pass",
                    "review_note": "",
                }
            ],
            "recommended_clip": {
                "start_time": 1.0,
                "end_time": 4.0,
                "output_ratio": "16:9",
            },
            "output": {},
        }

    def _complete_with_approved_review(self, job_id: str) -> None:
        jobs = self.app.extensions["job_service"]
        jobs.write_report(job_id, self._report())
        jobs.mark_completed(job_id, "analysis_report.json")
        response = self.owner.patch(
            f"/api/jobs/{job_id}/review",
            json={"status": "approved"},
        )
        self.assertEqual(response.status_code, 200, response.get_json())

    def test_upload_creates_matching_file_and_sqlite_index(self) -> None:
        job_id = self._upload()
        jobs = self.app.extensions["job_service"]
        job = jobs.get_job(job_id)
        row = self._job_row(job_id)

        self.assertEqual(job["status"], "created")
        self.assertEqual(row["status"], "created")
        self.assertEqual(
            row["job_json_path"],
            f"outputs/{job_id}/job.json",
        )
        self.assertIsNone(row["report_json_path"])
        self.assertIsNone(row["rough_cut_path"])
        self.assertEqual(int(row["project_id"]), self.project_id)
        self.assertEqual(self._count("assets"), 1)

    def test_sqlite_create_failure_discards_workspace_and_rows(self) -> None:
        before = set(self.config["OUTPUTS_DIR"].iterdir())
        with patch(
            "routes.api_routes.create_asset_and_job_index",
            side_effect=sqlite3.IntegrityError("forced create failure"),
        ):
            response = self.owner.post(
                "/api/jobs",
                data={
                    "file": (io.BytesIO(self.MINIMAL_MP4), "failed.mp4"),
                    "project_id": str(self.project_id),
                },
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(set(self.config["OUTPUTS_DIR"].iterdir()), before)
        self.assertEqual(self._count("jobs"), 0)
        self.assertEqual(self._count("assets"), 0)
        self.assertEqual(self._count("projects"), 1)

    def test_created_to_queued_is_synchronized(self) -> None:
        job_id = self._upload()
        job = self.app.extensions["job_service"].queue_for_analysis(job_id)

        self.assertEqual(job["status"], "queued")
        self.assertEqual(self._job_row(job_id)["status"], "queued")

    def test_queued_to_running_synchronizes_started_at(self) -> None:
        job_id = self._upload()
        jobs = self.app.extensions["job_service"]
        jobs.queue_for_analysis(job_id)
        job = jobs.mark_running(job_id)
        row = self._job_row(job_id)

        self.assertEqual(row["status"], "running")
        self.assertEqual(row["started_at"], job["started_at"])

    def test_running_to_completed_synchronizes_report_and_time(self) -> None:
        job_id = self._upload()
        jobs = self.app.extensions["job_service"]
        jobs.queue_for_analysis(job_id)
        jobs.mark_running(job_id)
        jobs.write_report(job_id, self._report())
        job = jobs.mark_completed(job_id, "analysis_report.json")
        row = self._job_row(job_id)

        self.assertEqual(row["status"], "completed")
        self.assertEqual(row["completed_at"], job["completed_at"])
        self.assertEqual(
            row["report_json_path"],
            f"outputs/{job_id}/analysis_report.json",
        )

    def test_running_to_failed_synchronizes_error(self) -> None:
        job_id = self._upload()
        jobs = self.app.extensions["job_service"]
        jobs.queue_for_analysis(job_id)
        jobs.mark_running(job_id)
        job = jobs.mark_failed(job_id, "模型推理失败", "MODEL_FAILURE")
        row = self._job_row(job_id)

        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["error_message"], job["error"])
        self.assertEqual(row["error_code"], "MODEL_FAILURE")

    def test_sqlite_sync_failure_restores_job_json(self) -> None:
        job_id = self._upload()
        jobs = self.app.extensions["job_service"]
        repository = self.app.extensions["job_index_repository"]
        before = jobs.get_job(job_id)

        with patch.object(
            repository,
            "sync_job",
            side_effect=sqlite3.OperationalError("forced sync failure"),
        ):
            with self.assertRaises(JobPersistenceConsistencyError):
                jobs.queue_for_analysis(job_id)

        self.assertEqual(jobs.get_job(job_id), before)
        self.assertEqual(self._job_row(job_id)["status"], "created")

    def test_startup_reconciles_completed_status_and_report_path(self) -> None:
        job_id = self._upload()
        jobs = self.app.extensions["job_service"]
        job_path = jobs.job_dir(job_id) / "job.json"
        job = jobs.get_job(job_id)
        job.update(
            {
                "status": "completed",
                "completed_at": "2026-07-27T12:00:00",
                "updated_at": "2026-07-27T12:00:00",
            }
        )
        job_path.write_text(
            json.dumps(job, ensure_ascii=False),
            encoding="utf-8",
        )
        jobs.report_path(job_id).write_text(
            json.dumps(self._report(), ensure_ascii=False),
            encoding="utf-8",
        )

        create_app(self.config)
        row = self._job_row(job_id)

        self.assertEqual(row["status"], "completed")
        self.assertEqual(
            row["report_json_path"],
            f"outputs/{job_id}/analysis_report.json",
        )

    def test_startup_marks_interrupted_file_and_index_failed(self) -> None:
        job_id = self._upload()
        jobs = self.app.extensions["job_service"]
        jobs.queue_for_analysis(job_id)

        restarted = create_app(self.config)
        restarted_job = restarted.extensions["job_service"].get_job(job_id)
        row = self._job_row(job_id)

        self.assertEqual(restarted_job["status"], "failed")
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["error_code"], "INTERRUPTED_BY_RESTART")

    def test_startup_marks_missing_workspace_index_failed(self) -> None:
        job_id = self._upload()
        jobs = self.app.extensions["job_service"]
        shutil.rmtree(jobs.job_dir(job_id))

        create_app(self.config)
        row = self._job_row(job_id)

        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["error_code"], "JOB_STORAGE_MISSING")
        self.assertIsNone(row["report_json_path"])
        self.assertIsNone(row["rough_cut_path"])

    def test_startup_restores_tombstone_when_job_index_still_exists(
        self,
    ) -> None:
        job_id = self._upload()
        jobs = self.app.extensions["job_service"]
        jobs.write_report(job_id, self._report())
        normal_directory = jobs.job_dir(job_id)
        input_files = list((normal_directory / "input").iterdir())
        self.assertEqual(len(input_files), 1)
        tombstone = self.config["OUTPUTS_DIR"] / (
            f".delete-{job_id}-{'a' * 32}"
        )
        os.replace(normal_directory, tombstone)

        with self.assertLogs("services.job_service", level="WARNING") as logs:
            rebuilt = create_app(self.config)

        rebuilt_jobs = rebuilt.extensions["job_service"]
        self.assertTrue(normal_directory.is_dir())
        self.assertFalse(tombstone.exists())
        self.assertTrue((normal_directory / "job.json").is_file())
        self.assertTrue((normal_directory / "analysis_report.json").is_file())
        self.assertEqual(len(list((normal_directory / "input").iterdir())), 1)
        self.assertIsNotNone(self._job_row(job_id))
        self.assertEqual(self._count("assets"), 1)
        self.assertNotEqual(
            self._job_row(job_id)["error_code"],
            "JOB_STORAGE_MISSING",
        )
        self.assertEqual(rebuilt_jobs.get_job(job_id)["status"], "created")
        self.assertTrue(any("恢复正常工作目录" in item for item in logs.output))

    def test_startup_preserves_ambiguous_tombstone_and_normal_directory(
        self,
    ) -> None:
        job_id = self._upload()
        jobs = self.app.extensions["job_service"]
        normal_directory = jobs.job_dir(job_id)
        tombstone = self.config["OUTPUTS_DIR"] / (
            f".delete-{job_id}-{'b' * 32}"
        )
        shutil.copytree(normal_directory, tombstone)

        with self.assertLogs("services.job_service", level="WARNING") as logs:
            rebuilt = create_app(self.config)

        self.assertTrue(normal_directory.is_dir())
        self.assertTrue(tombstone.is_dir())
        self.assertEqual(
            rebuilt.extensions["job_service"].get_job(job_id)["status"],
            "created",
        )
        self.assertIsNotNone(self._job_row(job_id))
        self.assertTrue(any("状态不明确" in item for item in logs.output))

    def test_missing_project_index_rejects_state_change_and_restores_job(
        self,
    ) -> None:
        job_id = self._upload()
        jobs = self.app.extensions["job_service"]
        connection = self._connect()
        try:
            connection.execute(
                "DELETE FROM jobs WHERE public_job_id = ?",
                (job_id,),
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaisesRegex(
            JobPersistenceConsistencyError,
            "SQLite",
        ):
            jobs.queue_for_analysis(job_id)

        self.assertEqual(jobs.get_job(job_id)["status"], "created")
        self.assertIsNone(self._job_row(job_id))

    def test_missing_project_index_rejects_report_and_removes_new_file(
        self,
    ) -> None:
        job_id = self._upload()
        jobs = self.app.extensions["job_service"]
        connection = self._connect()
        try:
            connection.execute(
                "DELETE FROM jobs WHERE public_job_id = ?",
                (job_id,),
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaisesRegex(
            JobPersistenceConsistencyError,
            "SQLite",
        ):
            jobs.write_report(job_id, self._report())

        self.assertFalse(jobs.report_path(job_id).exists())
        self.assertIsNone(self._job_row(job_id))

    def test_rough_cut_success_synchronizes_three_targets(self) -> None:
        job_id = self._upload()
        self._complete_with_approved_review(job_id)
        jobs = self.app.extensions["job_service"]

        def fake_export(_input, output, *_args):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"rough-cut")
            return output.resolve()

        with (
            patch(
                "routes.api_routes.is_ffmpeg_available",
                return_value=True,
            ),
            patch(
                "routes.api_routes.create_multi_segment_rough_cut",
                side_effect=fake_export,
            ),
        ):
            response = self.owner.post(
                f"/api/jobs/{job_id}/rough-cut",
                json={},
            )

        self.assertEqual(response.status_code, 200, response.get_json())
        relative = response.get_json()["rough_cut_file"]
        self.assertTrue((jobs.job_dir(job_id) / relative).is_file())
        self.assertEqual(jobs.get_job(job_id)["rough_cut_file"], relative)
        self.assertEqual(jobs.read_report(job_id)["output"]["video"], relative)
        self.assertEqual(
            self._job_row(job_id)["rough_cut_path"],
            f"outputs/{job_id}/{relative}",
        )

    def test_rough_cut_replace_failure_restores_all_metadata(self) -> None:
        job_id = self._upload()
        self._complete_with_approved_review(job_id)
        jobs = self.app.extensions["job_service"]
        job_before = jobs.get_job(job_id)
        report_before = jobs.read_report(job_id)
        real_replace = os.replace

        def fake_export(_input, output, *_args):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"staged")
            return output.resolve()

        def fail_publish(source, destination):
            if ".staged.mp4" in str(source):
                raise OSError("forced final replace failure")
            return real_replace(source, destination)

        with (
            patch(
                "routes.api_routes.is_ffmpeg_available",
                return_value=True,
            ),
            patch(
                "routes.api_routes.create_multi_segment_rough_cut",
                side_effect=fake_export,
            ),
            patch("routes.api_routes.os.replace", side_effect=fail_publish),
        ):
            response = self.owner.post(
                f"/api/jobs/{job_id}/rough-cut",
                json={},
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(jobs.get_job(job_id), job_before)
        self.assertEqual(jobs.read_report(job_id), report_before)
        self.assertIsNone(self._job_row(job_id)["rough_cut_path"])
        self.assertFalse(
            (jobs.job_dir(job_id) / "result" / "rough_cut_16x9.mp4").exists()
        )

    def test_rough_cut_backup_cleanup_failure_keeps_successful_result(
        self,
    ) -> None:
        job_id = self._upload()
        self._complete_with_approved_review(job_id)
        jobs = self.app.extensions["job_service"]
        output = jobs.job_dir(job_id) / "result" / "rough_cut_16x9.mp4"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"old-output")
        real_unlink = Path.unlink

        def fake_export(_input, target, *_args):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"new-output")
            return target.resolve()

        def fail_backup_unlink(path, missing_ok=False):
            if path.name.endswith(".backup"):
                raise PermissionError("forced backup cleanup failure")
            return real_unlink(path, missing_ok=missing_ok)

        with (
            patch(
                "routes.api_routes.is_ffmpeg_available",
                return_value=True,
            ),
            patch(
                "routes.api_routes.create_multi_segment_rough_cut",
                side_effect=fake_export,
            ),
            patch.object(
                Path,
                "unlink",
                autospec=True,
                side_effect=fail_backup_unlink,
            ),
            self.assertLogs("routes.api_routes", level="WARNING") as logs,
        ):
            response = self.owner.post(
                f"/api/jobs/{job_id}/rough-cut",
                json={},
            )

        self.assertEqual(response.status_code, 200, response.get_json())
        relative = response.get_json()["rough_cut_file"]
        self.assertEqual(output.read_bytes(), b"new-output")
        self.assertEqual(jobs.get_job(job_id)["rough_cut_file"], relative)
        self.assertEqual(jobs.read_report(job_id)["output"]["video"], relative)
        self.assertEqual(
            self._job_row(job_id)["rough_cut_path"],
            f"outputs/{job_id}/{relative}",
        )
        self.assertTrue(any("备份" in item for item in logs.output))

    def _insert_review_and_agent(self, job_id: str) -> tuple[int, int]:
        with self.app.app_context():
            connection = get_db()
            row = connection.execute(
                "SELECT id FROM jobs WHERE public_job_id = ?",
                (job_id,),
            ).fetchone()
            job_row_id = int(row["id"])
            review_id = int(
                connection.execute(
                    """
                    INSERT INTO reviews (
                        job_row_id, reviewer_id, status,
                        created_at, updated_at
                    )
                    VALUES (?, ?, 'approved', 'now', 'now')
                    """,
                    (job_row_id, self.owner_id),
                ).lastrowid
            )
            agent_id = int(
                connection.execute(
                    """
                    INSERT INTO agent_calls (
                        job_row_id, requested_by, status, created_at
                    )
                    VALUES (?, ?, 'failed', 'now')
                    """,
                    (job_row_id, self.owner_id),
                ).lastrowid
            )
            connection.commit()
        return review_id, agent_id

    def test_delete_cascades_rows_removes_asset_and_keeps_project(self) -> None:
        job_id = self._upload()
        jobs = self.app.extensions["job_service"]
        row = self._job_row(job_id)
        asset_id = int(row["asset_id"])
        self._insert_review_and_agent(job_id)

        response = self.owner.delete(f"/api/jobs/{job_id}")

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertFalse(jobs.job_dir(job_id).exists())
        self.assertIsNone(self._job_row(job_id))
        self.assertEqual(self._count("reviews"), 0)
        self.assertEqual(self._count("agent_calls"), 0)
        self.assertEqual(
            self._count("assets", "WHERE id = ?", (asset_id,)),
            0,
        )
        self.assertEqual(
            self._count("projects", "WHERE id = ?", (self.project_id,)),
            1,
        )

    def test_delete_one_job_does_not_affect_project_sibling(self) -> None:
        first = self._upload("first.mp4")
        second = self._upload("second.mp4")
        jobs = self.app.extensions["job_service"]

        response = self.owner.delete(f"/api/jobs/{first}")

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self._job_row(first))
        self.assertIsNotNone(self._job_row(second))
        self.assertTrue(jobs.job_dir(second).is_dir())
        self.assertEqual(self._count("projects"), 1)
        self.assertEqual(self._count("assets"), 1)

    def test_non_owner_delete_has_no_side_effect(self) -> None:
        job_id = self._upload()
        jobs = self.app.extensions["job_service"]
        before = self._job_row(job_id)

        response = self.other.delete(f"/api/jobs/{job_id}")

        self.assertEqual(response.status_code, 403)
        self.assertTrue(jobs.job_dir(job_id).is_dir())
        self.assertEqual(dict(self._job_row(job_id)), dict(before))

    def test_busy_delete_has_no_side_effect(self) -> None:
        job_id = self._upload()
        jobs = self.app.extensions["job_service"]
        jobs.queue_for_analysis(job_id)
        before = self._job_row(job_id)

        response = self.owner.delete(f"/api/jobs/{job_id}")

        self.assertEqual(response.status_code, 409)
        self.assertTrue(jobs.job_dir(job_id).is_dir())
        self.assertEqual(dict(self._job_row(job_id)), dict(before))

    def test_delete_database_failure_restores_everything(self) -> None:
        job_id = self._upload()
        jobs = self.app.extensions["job_service"]
        repository = self.app.extensions["job_index_repository"]
        self._insert_review_and_agent(job_id)
        counts = {
            table: self._count(table)
            for table in ("jobs", "assets", "reviews", "agent_calls")
        }

        with patch.object(
            repository,
            "delete_job_index",
            side_effect=sqlite3.OperationalError("forced delete failure"),
        ):
            response = self.owner.delete(f"/api/jobs/{job_id}")

        self.assertEqual(response.status_code, 500)
        self.assertTrue(jobs.job_dir(job_id).is_dir())
        for table, count in counts.items():
            self.assertEqual(self._count(table), count)
        self.assertEqual(
            [
                path
                for path in self.config["OUTPUTS_DIR"].iterdir()
                if path.name.startswith(".delete-")
            ],
            [],
        )

    def test_delete_false_index_result_restores_project_workspace(
        self,
    ) -> None:
        job_id = self._upload()
        jobs = self.app.extensions["job_service"]
        repository = self.app.extensions["job_index_repository"]

        with patch.object(
            repository,
            "delete_job_index",
            return_value=False,
        ):
            response = self.owner.delete(f"/api/jobs/{job_id}")

        self.assertEqual(response.status_code, 500, response.get_json())
        self.assertEqual(
            response.get_json()["error_code"],
            "JOB_PERSISTENCE_CONSISTENCY_ERROR",
        )
        self.assertTrue(jobs.job_dir(job_id).is_dir())
        self.assertIsNotNone(self._job_row(job_id))
        self.assertEqual(
            [
                path
                for path in self.config["OUTPUTS_DIR"].iterdir()
                if path.name.startswith(".delete-")
            ],
            [],
        )

    def test_delete_cleanup_failure_leaves_tombstone_for_startup(self) -> None:
        job_id = self._upload()
        jobs = self.app.extensions["job_service"]
        real_rmtree = shutil.rmtree

        def fail_tombstone(path, *args, **kwargs):
            if Path(path).name.startswith(".delete-"):
                raise OSError("forced tombstone cleanup failure")
            return real_rmtree(path, *args, **kwargs)

        with patch(
            "services.job_service.shutil.rmtree",
            side_effect=fail_tombstone,
        ):
            response = self.owner.delete(f"/api/jobs/{job_id}")

        self.assertEqual(response.status_code, 500)
        self.assertTrue(response.get_json()["cleanup_pending"])
        self.assertFalse(jobs.job_dir(job_id).exists())
        self.assertIsNone(self._job_row(job_id))
        tombstones = [
            path
            for path in self.config["OUTPUTS_DIR"].iterdir()
            if path.name.startswith(".delete-")
        ]
        self.assertEqual(len(tombstones), 1)

        create_app(self.config)
        self.assertFalse(tombstones[0].exists())
        self.assertIsNone(self._job_row(job_id))

    def test_legacy_job_is_not_auto_indexed(self) -> None:
        jobs = self.app.extensions["job_service"]
        legacy_id, _ = jobs.reserve_workspace()
        jobs.create_job_record(
            legacy_id,
            "Legacy",
            "legacy.mp4",
            {},
        )
        jobs.queue_for_analysis(legacy_id)
        jobs.write_report(legacy_id, self._report())

        create_app(self.config)

        self.assertIsNone(self._job_row(legacy_id))
        self.assertTrue(jobs.job_dir(legacy_id).is_dir())
        self.assertTrue(jobs.report_path(legacy_id).is_file())


if __name__ == "__main__":
    unittest.main()
