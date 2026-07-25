"""Request-scoped SQLite connections and schema initialization."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from flask import Flask, current_app, g


MIGRATION_VERSION = 1
MIGRATION_NAME = "initial"
MIGRATION_PATH = Path(__file__).resolve().parent / "migrations" / "001_initial.sql"


class DatabaseMigrationError(RuntimeError):
    """Raised when the application database cannot be migrated safely."""


class UnsupportedDatabaseConfigurationError(RuntimeError):
    """Raised when the configured SQLite target is unsupported."""


def _database_target() -> str:
    configured = current_app.config["DATABASE"]
    target = str(configured)
    if target == ":memory:":
        raise UnsupportedDatabaseConfigurationError(
            "SQLite ':memory:' databases are not supported; "
            "use a temporary file database instead"
        )
    return target


def get_db() -> sqlite3.Connection:
    """Return the connection for the current Flask application context."""
    if "db" not in g:
        target = _database_target()
        Path(target).expanduser().parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(target)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        g.db = connection
    return g.db


def close_db(_error: BaseException | None = None) -> None:
    """Close and remove the connection for the current app context."""
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def _schema_version(connection: sqlite3.Connection) -> int | None:
    table = connection.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = 'schema_version'
        """
    ).fetchone()
    if table is None:
        return None
    row = connection.execute(
        "SELECT MAX(version) AS version FROM schema_version"
    ).fetchone()
    return row["version"]


def init_db() -> None:
    """Apply the version 1 migration when the configured database needs it."""
    connection = get_db()
    try:
        version = _schema_version(connection)
        if version is None or version < MIGRATION_VERSION:
            migration_sql = MIGRATION_PATH.read_text(encoding="utf-8")
            connection.executescript(migration_sql)

        version_row = connection.execute(
            """
            SELECT version, name
            FROM schema_version
            WHERE version = ?
            """,
            (MIGRATION_VERSION,),
        ).fetchone()
        if version_row is None or version_row["name"] != MIGRATION_NAME:
            raise DatabaseMigrationError(
                f"Database migration {MIGRATION_VERSION} "
                f"({MIGRATION_NAME}) is not recorded"
            )
    except DatabaseMigrationError:
        raise
    except (OSError, sqlite3.Error) as exc:
        raise DatabaseMigrationError(
            f"Failed to apply database migration {MIGRATION_VERSION} "
            f"({MIGRATION_NAME})"
        ) from exc


def init_app(app: Flask) -> None:
    """Register the database connection lifecycle with a Flask app."""
    app.teardown_appcontext(close_db)
