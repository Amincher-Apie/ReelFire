from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from app import create_app
from database import get_db
from services.job_service import JOB_ID_PATTERN


class FakeAnalysisService:
    def shutdown(self, wait: bool = False) -> None:
        del wait


def fake_analysis_service_factory(*_args) -> FakeAnalysisService:
    return FakeAnalysisService()


class ProjectUploadPersistenceTestCase(unittest.TestCase):
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
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def register(
        self,
        client,
        username: str,
        password: str = "test-passphrase",
    ) -> dict:
        response = client.post(
            "/api/auth/register",
            json={"username": username, "password": password},
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["user"]

    def create_project(self, client, name: str = "CS2 教学素材") -> dict:
        response = client.post(
            "/api/projects",
            json={
                "name": name,
                "description": "课程演示项目",
                "game_type": "cs2",
            },
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["project"]

    def upload(self, client, *, project_id: object | None = None, **extra):
        data = {
            "file": (io.BytesIO(self.MINIMAL_MP4), "demo.mp4"),
            "project_name": "不可信的请求项目名",
            **extra,
        }
        if project_id is not None:
            data["project_id"] = str(project_id)
        return client.post(
            "/api/jobs",
            data=data,
            content_type="multipart/form-data",
        )

    def table_count(self, table: str) -> int:
        self.assertIn(table, {"projects", "assets", "jobs"})
        with self.app.app_context():
            row = get_db().execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
            return int(row["count"])

    def workspace_names(self) -> set[str]:
        if not self.outputs_dir.exists():
            return set()
        return {path.name for path in self.outputs_dir.iterdir() if path.is_dir()}

    def test_project_endpoints_require_authentication(self) -> None:
        create_response = self.client.post("/api/projects", json={"name": "demo"})
        list_response = self.client.get("/api/projects")

        for response in (create_response, list_response):
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.get_json()["error_code"], "AUTH_REQUIRED")

    def test_create_project_uses_session_owner_and_active_status(self) -> None:
        user = self.register(self.client, "project-owner")
        project = self.create_project(self.client)

        self.assertEqual(project["owner_id"], user["id"])
        self.assertEqual(project["status"], "active")
        with self.app.app_context():
            row = get_db().execute(
                "SELECT owner_id, name, status FROM projects WHERE id = ?",
                (project["id"],),
            ).fetchone()
        self.assertEqual(row["owner_id"], user["id"])
        self.assertEqual(row["name"], "CS2 教学素材")
        self.assertEqual(row["status"], "active")

    def test_owned_project_can_be_renamed_and_archived(self) -> None:
        self.register(self.client, "project-lifecycle-owner")
        project = self.create_project(self.client, "Original project")

        renamed = self.client.patch(
            f"/api/projects/{project['id']}",
            json={"name": "Renamed project"},
        )
        self.assertEqual(renamed.status_code, 200, renamed.get_json())
        self.assertEqual(
            renamed.get_json()["project"]["name"],
            "Renamed project",
        )

        archived = self.client.patch(
            f"/api/projects/{project['id']}",
            json={"status": "archived"},
        )
        self.assertEqual(archived.status_code, 200, archived.get_json())
        self.assertEqual(
            archived.get_json()["project"]["status"],
            "archived",
        )
        listed = self.client.get("/api/projects").get_json()["projects"]
        self.assertEqual(listed, [])

    def test_request_cannot_choose_owner_id(self) -> None:
        user = self.register(self.client, "owner-field-user")
        response = self.client.post(
            "/api/projects",
            json={"name": "demo", "owner_id": user["id"] + 100},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.get_json()["error_code"],
            "PROJECT_OWNER_FORBIDDEN",
        )
        self.assertEqual(self.table_count("projects"), 0)

    def test_users_only_list_their_own_projects(self) -> None:
        client_a = self.app.test_client()
        client_b = self.app.test_client()
        self.register(client_a, "project-user-a")
        self.register(client_b, "project-user-b")
        project_a = self.create_project(client_a, "A project")
        project_b = self.create_project(client_b, "B project")

        ids_a = {
            project["id"]
            for project in client_a.get("/api/projects").get_json()["projects"]
        }
        ids_b = {
            project["id"]
            for project in client_b.get("/api/projects").get_json()["projects"]
        }
        self.assertEqual(ids_a, {project_a["id"]})
        self.assertEqual(ids_b, {project_b["id"]})

    def test_unauthenticated_project_upload_creates_nothing(self) -> None:
        owner = self.app.test_client()
        self.register(owner, "upload-owner")
        project = self.create_project(owner)
        before = self.workspace_names()

        response = self.upload(self.client, project_id=project["id"])

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["error_code"], "AUTH_REQUIRED")
        self.assertEqual(self.workspace_names(), before)
        self.assertEqual(self.table_count("assets"), 0)
        self.assertEqual(self.table_count("jobs"), 0)

    def test_owned_project_upload_persists_relationships_and_relative_paths(self) -> None:
        user = self.register(self.client, "sqlite-upload-owner")
        project = self.create_project(self.client, "Trusted project")

        response = self.upload(
            self.client,
            project_id=project["id"],
            game_type="csgo",
        )

        self.assertEqual(response.status_code, 201, response.get_json())
        payload = response.get_json()
        job_id = payload["job_id"]
        self.assertIsInstance(job_id, str)
        self.assertRegex(job_id, JOB_ID_PATTERN)
        self.assertNotIn("job_row_id", payload)
        job_dir = self.outputs_dir / job_id
        self.assertTrue((job_dir / "input" / "demo.mp4").is_file())
        self.assertTrue((job_dir / "job.json").is_file())
        job_json = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(job_json["project_name"], "Trusted project")
        self.assertEqual(job_json["project_id"], project["id"])

        with self.app.app_context():
            asset = get_db().execute("SELECT * FROM assets").fetchone()
            job = get_db().execute("SELECT * FROM jobs").fetchone()
        self.assertEqual(asset["project_id"], project["id"])
        self.assertEqual(job["project_id"], project["id"])
        self.assertEqual(job["asset_id"], asset["id"])
        self.assertEqual(job["created_by"], user["id"])
        self.assertEqual(job["public_job_id"], job_id)
        for value in (asset["stored_path"], job["job_json_path"]):
            self.assertFalse(Path(value).is_absolute())
            self.assertNotIn(str(self.root), value)
            self.assertNotIn("\\", value)
        self.assertEqual(job["report_json_path"], None)
        self.assertEqual(job["rough_cut_path"], None)

    def test_other_users_project_is_denied_before_workspace_creation(self) -> None:
        owner = self.app.test_client()
        attacker = self.app.test_client()
        self.register(owner, "owned-project-user")
        self.register(attacker, "other-project-user")
        project = self.create_project(owner)
        before = self.workspace_names()

        response = self.upload(attacker, project_id=project["id"])

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.get_json()["error_code"],
            "PROJECT_ACCESS_DENIED",
        )
        self.assertEqual(self.workspace_names(), before)
        self.assertEqual(self.table_count("assets"), 0)
        self.assertEqual(self.table_count("jobs"), 0)

    def test_missing_project_is_rejected_before_workspace_creation(self) -> None:
        self.register(self.client, "missing-project-user")
        before = self.workspace_names()

        response = self.upload(self.client, project_id=999999)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["error_code"], "PROJECT_NOT_FOUND")
        self.assertEqual(self.workspace_names(), before)

    def test_invalid_project_ids_do_not_fall_back_to_file_only_upload(self) -> None:
        self.register(self.client, "invalid-project-user")
        for raw_value in ("", "0", "-1", "abc", "1.5"):
            with self.subTest(project_id=raw_value):
                before = self.workspace_names()
                response = self.client.post(
                    "/api/jobs",
                    data={
                        "file": (io.BytesIO(self.MINIMAL_MP4), "demo.mp4"),
                        "project_id": raw_value,
                        "project_name": "legacy",
                    },
                    content_type="multipart/form-data",
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(
                    response.get_json()["error_code"],
                    "PROJECT_INPUT_INVALID",
                )
                self.assertEqual(self.workspace_names(), before)
        self.assertEqual(self.table_count("assets"), 0)
        self.assertEqual(self.table_count("jobs"), 0)

    def test_database_failure_rolls_back_and_discards_workspace(self) -> None:
        self.register(self.client, "rollback-user")
        project = self.create_project(self.client)
        with self.app.app_context():
            get_db().execute(
                """
                CREATE TRIGGER reject_job_index
                BEFORE INSERT ON jobs
                BEGIN
                    SELECT RAISE(ABORT, 'forced test failure');
                END
                """
            )
            get_db().commit()
        before = self.workspace_names()

        response = self.upload(self.client, project_id=project["id"])

        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.workspace_names(), before)
        self.assertEqual(self.table_count("assets"), 0)
        self.assertEqual(self.table_count("jobs"), 0)

    def test_project_name_only_upload_requires_login_and_is_owned(self) -> None:
        anonymous = self.client.post(
            "/api/jobs",
            data={
                "file": (io.BytesIO(self.MINIMAL_MP4), "legacy.mp4"),
                "project_name": "Legacy project",
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(anonymous.status_code, 401, anonymous.get_json())

        self.register(self.client, "legacy-upload-user")
        response = self.client.post(
            "/api/jobs",
            data={
                "file": (io.BytesIO(self.MINIMAL_MP4), "legacy.mp4"),
                "project_name": "Legacy project",
            },
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 201, response.get_json())
        job_id = response.get_json()["job_id"]
        self.assertRegex(job_id, JOB_ID_PATTERN)
        self.assertTrue((self.outputs_dir / job_id / "job.json").is_file())
        self.assertEqual(self.table_count("projects"), 1)
        self.assertEqual(self.table_count("assets"), 1)
        self.assertEqual(self.table_count("jobs"), 1)
        listed_ids = {
            job["job_id"]
            for job in self.client.get("/api/jobs").get_json()["jobs"]
        }
        self.assertEqual(listed_ids, {job_id})


if __name__ == "__main__":
    unittest.main()
