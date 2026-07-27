from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from app import create_app
from database import get_db
from services.project_service import (
    ProjectNotEmptyError,
    delete_empty_project,
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


class ProjectLifecycleTestCase(unittest.TestCase):
    MINIMAL_MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 32

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.config = {
            "TESTING": True,
            "DATABASE": self.root / "test.db",
            "SECRET_KEY": "project-lifecycle-secret",
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
        self.owner_id = self._register(self.owner, "project-owner")
        self.other_id = self._register(self.other, "project-other")
        self.project = self._create_project(
            self.owner,
            "Owner Project",
            description="Initial",
            game_type="valorant",
        )
        self.other_project = self._create_project(
            self.other,
            "Other Project",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _register(self, client, username: str) -> int:
        response = client.post(
            "/api/auth/register",
            json={"username": username, "password": "test-passphrase"},
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        return int(response.get_json()["user"]["id"])

    def _create_project(self, client, name: str, **fields) -> dict:
        response = client.post(
            "/api/projects",
            json={"name": name, **fields},
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["project"]

    def _upload(self, client, project_id: int, name: str = "clip.mp4"):
        return client.post(
            "/api/jobs",
            data={
                "file": (io.BytesIO(self.MINIMAL_MP4), name),
                "project_id": str(project_id),
            },
            content_type="multipart/form-data",
        )

    def _job_ids(self, project_id: int) -> list[str]:
        with self.app.app_context():
            rows = get_db().execute(
                """
                SELECT public_job_id
                FROM jobs
                WHERE project_id = ?
                ORDER BY id
                """,
                (project_id,),
            ).fetchall()
        return [str(row["public_job_id"]) for row in rows]

    def _set_job_index(
        self,
        job_id: str,
        *,
        status: str,
        report: str | None = None,
        rough_cut: str | None = None,
    ) -> None:
        with self.app.app_context():
            connection = get_db()
            connection.execute(
                """
                UPDATE jobs
                SET status = ?,
                    report_json_path = ?,
                    rough_cut_path = ?,
                    error_code = CASE WHEN ? = 'failed'
                        THEN 'TEST_FAILURE' ELSE NULL END,
                    error_message = CASE WHEN ? = 'failed'
                        THEN '测试失败信息' ELSE NULL END,
                    updated_at = '2026-07-27T12:00:00+00:00',
                    completed_at = CASE
                        WHEN ? IN ('completed', 'failed')
                        THEN '2026-07-27T12:00:00+00:00'
                        ELSE NULL
                    END
                WHERE public_job_id = ?
                """,
                (
                    status,
                    report,
                    rough_cut,
                    status,
                    status,
                    status,
                    job_id,
                ),
            )
            connection.commit()

    def test_get_own_project_detail_without_jobs_has_fixed_zero_counts(
        self,
    ) -> None:
        response = self.owner.get(f"/api/projects/{self.project['id']}")

        self.assertEqual(response.status_code, 200, response.get_json())
        project = response.get_json()["project"]
        self.assertEqual(project["name"], "Owner Project")
        self.assertEqual(project["job_count"], 0)
        self.assertEqual(
            project["jobs_by_status"],
            {
                "created": 0,
                "queued": 0,
                "running": 0,
                "completed": 0,
                "failed": 0,
            },
        )
        self.assertNotIn("owner_id", project)

    def test_project_detail_counts_jobs_by_sqlite_status(self) -> None:
        first = self._upload(self.owner, self.project["id"], "one.mp4")
        second = self._upload(self.owner, self.project["id"], "two.mp4")
        self.assertEqual(first.status_code, 201, first.get_json())
        self.assertEqual(second.status_code, 201, second.get_json())
        job_ids = self._job_ids(self.project["id"])
        self._set_job_index(job_ids[0], status="completed")
        self._set_job_index(job_ids[1], status="failed")

        project = self.owner.get(
            f"/api/projects/{self.project['id']}"
        ).get_json()["project"]

        self.assertEqual(project["job_count"], 2)
        self.assertEqual(project["jobs_by_status"]["completed"], 1)
        self.assertEqual(project["jobs_by_status"]["failed"], 1)
        self.assertEqual(project["jobs_by_status"]["created"], 0)

    def test_project_detail_distinguishes_missing_and_other_owner(self) -> None:
        missing = self.owner.get("/api/projects/999999")
        forbidden = self.owner.get(
            f"/api/projects/{self.other_project['id']}"
        )

        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.get_json()["error_code"], "PROJECT_NOT_FOUND")
        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(
            forbidden.get_json()["error_code"],
            "PROJECT_ACCESS_DENIED",
        )

    def test_update_project_name_description_and_game_type(self) -> None:
        response = self.owner.patch(
            f"/api/projects/{self.project['id']}",
            json={
                "name": "  Renamed Project  ",
                "description": "Updated description",
                "game_type": "csgo",
            },
        )

        self.assertEqual(response.status_code, 200, response.get_json())
        project = response.get_json()["project"]
        self.assertEqual(project["name"], "Renamed Project")
        self.assertEqual(project["description"], "Updated description")
        self.assertEqual(project["game_type"], "csgo")
        self.assertNotEqual(project["updated_at"], self.project["updated_at"])
        self.assertNotIn("owner_id", project)

    def test_update_project_accepts_null_optional_fields(self) -> None:
        response = self.owner.patch(
            f"/api/projects/{self.project['id']}",
            json={"description": None, "game_type": None},
        )

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertIsNone(response.get_json()["project"]["description"])
        self.assertIsNone(response.get_json()["project"]["game_type"])

    def test_update_project_preserves_empty_optional_strings(self) -> None:
        response = self.owner.patch(
            f"/api/projects/{self.project['id']}",
            json={"description": "", "game_type": ""},
        )

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["project"]["description"], "")
        self.assertEqual(response.get_json()["project"]["game_type"], "")

    def test_update_rejects_non_object_empty_and_unknown_fields(self) -> None:
        cases = (
            ([], "PROJECT_INPUT_INVALID"),
            ({}, "PROJECT_INPUT_INVALID"),
            ({"owner_id": self.other_id}, "PROJECT_INPUT_INVALID"),
            ({"id": 100}, "PROJECT_INPUT_INVALID"),
            ({"unexpected": True}, "PROJECT_INPUT_INVALID"),
        )
        for payload, error_code in cases:
            with self.subTest(payload=payload):
                response = self.owner.patch(
                    f"/api/projects/{self.project['id']}",
                    json=payload,
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.get_json()["error_code"], error_code)

    def test_update_rejects_invalid_field_values(self) -> None:
        cases = (
            {"name": "  "},
            {"name": "x" * 101},
            {"description": "x" * 1001},
            {"description": []},
            {"game_type": "x" * 51},
            {"game_type": 1},
            {"status": "deleted"},
            {"status": None},
        )
        for payload in cases:
            with self.subTest(payload=payload):
                response = self.owner.patch(
                    f"/api/projects/{self.project['id']}",
                    json=payload,
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(
                    response.get_json()["error_code"],
                    "PROJECT_INPUT_INVALID",
                )

    def test_other_owner_cannot_update_project(self) -> None:
        response = self.other.patch(
            f"/api/projects/{self.project['id']}",
            json={"name": "Stolen"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.get_json()["error_code"],
            "PROJECT_ACCESS_DENIED",
        )

    def test_archive_blocks_upload_and_active_restore_allows_upload(self) -> None:
        archived = self.owner.patch(
            f"/api/projects/{self.project['id']}",
            json={"status": "archived"},
        )
        before = set(self.config["OUTPUTS_DIR"].iterdir())
        blocked = self._upload(self.owner, self.project["id"])

        self.assertEqual(archived.status_code, 200, archived.get_json())
        self.assertEqual(blocked.status_code, 409, blocked.get_json())
        self.assertEqual(
            blocked.get_json()["error_code"],
            "PROJECT_ARCHIVED",
        )
        self.assertEqual(set(self.config["OUTPUTS_DIR"].iterdir()), before)
        self.assertEqual(self._job_ids(self.project["id"]), [])

        restored = self.owner.patch(
            f"/api/projects/{self.project['id']}",
            json={"status": "active"},
        )
        uploaded = self._upload(self.owner, self.project["id"])
        self.assertEqual(restored.status_code, 200, restored.get_json())
        self.assertEqual(uploaded.status_code, 201, uploaded.get_json())

    def test_project_job_list_returns_safe_sqlite_summaries(self) -> None:
        response = self._upload(self.owner, self.project["id"])
        self.assertEqual(response.status_code, 201, response.get_json())
        job_id = response.get_json()["job_id"]
        self._set_job_index(
            job_id,
            status="completed",
            report=f"outputs/{job_id}/analysis_report.json",
            rough_cut=f"outputs/{job_id}/result/rough_cut.mp4",
        )

        listing = self.owner.get(
            f"/api/projects/{self.project['id']}/jobs"
        )

        self.assertEqual(listing.status_code, 200, listing.get_json())
        payload = listing.get_json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["limit"], 50)
        self.assertEqual(payload["offset"], 0)
        summary = payload["jobs"][0]
        self.assertEqual(summary["job_id"], job_id)
        self.assertTrue(summary["report_available"])
        self.assertTrue(summary["rough_cut_available"])
        self.assertNotIn("job_json_path", summary)
        self.assertNotIn("report_json_path", summary)
        self.assertNotIn("rough_cut_path", summary)

    def test_project_job_list_supports_status_filter(self) -> None:
        self.assertEqual(
            self._upload(self.owner, self.project["id"], "one.mp4").status_code,
            201,
        )
        self.assertEqual(
            self._upload(self.owner, self.project["id"], "two.mp4").status_code,
            201,
        )
        job_ids = self._job_ids(self.project["id"])
        self._set_job_index(job_ids[1], status="failed")

        response = self.owner.get(
            f"/api/projects/{self.project['id']}/jobs?status=failed"
        )

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["total"], 1)
        self.assertEqual(response.get_json()["jobs"][0]["status"], "failed")
        self.assertEqual(
            response.get_json()["jobs"][0]["error_code"],
            "TEST_FAILURE",
        )

    def test_project_job_list_supports_limit_and_offset(self) -> None:
        self.assertEqual(
            self._upload(self.owner, self.project["id"], "one.mp4").status_code,
            201,
        )
        self.assertEqual(
            self._upload(self.owner, self.project["id"], "two.mp4").status_code,
            201,
        )
        first = self.owner.get(
            f"/api/projects/{self.project['id']}/jobs?limit=1&offset=0"
        ).get_json()
        second = self.owner.get(
            f"/api/projects/{self.project['id']}/jobs?limit=1&offset=1"
        ).get_json()

        self.assertEqual(first["total"], 2)
        self.assertEqual(second["total"], 2)
        self.assertEqual(first["limit"], 1)
        self.assertEqual(second["offset"], 1)
        self.assertNotEqual(
            first["jobs"][0]["job_id"],
            second["jobs"][0]["job_id"],
        )

    def test_project_job_list_rejects_invalid_queries(self) -> None:
        queries = (
            "status=unknown",
            "status=",
            "limit=0",
            "limit=101",
            "limit=abc",
            "offset=-1",
            "offset=1.5",
        )
        for query in queries:
            with self.subTest(query=query):
                response = self.owner.get(
                    f"/api/projects/{self.project['id']}/jobs?{query}"
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(
                    response.get_json()["error_code"],
                    "PROJECT_INPUT_INVALID",
                )

    def test_other_owner_cannot_list_project_jobs(self) -> None:
        response = self.other.get(
            f"/api/projects/{self.project['id']}/jobs"
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.get_json()["error_code"],
            "PROJECT_ACCESS_DENIED",
        )

    def test_delete_empty_project_succeeds_without_touching_files(self) -> None:
        sentinel = self.config["OUTPUTS_DIR"] / "unrelated"
        sentinel.mkdir()

        response = self.owner.delete(
            f"/api/projects/{self.project['id']}"
        )

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertTrue(sentinel.is_dir())
        missing = self.owner.get(f"/api/projects/{self.project['id']}")
        self.assertEqual(missing.status_code, 404)

    def test_delete_nonempty_project_returns_project_not_empty(self) -> None:
        uploaded = self._upload(self.owner, self.project["id"])
        self.assertEqual(uploaded.status_code, 201, uploaded.get_json())

        response = self.owner.delete(
            f"/api/projects/{self.project['id']}"
        )

        self.assertEqual(response.status_code, 409, response.get_json())
        self.assertEqual(
            response.get_json()["error_code"],
            "PROJECT_NOT_EMPTY",
        )
        self.assertIn("先", response.get_json()["error"])
        self.assertIsNotNone(
            self.owner.get(f"/api/projects/{self.project['id']}").get_json()
        )

    def test_delete_other_and_missing_projects_are_distinguished(self) -> None:
        forbidden = self.other.delete(
            f"/api/projects/{self.project['id']}"
        )
        missing = self.owner.delete("/api/projects/999999")

        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(
            forbidden.get_json()["error_code"],
            "PROJECT_ACCESS_DENIED",
        )
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.get_json()["error_code"], "PROJECT_NOT_FOUND")

    def test_deleting_project_does_not_affect_another_project(self) -> None:
        response = self.owner.delete(
            f"/api/projects/{self.project['id']}"
        )

        self.assertEqual(response.status_code, 200, response.get_json())
        other = self.other.get(
            f"/api/projects/{self.other_project['id']}"
        )
        self.assertEqual(other.status_code, 200, other.get_json())
        self.assertEqual(
            other.get_json()["project"]["name"],
            "Other Project",
        )

    def test_delete_checks_job_count_inside_immediate_transaction(self) -> None:
        uploaded = self._upload(self.owner, self.project["id"])
        self.assertEqual(uploaded.status_code, 201, uploaded.get_json())
        statements: list[str] = []

        with self.app.app_context():
            connection = get_db()
            connection.set_trace_callback(statements.append)
            with self.assertRaises(ProjectNotEmptyError):
                delete_empty_project(self.project["id"], self.owner_id)
            connection.set_trace_callback(None)

        normalized = [statement.upper() for statement in statements]
        begin_index = next(
            index
            for index, statement in enumerate(normalized)
            if "BEGIN IMMEDIATE" in statement
        )
        count_index = next(
            index
            for index, statement in enumerate(normalized)
            if "SELECT COUNT(*) AS COUNT FROM JOBS" in statement
        )
        rollback_index = next(
            index
            for index, statement in enumerate(normalized)
            if "ROLLBACK" in statement
        )
        self.assertLess(begin_index, count_index)
        self.assertLess(count_index, rollback_index)


if __name__ == "__main__":
    unittest.main()
