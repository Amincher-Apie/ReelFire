"""SQLite-backed authentication and legacy user migration."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import current_app
from werkzeug.security import check_password_hash, generate_password_hash

from database import get_db


LEGACY_HASH_PREFIX = "legacy_sha256$"
LEGACY_SHA256_PATTERN = re.compile(r"[0-9a-fA-F]{64}")


class UsernameExistsError(RuntimeError):
    """Raised when a case-insensitive username conflict occurs."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _public_user(row: sqlite3.Row) -> dict[str, Any]:
    username = str(row["username"])
    display_name = row["display_name"]
    return {
        "id": row["id"],
        "username": username,
        "display_name": display_name,
        "role": row["role"],
        "created_at": row["created_at"],
        "is_guest": username.startswith("guest_") and display_name == "游客",
    }


def _find_user_by_username(username: str) -> sqlite3.Row | None:
    return get_db().execute(
        """
        SELECT
            id,
            username,
            password_hash,
            display_name,
            role,
            is_active,
            created_at
        FROM users
        WHERE username = ? COLLATE NOCASE
        """,
        (username,),
    ).fetchone()


def create_user(username: str, password: str) -> dict[str, Any]:
    """Create and return a normal active user."""
    connection = get_db()
    timestamp = _utc_now()
    try:
        cursor = connection.execute(
            """
            INSERT INTO users (
                username,
                password_hash,
                display_name,
                role,
                is_active,
                created_at,
                updated_at
            )
            VALUES (?, ?, NULL, 'user', 1, ?, ?)
            """,
            (
                username,
                generate_password_hash(password),
                timestamp,
                timestamp,
            ),
        )
        connection.commit()
    except sqlite3.IntegrityError:
        connection.rollback()
        if _find_user_by_username(username) is not None:
            raise UsernameExistsError("Username already exists")
        raise
    except sqlite3.Error:
        connection.rollback()
        raise

    row = connection.execute(
        """
        SELECT id, username, display_name, role, created_at
        FROM users
        WHERE id = ?
        """,
        (cursor.lastrowid,),
    ).fetchone()
    return _public_user(row)


def create_guest_user() -> dict[str, Any]:
    """Create an isolated guest identity that can own projects and jobs."""
    connection = get_db()
    timestamp = _utc_now()
    for _attempt in range(5):
        username = f"guest_{secrets.token_hex(6)}"
        try:
            cursor = connection.execute(
                """
                INSERT INTO users (
                    username,
                    password_hash,
                    display_name,
                    role,
                    is_active,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, '游客', 'user', 1, ?, ?)
                """,
                (
                    username,
                    generate_password_hash(secrets.token_urlsafe(32)),
                    timestamp,
                    timestamp,
                ),
            )
            connection.commit()
        except sqlite3.IntegrityError:
            connection.rollback()
            continue
        except sqlite3.Error:
            connection.rollback()
            raise

        row = connection.execute(
            """
            SELECT id, username, display_name, role, created_at
            FROM users
            WHERE id = ?
            """,
            (cursor.lastrowid,),
        ).fetchone()
        return _public_user(row)
    raise RuntimeError("无法分配唯一的游客身份")


def authenticate_user(username: str, password: str) -> dict[str, Any] | None:
    """Validate credentials and update login metadata on success."""
    connection = get_db()
    row = _find_user_by_username(username)
    if row is None or not row["is_active"]:
        return None

    stored_hash = row["password_hash"]
    upgraded_hash: str | None = None
    if stored_hash.startswith(LEGACY_HASH_PREFIX):
        legacy_hash = stored_hash.removeprefix(LEGACY_HASH_PREFIX)
        candidate = hashlib.sha256(password.encode("utf-8")).hexdigest()
        if not (
            LEGACY_SHA256_PATTERN.fullmatch(legacy_hash)
            and hmac.compare_digest(legacy_hash.lower(), candidate)
        ):
            return None
        upgraded_hash = generate_password_hash(password)
    else:
        try:
            password_matches = check_password_hash(stored_hash, password)
        except (TypeError, ValueError):
            password_matches = False
        if not password_matches:
            return None

    timestamp = _utc_now()
    try:
        if upgraded_hash is None:
            connection.execute(
                """
                UPDATE users
                SET last_login_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (timestamp, timestamp, row["id"]),
            )
        else:
            connection.execute(
                """
                UPDATE users
                SET password_hash = ?, last_login_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (upgraded_hash, timestamp, timestamp, row["id"]),
            )
        connection.commit()
    except sqlite3.Error:
        connection.rollback()
        raise

    return _public_user(row)


def get_user_by_id(user_id: object) -> dict[str, Any] | None:
    """Return the current database state for a session user ID."""
    if isinstance(user_id, bool) or not isinstance(user_id, int):
        return None
    row = get_db().execute(
        """
        SELECT id, username, display_name, role, is_active, created_at
        FROM users
        WHERE id = ?
        """,
        (user_id,),
    ).fetchone()
    if row is None:
        return None
    user = _public_user(row)
    user["is_active"] = bool(row["is_active"])
    return user


def _legacy_created_at(value: object, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return fallback
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def import_legacy_users(legacy_file: str | Path) -> int:
    """Idempotently import valid users from the former JSON store."""
    path = Path(legacy_file)
    try:
        with path.open("r", encoding="utf-8") as handle:
            legacy_users = json.load(handle)
    except FileNotFoundError:
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError):
        current_app.logger.warning(
            "Legacy user data could not be read; leaving the source file unchanged"
        )
        return 0

    if not isinstance(legacy_users, dict):
        current_app.logger.warning(
            "Legacy user data has an invalid structure; "
            "leaving the source file unchanged"
        )
        return 0

    connection = get_db()
    imported = 0
    fallback_timestamp = _utc_now()
    try:
        for raw_username, metadata in legacy_users.items():
            if not isinstance(raw_username, str) or not isinstance(metadata, dict):
                continue
            username = raw_username.strip()
            legacy_hash = metadata.get("password")
            if (
                not 2 <= len(username) <= 32
                or not isinstance(legacy_hash, str)
                or LEGACY_SHA256_PATTERN.fullmatch(legacy_hash) is None
            ):
                continue
            timestamp = _legacy_created_at(
                metadata.get("created_at"),
                fallback_timestamp,
            )
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO users (
                    username,
                    password_hash,
                    display_name,
                    role,
                    is_active,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, NULL, 'user', 1, ?, ?)
                """,
                (
                    username,
                    f"{LEGACY_HASH_PREFIX}{legacy_hash.lower()}",
                    timestamp,
                    timestamp,
                ),
            )
            imported += cursor.rowcount
        connection.commit()
    except sqlite3.Error:
        connection.rollback()
        raise
    return imported
