from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from werkzeug.security import check_password_hash

from app import create_app
from database import get_db
from services.auth_service import (
    LEGACY_HASH_PREFIX,
    create_user,
    import_legacy_users,
)


class FakeAnalysisService:
    def shutdown(self, wait: bool = False) -> None:
        del wait


def fake_analysis_service_factory(*_args) -> FakeAnalysisService:
    return FakeAnalysisService()


class AuthenticationTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database_path = self.root / "auth.db"
        self.legacy_users_file = self.root / "users.db"
        self.app = self.create_test_app()
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def create_test_app(
        self,
        *,
        database_path: Path | None = None,
        legacy_users_file: Path | None = None,
        suffix: str = "default",
    ):
        return create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-secret-key",
                "DATABASE": database_path or self.database_path,
                "LEGACY_USERS_FILE": (
                    legacy_users_file or self.legacy_users_file
                ),
                "OUTPUTS_DIR": self.root / f"outputs-{suffix}",
                "MODELS_DIR": self.root / f"models-{suffix}",
                "MODEL_PATH": self.root / f"models-{suffix}" / "missing.pt",
                "BACKGROUND_WORKERS": 1,
                "ANALYSIS_SERVICE_FACTORY": fake_analysis_service_factory,
            }
        )

    def register(
        self,
        username: str = "frontend-reviewer",
        password: str = "test-passphrase",
    ):
        return self.client.post(
            "/api/auth/register",
            json={"username": username, "password": password},
        )

    def database_user(self, username: str):
        with self.app.app_context():
            return get_db().execute(
                """
                SELECT *
                FROM users
                WHERE username = ? COLLATE NOCASE
                """,
                (username,),
            ).fetchone()

    def test_register_writes_secure_sqlite_user_and_session(self) -> None:
        response = self.register()

        self.assertEqual(response.status_code, 201, response.get_json())
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["user"]["username"], "frontend-reviewer")
        created_at = payload["user"]["created_at"]
        self.assertIsInstance(created_at, str)
        parsed_created_at = datetime.fromisoformat(created_at)
        self.assertIsNotNone(parsed_created_at.tzinfo)
        self.assertEqual(
            parsed_created_at.utcoffset(),
            timezone.utc.utcoffset(parsed_created_at),
        )
        row = self.database_user("frontend-reviewer")
        self.assertIsNotNone(row)
        self.assertNotEqual(row["password_hash"], "test-passphrase")
        self.assertIsNone(re.fullmatch(r"[0-9a-f]{64}", row["password_hash"]))
        self.assertTrue(
            check_password_hash(row["password_hash"], "test-passphrase")
        )
        with self.client.session_transaction() as flask_session:
            self.assertEqual(flask_session["user_id"], row["id"])
            self.assertNotIn("user", flask_session)
        self.assertFalse(self.legacy_users_file.exists())

    def test_guest_login_creates_isolated_database_identity_and_session(self) -> None:
        first = self.client.post("/api/auth/guest", json={})
        first_payload = first.get_json()

        self.assertEqual(first.status_code, 201, first_payload)
        self.assertTrue(first_payload["ok"])
        self.assertTrue(first_payload["user"]["is_guest"])
        self.assertEqual(first_payload["user"]["display_name"], "游客")
        self.assertRegex(first_payload["user"]["username"], r"^guest_[0-9a-f]{12}$")

        first_id = first_payload["user"]["id"]
        with self.client.session_transaction() as flask_session:
            self.assertEqual(flask_session["user_id"], first_id)

        second_client = self.app.test_client()
        second = second_client.post("/api/auth/guest", json={})
        second_payload = second.get_json()
        self.assertEqual(second.status_code, 201, second_payload)
        self.assertNotEqual(second_payload["user"]["id"], first_id)
        self.assertNotEqual(
            second_payload["user"]["username"],
            first_payload["user"]["username"],
        )

    def test_register_rejects_case_insensitive_duplicate(self) -> None:
        self.assertEqual(self.register("Reviewer").status_code, 201)
        duplicate = self.register("reviewer")
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(
            duplicate.get_json()["error_code"],
            "AUTH_USERNAME_EXISTS",
        )

    def test_non_username_integrity_error_is_not_misclassified(self) -> None:
        with self.app.app_context():
            with (
                patch(
                    "services.auth_service.generate_password_hash",
                    return_value=None,
                ),
                self.assertRaises(sqlite3.IntegrityError),
            ):
                create_user("constraint-user", "valid-password")

    def test_register_validates_required_username_and_password(self) -> None:
        cases = [
            ({}, "AUTH_INPUT_REQUIRED"),
            ({"username": "valid"}, "AUTH_INPUT_REQUIRED"),
            (
                {"username": "x", "password": "long-enough"},
                "AUTH_USERNAME_INVALID",
            ),
            (
                {"username": "valid", "password": "short"},
                "AUTH_PASSWORD_WEAK",
            ),
        ]
        for body, error_code in cases:
            with self.subTest(body=body):
                response = self.client.post("/api/auth/register", json=body)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.get_json()["error_code"], error_code)

    def test_login_accepts_password_updates_metadata_and_session(self) -> None:
        self.register("LoginUser", "correct-password")
        self.client.post("/api/auth/logout")

        response = self.client.post(
            "/api/auth/login",
            json={"username": "loginuser", "password": "correct-password"},
        )

        self.assertEqual(response.status_code, 200, response.get_json())
        row = self.database_user("LoginUser")
        self.assertIsNotNone(row["last_login_at"])
        self.assertEqual(row["last_login_at"], row["updated_at"])
        with self.client.session_transaction() as flask_session:
            self.assertEqual(flask_session["user_id"], row["id"])
            self.assertNotIn("user", flask_session)

    def test_invalid_and_missing_credentials_share_one_response(self) -> None:
        self.register("known-user", "correct-password")
        self.client.post("/api/auth/logout")
        wrong_password = self.client.post(
            "/api/auth/login",
            json={"username": "known-user", "password": "wrong-password"},
        )
        missing_user = self.client.post(
            "/api/auth/login",
            json={"username": "missing-user", "password": "wrong-password"},
        )

        self.assertEqual(wrong_password.status_code, 401)
        self.assertEqual(missing_user.status_code, 401)
        self.assertEqual(wrong_password.get_json(), missing_user.get_json())
        self.assertEqual(
            wrong_password.get_json()["error_code"],
            "AUTH_INVALID_CREDENTIALS",
        )

    def test_disabled_user_cannot_login(self) -> None:
        self.register("disabled-user", "correct-password")
        self.client.post("/api/auth/logout")
        with self.app.app_context():
            connection = get_db()
            connection.execute(
                "UPDATE users SET is_active = 0 WHERE username = ?",
                ("disabled-user",),
            )
            connection.commit()

        response = self.client.post(
            "/api/auth/login",
            json={
                "username": "disabled-user",
                "password": "correct-password",
            },
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.get_json()["error_code"],
            "AUTH_INVALID_CREDENTIALS",
        )

    def test_me_reads_current_user_from_sqlite(self) -> None:
        registered = self.register("current-user")
        user_id = registered.get_json()["user"]["id"]
        with self.app.app_context():
            connection = get_db()
            connection.execute(
                "UPDATE users SET display_name = ? WHERE id = ?",
                ("Current Reviewer", user_id),
            )
            connection.commit()

        response = self.client.get("/api/auth/me")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json()["user"]["display_name"],
            "Current Reviewer",
        )

    def test_me_rejects_anonymous_deleted_and_disabled_users(self) -> None:
        anonymous = self.client.get("/api/auth/me")
        self.assertEqual(anonymous.status_code, 401)
        self.assertEqual(anonymous.get_json()["error_code"], "AUTH_REQUIRED")

        registered = self.register("temporary-user")
        user_id = registered.get_json()["user"]["id"]
        with self.app.app_context():
            connection = get_db()
            connection.execute(
                "UPDATE users SET is_active = 0 WHERE id = ?",
                (user_id,),
            )
            connection.commit()
        disabled = self.client.get("/api/auth/me")
        self.assertEqual(disabled.status_code, 401)
        with self.client.session_transaction() as flask_session:
            self.assertNotIn("user_id", flask_session)

        with self.app.app_context():
            connection = get_db()
            connection.execute("DELETE FROM users WHERE id = ?", (user_id,))
            connection.commit()
        with self.client.session_transaction() as flask_session:
            flask_session["user_id"] = user_id
        deleted = self.client.get("/api/auth/me")
        self.assertEqual(deleted.status_code, 401)

    def test_logout_clears_current_and_legacy_session_fields(self) -> None:
        self.register()
        with self.client.session_transaction() as flask_session:
            flask_session["user"] = "legacy-session-user"

        logout = self.client.post("/api/auth/logout")
        current = self.client.get("/api/auth/me")

        self.assertEqual(logout.status_code, 200)
        self.assertEqual(current.status_code, 401)
        with self.client.session_transaction() as flask_session:
            self.assertNotIn("user_id", flask_session)
            self.assertNotIn("user", flask_session)

    def test_legacy_import_is_idempotent_and_does_not_overwrite(self) -> None:
        self.register("Alice", "new-password")
        original_hash = self.database_user("Alice")["password_hash"]
        self.legacy_users_file.write_text(
            json.dumps(
                {
                    "alice": {
                        "password": hashlib.sha256(
                            b"legacy-alice-password"
                        ).hexdigest(),
                        "created_at": "2026-07-25T10:00:00",
                    },
                    "bob": {
                        "password": hashlib.sha256(
                            b"legacy-bob-password"
                        ).hexdigest(),
                        "created_at": "2026-07-25T10:00:00",
                    },
                    "invalid": {"password": "not-a-sha256"},
                }
            ),
            encoding="utf-8",
        )

        with self.app.app_context():
            self.assertEqual(import_legacy_users(self.legacy_users_file), 1)
            self.assertEqual(import_legacy_users(self.legacy_users_file), 0)
            connection = get_db()
            count = connection.execute(
                "SELECT COUNT(*) AS count FROM users"
            ).fetchone()["count"]
        self.assertEqual(count, 2)
        self.assertEqual(self.database_user("Alice")["password_hash"], original_hash)
        self.assertTrue(
            self.database_user("bob")["password_hash"].startswith(
                LEGACY_HASH_PREFIX
            )
        )

        restarted = self.create_test_app(suffix="restart")
        with restarted.app_context():
            count_after_restart = get_db().execute(
                "SELECT COUNT(*) AS count FROM users"
            ).fetchone()["count"]
        self.assertEqual(count_after_restart, 2)

    def test_legacy_login_upgrades_sha256_password(self) -> None:
        password = "legacy-password"
        self.legacy_users_file.write_text(
            json.dumps(
                {
                    "legacy-user": {
                        "password": hashlib.sha256(
                            password.encode("utf-8")
                        ).hexdigest(),
                        "created_at": "2026-07-25T10:00:00",
                    }
                }
            ),
            encoding="utf-8",
        )
        with self.app.app_context():
            import_legacy_users(self.legacy_users_file)
        before = self.database_user("legacy-user")["password_hash"]
        self.assertTrue(before.startswith(LEGACY_HASH_PREFIX))

        response = self.client.post(
            "/api/auth/login",
            json={"username": "LEGACY-USER", "password": password},
        )

        self.assertEqual(response.status_code, 200, response.get_json())
        after = self.database_user("legacy-user")["password_hash"]
        self.assertFalse(after.startswith(LEGACY_HASH_PREFIX))
        self.assertTrue(check_password_hash(after, password))

    def test_valid_legacy_user_is_imported_during_app_startup(self) -> None:
        password = "startup-legacy-password"
        legacy_file = self.root / "startup-users.db"
        legacy_file.write_text(
            json.dumps(
                {
                    "startup-user": {
                        "password": hashlib.sha256(
                            password.encode("utf-8")
                        ).hexdigest(),
                        "created_at": "2026-07-25T10:00:00",
                    }
                }
            ),
            encoding="utf-8",
        )
        database_path = self.root / "startup-import.db"

        app = self.create_test_app(
            database_path=database_path,
            legacy_users_file=legacy_file,
            suffix="startup-import",
        )
        client = app.test_client()
        with app.app_context():
            imported = get_db().execute(
                """
                SELECT password_hash
                FROM users
                WHERE username = ?
                """,
                ("startup-user",),
            ).fetchone()
        self.assertIsNotNone(imported)
        self.assertTrue(imported["password_hash"].startswith(LEGACY_HASH_PREFIX))

        response = client.post(
            "/api/auth/login",
            json={"username": "startup-user", "password": password},
        )

        self.assertEqual(response.status_code, 200, response.get_json())
        with app.app_context():
            upgraded = get_db().execute(
                """
                SELECT password_hash
                FROM users
                WHERE username = ?
                """,
                ("startup-user",),
            ).fetchone()["password_hash"]
        self.assertFalse(upgraded.startswith(LEGACY_HASH_PREFIX))
        self.assertTrue(check_password_hash(upgraded, password))

    def test_registration_does_not_modify_existing_legacy_file(self) -> None:
        legacy_payload = b"legacy-source-must-remain-unchanged"
        self.legacy_users_file.write_bytes(legacy_payload)
        before_registration = self.legacy_users_file.read_bytes()

        response = self.register("sqlite-only-user", "sqlite-password")

        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(
            self.legacy_users_file.read_bytes(),
            before_registration,
        )
        self.assertIsNotNone(self.database_user("sqlite-only-user"))

    def test_corrupt_legacy_json_is_preserved_and_does_not_block_startup(
        self,
    ) -> None:
        corrupt_file = self.root / "corrupt-users.db"
        corrupt_payload = b"{broken-json"
        corrupt_file.write_bytes(corrupt_payload)
        database_path = self.root / "corrupt-startup.db"

        app = self.create_test_app(
            database_path=database_path,
            legacy_users_file=corrupt_file,
            suffix="corrupt",
        )

        self.assertTrue(app.testing)
        self.assertTrue(database_path.is_file())
        self.assertEqual(corrupt_file.read_bytes(), corrupt_payload)


if __name__ == "__main__":
    unittest.main()
