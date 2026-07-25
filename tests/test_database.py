from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

from app import create_app
from database import close_db, get_db, init_db
from database.db import UnsupportedDatabaseConfigurationError


EXPECTED_TABLES = {
    "schema_version",
    "users",
    "projects",
    "assets",
    "jobs",
    "reviews",
    "agent_calls",
    "knowledge_documents",
}


class FakeAnalysisService:
    def shutdown(self, wait: bool = False) -> None:
        del wait


def fake_analysis_service_factory(*_args) -> FakeAnalysisService:
    return FakeAnalysisService()


class DatabaseTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.database_path = root / "database" / "test.db"
        self.modules_before_create_app = set(sys.modules)
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE": self.database_path,
                "OUTPUTS_DIR": root / "outputs",
                "MODELS_DIR": root / "models",
                "MODEL_PATH": root / "models" / "missing.pt",
                "ANALYSIS_SERVICE_FACTORY": fake_analysis_service_factory,
            }
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_initialization_creates_database_tables_and_version(self) -> None:
        self.assertTrue(self.database_path.is_file())
        with self.app.app_context():
            connection = get_db()
            rows = connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                """
            ).fetchall()
            self.assertEqual({row["name"] for row in rows}, EXPECTED_TABLES)
            version = connection.execute(
                "SELECT version, name FROM schema_version"
            ).fetchall()
            self.assertEqual(
                [(row["version"], row["name"]) for row in version],
                [(1, "initial")],
            )

    def test_repeated_initialization_is_idempotent(self) -> None:
        with self.app.app_context():
            init_db()
            init_db()
            connection = get_db()
            count = connection.execute(
                "SELECT COUNT(*) AS count FROM schema_version WHERE version = 1"
            ).fetchone()
            self.assertEqual(count["count"], 1)
            users_table = connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name = 'users'
                """
            ).fetchone()
            self.assertEqual(users_table["name"], "users")

    def test_connection_enables_foreign_keys_and_enforces_them(self) -> None:
        with self.app.app_context():
            connection = get_db()
            enabled = connection.execute("PRAGMA foreign_keys").fetchone()
            self.assertEqual(enabled[0], 1)
            self.assertEqual(
                connection.execute("PRAGMA busy_timeout").fetchone()[0],
                5000,
            )
            self.assertEqual(
                connection.execute("PRAGMA journal_mode").fetchone()[0],
                "wal",
            )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    INSERT INTO projects (
                        owner_id, name, status, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (999, "orphan", "active", "2026-07-25", "2026-07-25"),
                )

    def test_rows_support_name_based_access(self) -> None:
        with self.app.app_context():
            row = get_db().execute(
                "SELECT 42 AS answer"
            ).fetchone()
            self.assertEqual(row["answer"], 42)

    def test_app_context_teardown_closes_connection(self) -> None:
        with self.app.app_context():
            close_db()
            connection = get_db()
            self.assertIs(connection, get_db())
            connection.execute("SELECT 1").fetchone()
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")

    def test_test_app_does_not_load_torch_or_ultralytics(self) -> None:
        modules_loaded_by_create_app = (
            set(sys.modules) - self.modules_before_create_app
        )
        heavy_modules = {
            name
            for name in modules_loaded_by_create_app
            if name == "torch"
            or name.startswith("torch.")
            or name == "ultralytics"
            or name.startswith("ultralytics.")
        }
        self.assertEqual(heavy_modules, set())
        self.assertIsInstance(
            self.app.extensions["analysis_service"],
            FakeAnalysisService,
        )

    def test_memory_database_configuration_is_rejected(self) -> None:
        root = Path(self.temporary.name)
        with self.assertRaises(
            UnsupportedDatabaseConfigurationError
        ) as raised:
            create_app(
                {
                    "TESTING": True,
                    "DATABASE": ":memory:",
                    "OUTPUTS_DIR": root / "memory-outputs",
                    "MODELS_DIR": root / "memory-models",
                    "MODEL_PATH": root / "memory-models" / "missing.pt",
                    "ANALYSIS_SERVICE_FACTORY": fake_analysis_service_factory,
                }
            )

        message = str(raised.exception)
        self.assertIn(":memory:", message)
        self.assertIn("temporary file", message)


if __name__ == "__main__":
    unittest.main()
