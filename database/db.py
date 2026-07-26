"""Request-scoped SQLite connections and schema initialization."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from flask import Flask, current_app, g


MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
MIGRATIONS = (
    (1, "initial", MIGRATIONS_DIR / "001_initial.sql"),
    (
        2,
        "clarify_job_identifiers",
        MIGRATIONS_DIR / "002_clarify_job_identifiers.sql",
    ),
)
SUPPORTED_SCHEMA_VERSION = MIGRATIONS[-1][0]
APPLICATION_TABLES = frozenset(
    {
        "users",
        "projects",
        "assets",
        "jobs",
        "reviews",
        "agent_calls",
        "knowledge_documents",
    }
)


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


def _schema_versions(
    connection: sqlite3.Connection,
) -> list[sqlite3.Row]:
    table = connection.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = 'schema_version'
        """
    ).fetchone()
    if table is None:
        return []
    return connection.execute(
        """
        SELECT version, name
        FROM schema_version
        ORDER BY version
        """
    ).fetchall()


def _existing_application_tables(
    connection: sqlite3.Connection,
) -> set[str]:
    placeholders = ", ".join("?" for _table in APPLICATION_TABLES)
    return {
        row["name"]
        for row in connection.execute(
            f"""
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name IN ({placeholders})
            """,
            tuple(APPLICATION_TABLES),
        ).fetchall()
    }


def _schema_version_table_exists(
    connection: sqlite3.Connection,
) -> bool:
    return (
        connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = 'schema_version'
            """
        ).fetchone()
        is not None
    )


def _validate_migration_registry() -> None:
    versions = [version for version, _name, _path in MIGRATIONS]
    if versions != list(range(1, SUPPORTED_SCHEMA_VERSION + 1)):
        raise DatabaseMigrationError(
            "Application migration registry contains a version gap"
        )
    for version, name, path in MIGRATIONS:
        if not path.is_file():
            raise DatabaseMigrationError(
                f"Database migration file is missing for {version} ({name})"
            )


def _validate_recorded_migrations(rows: list[sqlite3.Row]) -> None:
    if not rows:
        return
    versions = [row["version"] for row in rows]
    latest_version = versions[-1]
    if not isinstance(latest_version, int):
        raise DatabaseMigrationError(
            "Database schema_version contains a non-integer version"
        )
    if latest_version > SUPPORTED_SCHEMA_VERSION:
        raise DatabaseMigrationError(
            "Database schema version is newer than this application supports"
        )
    expected_versions = list(range(1, latest_version + 1))
    if versions != expected_versions:
        raise DatabaseMigrationError(
            "Database schema_version contains a version gap"
        )

    registered_names = {
        version: name
        for version, name, _path in MIGRATIONS
    }
    for row in rows:
        expected_name = registered_names.get(row["version"])
        if row["name"] != expected_name:
            raise DatabaseMigrationError(
                f"Database migration {row['version']} name does not match "
                "the application migration registry"
            )


def _apply_migration(
    connection: sqlite3.Connection,
    version: int,
    name: str,
    path: Path,
) -> None:
    try:
        migration_sql = path.read_text(encoding="utf-8")
        connection.executescript(migration_sql)
    except (OSError, UnicodeError, sqlite3.Error) as exc:
        if connection.in_transaction:
            connection.rollback()
        raise DatabaseMigrationError(
            f"Failed to apply database migration {version} ({name})"
        ) from exc


def _validate_schema_structure(connection: sqlite3.Connection) -> None:
    expected_columns = {
        "jobs": ("public_job_id", "job_id"),
        "reviews": ("job_row_id", "job_id"),
        "agent_calls": ("job_row_id", "job_id"),
    }
    for table, (required, obsolete) in expected_columns.items():
        columns = {
            row["name"]
            for row in connection.execute(
                f"PRAGMA table_info({table})"
            ).fetchall()
        }
        if required not in columns or obsolete in columns:
            raise DatabaseMigrationError(
                f"Database table {table} does not have the expected "
                "job identifier columns"
            )


def init_db() -> None:
    """Apply all pending migrations and validate the resulting schema."""
    connection = get_db()
    try:
        _validate_migration_registry()
        version_table_exists = _schema_version_table_exists(connection)
        recorded = _schema_versions(connection)
        existing_tables = _existing_application_tables(connection)
        if not recorded and existing_tables:
            history_state = (
                "empty"
                if version_table_exists
                else "missing"
            )
            raise DatabaseMigrationError(
                "Existing application tables have "
                f"{history_state} schema migration history"
            )
        _validate_recorded_migrations(recorded)
        current_version = recorded[-1]["version"] if recorded else 0

        for version, name, path in MIGRATIONS:
            if version > current_version:
                _apply_migration(connection, version, name, path)

        recorded = _schema_versions(connection)
        _validate_recorded_migrations(recorded)
        if len(recorded) != len(MIGRATIONS):
            raise DatabaseMigrationError(
                "Database schema_version does not contain every "
                "application migration"
            )
        _validate_schema_structure(connection)
    except DatabaseMigrationError:
        raise
    except sqlite3.Error as exc:
        raise DatabaseMigrationError(
            "Failed to inspect or validate the database schema"
        ) from exc


def init_app(app: Flask) -> None:
    """Register the database connection lifecycle with a Flask app."""
    app.teardown_appcontext(close_db)
