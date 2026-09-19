"""SQLite lifecycle. Setup is explicit; opening the app never creates a database."""

import os
from pathlib import Path
import sqlite3

from flask import current_app, g


SCHEMA_VERSION = 4
SCHEMA_IDENTITY = "measurement-templates-rates-v4"


def connect_database(path):
    """Open an existing local database, with transactions controlled by callers."""
    database_path = Path(path).resolve()
    if not database_path.is_file():
        raise FileNotFoundError(f"Database does not exist: {database_path}")
    connection = sqlite3.connect(
        database_path.as_uri() + "?mode=rw", uri=True, timeout=10,
        isolation_level=None,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    connection.execute("PRAGMA synchronous = FULL")
    return connection


def get_db():
    if "db" not in g:
        g.db = connect_database(current_app.config["DATABASE"])
        found_version = g.db.execute("PRAGMA user_version").fetchone()[0]
        if found_version != SCHEMA_VERSION:
            g.db.close()
            g.pop("db")
            raise RuntimeError(
                f"This database is schema version {found_version}, not version {SCHEMA_VERSION}. "
                "Preserve it and initialize a new database; this source never upgrades it silently."
            )
        identity = g.db.execute(
            "SELECT value FROM settings WHERE key = 'schema_identity'"
        ).fetchone()
        if identity is None or identity["value"] != SCHEMA_IDENTITY:
            g.db.close()
            g.pop("db")
            raise RuntimeError(
                "This database does not use the Phase 3A.1 measurement-template and rate foundation. Preserve it and initialize a new database."
            )
    return g.db


def close_db(error=None):
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def initialize_database(path, username, password_hash, secret_key):
    """Create a new database only; never seed, clear, or overwrite an existing one."""
    database_path = Path(path).resolve()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation refuses even an existing empty file. This happens before
    # SQLite opens the file, so setup cannot accidentally reseed operational data.
    descriptor = os.open(database_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    connection = None
    try:
        connection = connect_database(database_path)
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        schema = (Path(__file__).parent / "migrations" / "001_initial.sql").read_text(encoding="utf-8")
        # executescript otherwise commits any pending transaction first. Start
        # within the script so schema, seed metadata, and credentials are atomic.
        connection.executescript("BEGIN IMMEDIATE;\n" + schema)
        connection.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, password_hash),
        )
        connection.execute("INSERT INTO settings (key, value) VALUES ('secret_key', ?)", (secret_key,))
        connection.commit()
    except BaseException:
        if connection is not None:
            connection.rollback()
            connection.close()
            connection = None
        # This file belongs to this failed setup attempt: exclusive creation above
        # proved there was no earlier shop database at this path.
        database_path.unlink(missing_ok=True)
        Path(str(database_path) + "-wal").unlink(missing_ok=True)
        Path(str(database_path) + "-shm").unlink(missing_ok=True)
        raise
    finally:
        if connection is not None:
            connection.close()
