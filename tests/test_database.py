from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from app import create_app
from database import close_db, get_db, init_app as init_database_app, init_db
from database.db import (
    DatabaseMigrationError,
    UnsupportedDatabaseConfigurationError,
)


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
INITIAL_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "database"
    / "migrations"
    / "001_initial.sql"
)


class FakeAnalysisService:
    def shutdown(self, wait: bool = False) -> None:
        del wait


def fake_analysis_service_factory(*_args) -> FakeAnalysisService:
    return FakeAnalysisService()


def create_database_only_app(database_path: Path) -> Flask:
    app = Flask(__name__)
    app.config["DATABASE"] = database_path
    init_database_app(app)
    return app


def create_version_one_database(database_path: Path) -> None:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(INITIAL_MIGRATION.read_text(encoding="utf-8"))
    connection.close()


def insert_complete_job_relationship(
    connection: sqlite3.Connection,
    public_job_id: str,
    *,
    job_column: str,
    related_job_column: str,
) -> dict[str, int]:
    timestamp = "2026-07-25T10:00:00+00:00"
    user_id = connection.execute(
        """
        INSERT INTO users (
            username, password_hash, role, is_active, created_at, updated_at
        )
        VALUES (?, ?, 'user', 1, ?, ?)
        """,
        (f"user-{public_job_id}", "hash", timestamp, timestamp),
    ).lastrowid
    project_id = connection.execute(
        """
        INSERT INTO projects (
            owner_id, name, status, created_at, updated_at
        )
        VALUES (?, ?, 'active', ?, ?)
        """,
        (user_id, f"project-{public_job_id}", timestamp, timestamp),
    ).lastrowid
    asset_id = connection.execute(
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
        VALUES (?, 'input.mp4', 'input/input.mp4', 'video', 10, ?, ?)
        """,
        (project_id, timestamp, timestamp),
    ).lastrowid
    job_id = connection.execute(
        f"""
        INSERT INTO jobs (
            {job_column},
            project_id,
            asset_id,
            created_by,
            status,
            job_json_path,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, 'created', 'job.json', ?, ?)
        """,
        (
            public_job_id,
            project_id,
            asset_id,
            user_id,
            timestamp,
            timestamp,
        ),
    ).lastrowid
    review_id = connection.execute(
        f"""
        INSERT INTO reviews (
            {related_job_column},
            reviewer_id,
            status,
            created_at,
            updated_at
        )
        VALUES (?, ?, 'pending', ?, ?)
        """,
        (job_id, user_id, timestamp, timestamp),
    ).lastrowid
    agent_call_id = connection.execute(
        f"""
        INSERT INTO agent_calls (
            {related_job_column},
            requested_by,
            status,
            created_at
        )
        VALUES (?, ?, 'queued', ?)
        """,
        (job_id, user_id, timestamp),
    ).lastrowid
    connection.commit()
    return {
        "user_id": user_id,
        "project_id": project_id,
        "asset_id": asset_id,
        "job_id": job_id,
        "review_id": review_id,
        "agent_call_id": agent_call_id,
    }


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
                "LEGACY_USERS_FILE": root / "legacy-users.db",
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
                [
                    (1, "initial"),
                    (2, "clarify_job_identifiers"),
                ],
            )

    def test_repeated_initialization_is_idempotent(self) -> None:
        with self.app.app_context():
            init_db()
            init_db()
            connection = get_db()
            count = connection.execute(
                "SELECT COUNT(*) AS count FROM schema_version"
            ).fetchone()
            self.assertEqual(count["count"], 2)
            users_table = connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name = 'users'
                """
            ).fetchone()
            self.assertEqual(users_table["name"], "users")

    def test_version_two_columns_types_and_unique_constraint(self) -> None:
        with self.app.app_context():
            connection = get_db()
            jobs = {
                row["name"]: row["type"]
                for row in connection.execute(
                    "PRAGMA table_info(jobs)"
                ).fetchall()
            }
            reviews = {
                row["name"]: row["type"]
                for row in connection.execute(
                    "PRAGMA table_info(reviews)"
                ).fetchall()
            }
            agent_calls = {
                row["name"]: row["type"]
                for row in connection.execute(
                    "PRAGMA table_info(agent_calls)"
                ).fetchall()
            }
            self.assertEqual(jobs["public_job_id"], "TEXT")
            self.assertNotIn("job_id", jobs)
            self.assertEqual(reviews["job_row_id"], "INTEGER")
            self.assertNotIn("job_id", reviews)
            self.assertEqual(agent_calls["job_row_id"], "INTEGER")
            self.assertNotIn("job_id", agent_calls)

            ids = insert_complete_job_relationship(
                connection,
                "public-job-001",
                job_column="public_job_id",
                related_job_column="job_row_id",
            )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    INSERT INTO jobs (
                        public_job_id,
                        project_id,
                        asset_id,
                        created_by,
                        status,
                        job_json_path,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, 'created', 'duplicate.json', ?, ?)
                    """,
                    (
                        "public-job-001",
                        ids["project_id"],
                        ids["asset_id"],
                        ids["user_id"],
                        "2026-07-25T10:00:00+00:00",
                        "2026-07-25T10:00:00+00:00",
                    ),
                )

    def test_version_one_database_upgrades_without_data_loss(self) -> None:
        root = Path(self.temporary.name)
        upgrade_path = root / "upgrade" / "version-one.db"
        upgrade_path.parent.mkdir(parents=True)
        connection = sqlite3.connect(upgrade_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(INITIAL_MIGRATION.read_text(encoding="utf-8"))
        ids = insert_complete_job_relationship(
            connection,
            "existing-public-job",
            job_column="job_id",
            related_job_column="job_id",
        )
        connection.close()

        upgraded_app = create_app(
            {
                "TESTING": True,
                "DATABASE": upgrade_path,
                "LEGACY_USERS_FILE": root / "upgrade-legacy-users.db",
                "OUTPUTS_DIR": root / "upgrade-outputs",
                "MODELS_DIR": root / "upgrade-models",
                "MODEL_PATH": root / "upgrade-models" / "missing.pt",
                "ANALYSIS_SERVICE_FACTORY": fake_analysis_service_factory,
            }
        )
        with upgraded_app.app_context():
            upgraded = get_db()
            job = upgraded.execute(
                """
                SELECT id, public_job_id
                FROM jobs
                WHERE id = ?
                """,
                (ids["job_id"],),
            ).fetchone()
            review = upgraded.execute(
                "SELECT job_row_id FROM reviews WHERE id = ?",
                (ids["review_id"],),
            ).fetchone()
            agent_call = upgraded.execute(
                "SELECT job_row_id FROM agent_calls WHERE id = ?",
                (ids["agent_call_id"],),
            ).fetchone()
            versions = upgraded.execute(
                "SELECT version, name FROM schema_version ORDER BY version"
            ).fetchall()
            self.assertEqual(job["public_job_id"], "existing-public-job")
            self.assertEqual(review["job_row_id"], ids["job_id"])
            self.assertEqual(agent_call["job_row_id"], ids["job_id"])
            self.assertEqual(
                [(row["version"], row["name"]) for row in versions],
                [
                    (1, "initial"),
                    (2, "clarify_job_identifiers"),
                ],
            )
            for table, row_id in (
                ("users", ids["user_id"]),
                ("projects", ids["project_id"]),
                ("assets", ids["asset_id"]),
                ("jobs", ids["job_id"]),
                ("reviews", ids["review_id"]),
                ("agent_calls", ids["agent_call_id"]),
            ):
                count = upgraded.execute(
                    f"SELECT COUNT(*) AS count FROM {table} WHERE id = ?",
                    (row_id,),
                ).fetchone()["count"]
                self.assertEqual(count, 1, table)

    def test_renamed_foreign_keys_keep_cascade_and_restrict_actions(
        self,
    ) -> None:
        with self.app.app_context():
            connection = get_db()
            ids = insert_complete_job_relationship(
                connection,
                "foreign-key-job",
                job_column="public_job_id",
                related_job_column="job_row_id",
            )
            for table in ("reviews", "agent_calls"):
                foreign_key = next(
                    row
                    for row in connection.execute(
                        f"PRAGMA foreign_key_list({table})"
                    ).fetchall()
                    if row["from"] == "job_row_id"
                )
                self.assertEqual(foreign_key["table"], "jobs")
                self.assertEqual(foreign_key["to"], "id")
                self.assertEqual(foreign_key["on_update"], "CASCADE")
                self.assertEqual(foreign_key["on_delete"], "CASCADE")

            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "DELETE FROM assets WHERE id = ?",
                    (ids["asset_id"],),
                )
            connection.rollback()
            connection.execute(
                "DELETE FROM jobs WHERE id = ?",
                (ids["job_id"],),
            )
            connection.commit()
            for table in ("reviews", "agent_calls"):
                count = connection.execute(
                    f"SELECT COUNT(*) AS count FROM {table}"
                ).fetchone()["count"]
                self.assertEqual(count, 0)

    def test_wrong_migration_name_is_rejected(self) -> None:
        with self.app.app_context():
            connection = get_db()
            connection.execute(
                "UPDATE schema_version SET name = 'wrong' WHERE version = 2"
            )
            connection.commit()
            with self.assertRaises(DatabaseMigrationError):
                init_db()

    def test_schema_version_gap_is_rejected(self) -> None:
        with self.app.app_context():
            connection = get_db()
            connection.execute(
                "DELETE FROM schema_version WHERE version = 1"
            )
            connection.commit()
            with self.assertRaises(DatabaseMigrationError):
                init_db()

    def test_newer_schema_version_is_rejected(self) -> None:
        with self.app.app_context():
            connection = get_db()
            connection.execute(
                """
                INSERT INTO schema_version (version, name, applied_at)
                VALUES (3, 'future', '2026-07-25T10:00:00Z')
                """
            )
            connection.commit()
            with self.assertRaises(DatabaseMigrationError):
                init_db()

    def test_missing_migration_file_is_rejected(self) -> None:
        missing_path = Path(self.temporary.name) / "missing-migration.sql"
        migrations = (
            (1, "initial", INITIAL_MIGRATION),
            (2, "clarify_job_identifiers", missing_path),
        )
        with self.app.app_context(), patch(
            "database.db.MIGRATIONS",
            migrations,
        ):
            with self.assertRaises(DatabaseMigrationError):
                init_db()

    def test_schema_structure_mismatch_is_rejected(self) -> None:
        with self.app.app_context():
            connection = get_db()
            connection.execute(
                """
                ALTER TABLE jobs
                RENAME COLUMN public_job_id TO unexpected_job_id
                """
            )
            connection.commit()
            with self.assertRaises(DatabaseMigrationError):
                init_db()

    def test_existing_schema_without_version_table_is_rejected(self) -> None:
        database_path = (
            Path(self.temporary.name)
            / "missing-history"
            / "existing-schema.db"
        )
        database_path.parent.mkdir(parents=True)
        connection = sqlite3.connect(database_path)
        connection.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")
        connection.commit()
        connection.close()

        app = create_database_only_app(database_path)
        with app.app_context():
            with self.assertRaises(DatabaseMigrationError):
                init_db()
            tables = {
                row["name"]
                for row in get_db().execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
        self.assertIn("users", tables)
        self.assertNotIn("schema_version", tables)
        self.assertNotIn("projects", tables)

    def test_existing_schema_with_empty_version_history_is_rejected(
        self,
    ) -> None:
        database_path = (
            Path(self.temporary.name)
            / "empty-history"
            / "existing-schema.db"
        )
        create_version_one_database(database_path)
        connection = sqlite3.connect(database_path)
        connection.execute("DELETE FROM schema_version")
        connection.commit()
        connection.close()

        app = create_database_only_app(database_path)
        with app.app_context():
            with self.assertRaises(DatabaseMigrationError):
                init_db()
            version_count = get_db().execute(
                "SELECT COUNT(*) AS count FROM schema_version"
            ).fetchone()["count"]
            jobs_columns = {
                row["name"]
                for row in get_db().execute(
                    "PRAGMA table_info(jobs)"
                ).fetchall()
            }
        self.assertEqual(version_count, 0)
        self.assertIn("job_id", jobs_columns)
        self.assertNotIn("public_job_id", jobs_columns)

    def test_invalid_utf8_migration_file_is_rejected(self) -> None:
        root = Path(self.temporary.name) / "invalid-encoding"
        database_path = root / "version-one.db"
        create_version_one_database(database_path)
        invalid_migration = root / "002_invalid_utf8.sql"
        invalid_migration.write_bytes(b"\xff\xfe\xfa")
        migrations = (
            (1, "initial", INITIAL_MIGRATION),
            (2, "clarify_job_identifiers", invalid_migration),
        )

        app = create_database_only_app(database_path)
        with app.app_context(), patch(
            "database.db.MIGRATIONS",
            migrations,
        ):
            with self.assertRaises(DatabaseMigrationError) as raised:
                init_db()
        self.assertIsInstance(raised.exception.__cause__, UnicodeError)

    def test_failed_version_two_migration_rolls_back_completely(
        self,
    ) -> None:
        root = Path(self.temporary.name) / "failed-version-two"
        database_path = root / "version-one.db"
        create_version_one_database(database_path)
        raw_connection = sqlite3.connect(database_path)
        raw_connection.row_factory = sqlite3.Row
        raw_connection.execute("PRAGMA foreign_keys = ON")
        ids = insert_complete_job_relationship(
            raw_connection,
            "rollback-public-job",
            job_column="job_id",
            related_job_column="job_id",
        )
        raw_connection.close()
        failing_migration = root / "002_failing.sql"
        failing_migration.write_text(
            """
            BEGIN IMMEDIATE;
            ALTER TABLE jobs
            RENAME COLUMN job_id TO public_job_id;
            ALTER TABLE reviews
            RENAME COLUMN job_id TO job_row_id;
            THIS IS NOT VALID SQL;
            ALTER TABLE agent_calls
            RENAME COLUMN job_id TO job_row_id;
            INSERT INTO schema_version (version, name, applied_at)
            VALUES (2, 'clarify_job_identifiers', '2026-07-25T10:00:00Z');
            COMMIT;
            """,
            encoding="utf-8",
        )
        migrations = (
            (1, "initial", INITIAL_MIGRATION),
            (2, "clarify_job_identifiers", failing_migration),
        )

        app = create_database_only_app(database_path)
        with app.app_context(), patch(
            "database.db.MIGRATIONS",
            migrations,
        ):
            with self.assertRaises(DatabaseMigrationError):
                init_db()
            connection = get_db()
            for table in ("jobs", "reviews", "agent_calls"):
                columns = {
                    row["name"]
                    for row in connection.execute(
                        f"PRAGMA table_info({table})"
                    ).fetchall()
                }
                self.assertIn("job_id", columns)
                self.assertNotIn("public_job_id", columns)
                self.assertNotIn("job_row_id", columns)
            versions = connection.execute(
                "SELECT version FROM schema_version ORDER BY version"
            ).fetchall()
            self.assertEqual([row["version"] for row in versions], [1])
            preserved = {
                table: connection.execute(
                    f"SELECT COUNT(*) AS count FROM {table} WHERE id = ?",
                    (row_id,),
                ).fetchone()["count"]
                for table, row_id in (
                    ("users", ids["user_id"]),
                    ("projects", ids["project_id"]),
                    ("assets", ids["asset_id"]),
                    ("jobs", ids["job_id"]),
                    ("reviews", ids["review_id"]),
                    ("agent_calls", ids["agent_call_id"]),
                )
            }
        self.assertEqual(set(preserved.values()), {1})

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
