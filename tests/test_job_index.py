from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app import create_app
from database import get_db
from services.job_index_service import (
    InvalidPublicJobIdError,
    JobIndexNotFoundError,
    get_job_index_by_public_id,
    resolve_job_row_id,
)


class FakeAnalysisService:
    def shutdown(self, wait: bool = False) -> None:
        del wait


def fake_analysis_service_factory(*_args) -> FakeAnalysisService:
    return FakeAnalysisService()


class JobIndexServiceTestCase(unittest.TestCase):
    PUBLIC_JOB_ID = "CaseSensitiveJob-001"

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE": root / "job-index.db",
                "LEGACY_USERS_FILE": root / "legacy-users.db",
                "OUTPUTS_DIR": root / "outputs",
                "MODELS_DIR": root / "models",
                "MODEL_PATH": root / "models" / "missing.pt",
                "ANALYSIS_SERVICE_FACTORY": fake_analysis_service_factory,
            }
        )
        with self.app.app_context():
            connection = get_db()
            timestamp = "2026-07-25T10:00:00+00:00"
            self.user_id = connection.execute(
                """
                INSERT INTO users (
                    username,
                    password_hash,
                    role,
                    is_active,
                    created_at,
                    updated_at
                )
                VALUES ('index-user', 'hash', 'user', 1, ?, ?)
                """,
                (timestamp, timestamp),
            ).lastrowid
            self.project_id = connection.execute(
                """
                INSERT INTO projects (
                    owner_id, name, status, created_at, updated_at
                )
                VALUES (?, 'Index Project', 'active', ?, ?)
                """,
                (self.user_id, timestamp, timestamp),
            ).lastrowid
            self.asset_id = connection.execute(
                """
                INSERT INTO assets (
                    project_id,
                    original_name,
                    stored_path,
                    media_type,
                    size_bytes,
                    created_at,
                    updated_at
                )
                VALUES (
                    ?, 'input.mp4', 'input/input.mp4', 'video', 10, ?, ?
                )
                """,
                (self.project_id, timestamp, timestamp),
            ).lastrowid
            self.job_row_id = connection.execute(
                """
                INSERT INTO jobs (
                    public_job_id,
                    project_id,
                    asset_id,
                    created_by,
                    status,
                    job_json_path,
                    report_json_path,
                    rough_cut_path,
                    created_at,
                    updated_at
                )
                VALUES (
                    ?, ?, ?, ?, 'completed', 'job.json',
                    'analysis_report.json', 'result/rough-cut.mp4', ?, ?
                )
                """,
                (
                    self.PUBLIC_JOB_ID,
                    self.project_id,
                    self.asset_id,
                    self.user_id,
                    timestamp,
                    timestamp,
                ),
            ).lastrowid
            connection.commit()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_resolve_public_job_id_returns_internal_integer_id(self) -> None:
        with self.app.app_context():
            resolved = resolve_job_row_id(self.PUBLIC_JOB_ID)
        self.assertIsInstance(resolved, int)
        self.assertEqual(resolved, self.job_row_id)

    def test_missing_and_case_changed_public_ids_do_not_match(self) -> None:
        with self.app.app_context():
            with self.assertRaises(JobIndexNotFoundError):
                resolve_job_row_id("missing-job")
            with self.assertRaises(JobIndexNotFoundError):
                resolve_job_row_id(self.PUBLIC_JOB_ID.lower())

    def test_invalid_public_job_ids_are_rejected(self) -> None:
        for invalid in (None, True, False, 1, "", "   "):
            with self.subTest(invalid=invalid), self.app.app_context():
                with self.assertRaises(InvalidPublicJobIdError):
                    resolve_job_row_id(invalid)

    def test_get_job_index_returns_plain_dict_with_required_fields(
        self,
    ) -> None:
        with self.app.app_context():
            index = get_job_index_by_public_id(self.PUBLIC_JOB_ID)

        self.assertIs(type(index), dict)
        self.assertEqual(
            index,
            {
                "id": self.job_row_id,
                "public_job_id": self.PUBLIC_JOB_ID,
                "project_id": self.project_id,
                "asset_id": self.asset_id,
                "created_by": self.user_id,
                "status": "completed",
                "job_json_path": "job.json",
                "report_json_path": "analysis_report.json",
                "rough_cut_path": "result/rough-cut.mp4",
            },
        )


if __name__ == "__main__":
    unittest.main()
