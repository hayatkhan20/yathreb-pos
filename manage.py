"""User-run setup, service and recovery commands. No automatic setup at import."""

import argparse
from contextlib import closing
from getpass import getpass
import ipaddress
from pathlib import Path
import secrets
import sqlite3
import sys

from werkzeug.security import generate_password_hash

from shop import PROJECT_ROOT, create_app
from shop.db import SCHEMA_IDENTITY, SCHEMA_VERSION, connect_database, initialize_database


def local_path(value):
    path = Path(value).expanduser().resolve()
    if str(path).startswith("\\\\"):
        raise ValueError("Use a local disk, not a network share, for the working database.")
    return path


def new_password():
    password = getpass("Owner password (12-128 characters): ")
    if not 12 <= len(password) <= 128:
        raise ValueError("Choose a password between 12 and 128 characters.")
    if password != getpass("Repeat owner password: "):
        raise ValueError("Passwords did not match. Nothing changed.")
    return generate_password_hash(password, method="scrypt")


LEGACY_SCHEMA_VERSION = 4
LEGACY_SCHEMA_IDENTITY = "measurement-templates-rates-v4"
BASE_REQUIRED_TABLES = {
    "products", "brands", "articles", "colours", "sizes", "variants",
    "stock_movements", "sales", "sale_items", "bill_sequence",
    "users", "settings", "login_guard", "customers", "customer_sequence",
    "measurement_profiles", "measurement_revisions", "tailoring_orders",
    "tailoring_items", "tailoring_sequence", "stitching_rate_revisions",
    "payments", "payment_sequence",
}
TAILOR_REQUIRED_TABLES = {"tailors", "tailoring_item_assignments"}


def _inspect_foundation(conn, expected_version, expected_identity, required_tables):
    found_version = conn.execute("PRAGMA user_version").fetchone()[0]
    if found_version != expected_version:
        raise ValueError(
            f"Database schema version {found_version} does not match required version "
            f"{expected_version}."
        )
    checks = conn.execute("PRAGMA integrity_check").fetchall()
    if len(checks) != 1 or checks[0][0] != "ok":
        raise ValueError("SQLite integrity check failed. Preserve the file and seek recovery help.")
    if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise ValueError("Database contains a broken relationship.")
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    )}
    if not required_tables.issubset(tables):
        raise ValueError("This is not a complete inventory backup.")
    identity = conn.execute(
        "SELECT value FROM settings WHERE key = 'schema_identity'"
    ).fetchone()
    if identity is None or identity[0] != expected_identity:
        raise ValueError("Database schema identity does not match its recorded version.")
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] != 1:
        raise ValueError("Expected exactly one owner account in this foundation database.")
    secret = conn.execute(
        "SELECT value FROM settings WHERE key = 'secret_key'"
    ).fetchone()
    if secret is None or len(secret[0]) < 32:
        raise ValueError("The database session secret is missing.")
    if conn.execute("SELECT id FROM login_guard WHERE id = 1").fetchone() is None:
        raise ValueError("The database login guard is missing.")


def inspect_database(conn):
    _inspect_foundation(
        conn,
        SCHEMA_VERSION,
        SCHEMA_IDENTITY,
        BASE_REQUIRED_TABLES | TAILOR_REQUIRED_TABLES,
    )


def inspect_tailor_upgrade_source(conn):
    _inspect_foundation(
        conn,
        LEGACY_SCHEMA_VERSION,
        LEGACY_SCHEMA_IDENTITY,
        BASE_REQUIRED_TABLES,
    )
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    )}
    if tables.intersection(TAILOR_REQUIRED_TABLES):
        raise ValueError("The version-4 database already contains unexpected Tailor tables.")


def upgrade_tailor_schema(database, backup_destination):
    """Explicitly back up and upgrade one verified schema-v4 database to schema v5."""
    database = Path(database).expanduser().resolve(strict=True)
    backup = Path(backup_destination).expanduser().resolve()
    if backup == database:
        raise ValueError("The upgrade backup must differ from the working database.")

    with closing(connect_database(database)) as source:
        inspect_tailor_upgrade_source(source)
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.touch(exist_ok=False)
        try:
            with closing(sqlite3.connect(str(backup), isolation_level=None)) as output:
                source.backup(output)
                inspect_tailor_upgrade_source(output)
        except Exception:
            backup.unlink(missing_ok=True)
            raise

        migration = (
            Path(__file__).parent / "shop" / "migrations" / "002_tailors.sql"
        ).read_text(encoding="utf-8")
        try:
            source.executescript("BEGIN IMMEDIATE;\n" + migration)
            source.commit()
        except Exception:
            source.rollback()
            raise
        inspect_database(source)
    return backup


def backup_database(database, destination):
    """SQLite's backup API captures committed WAL data, including during service use."""
    target = Path(destination).expanduser().resolve()
    if target == database.resolve():
        raise ValueError("The backup destination must differ from the working database.")
    target.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation refuses to overwrite an earlier backup, including empty files.
    target.touch(exist_ok=False)
    try:
        with closing(connect_database(database)) as source:
            with closing(sqlite3.connect(str(target), isolation_level=None)) as output:
                source.backup(output)
                inspect_database(output)
    except Exception:
        # Only our newly reserved output is removed; the source is never modified.
        target.unlink(missing_ok=True)
        raise
    return target


def restore_database(source_path, data_dir):
    """Restore only to a NEW folder. Never overwrite the working database."""
    source_path = Path(source_path).expanduser().resolve(strict=True)
    if data_dir.exists():
        raise ValueError("Restore needs a new data directory. Existing directories are never overwritten.")
    target = data_dir / "inventory.sqlite3"
    try:
        with closing(sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True)) as source:
            inspect_database(source)
            data_dir.mkdir(parents=True, exist_ok=False)
            with closing(sqlite3.connect(str(target), isolation_level=None)) as output:
                source.backup(output)
                inspect_database(output)
                output.execute("BEGIN IMMEDIATE")
                try:
                    output.execute("UPDATE settings SET value = ? WHERE key = 'secret_key'", (secrets.token_urlsafe(48),))
                    output.execute("UPDATE login_guard SET failures = 0, window_start = 0 WHERE id = 1")
                    output.commit()
                except Exception:
                    output.rollback()
                    raise
    except Exception:
        # Cleanup is limited to the new restore directory created by this call.
        target.unlink(missing_ok=True)
        Path(str(target) + "-wal").unlink(missing_ok=True)
        Path(str(target) + "-shm").unlink(missing_ok=True)
        if data_dir.exists():
            data_dir.rmdir()
        raise
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local shop inventory foundation")
    parser.add_argument("--data-dir", default=str(PROJECT_ROOT / "data"), help="Local database directory (default: project/data)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Create a new database and owner; never overwrite existing data")
    commands.add_parser("check", help="Check database integrity and schema; no stock changes")
    upgrade_cmd = commands.add_parser(
        "upgrade-v5",
        help="Back up and explicitly upgrade a verified schema-v4 database for Tailors",
    )
    upgrade_cmd.add_argument(
        "--backup-to", required=True,
        help="New backup filename retained as the schema-v4 recovery copy",
    )
    commands.add_parser("reset-password", help="Prompt for a new owner password; invalidates signed-in sessions")
    serve_cmd = commands.add_parser("serve", help="Start the local service; no auto-init or migration")
    serve_cmd.add_argument("--host", default="127.0.0.1", help="Loopback or a specific private IPv4 address on the main computer")
    serve_cmd.add_argument("--port", type=int, default=8080)
    backup_cmd = commands.add_parser("backup", help="Create a new SQLite backup without overwriting files")
    backup_cmd.add_argument("--to", required=True, help="New backup filename, preferably on a separate device")
    restore_cmd = commands.add_parser("restore", help="Restore a backup into a NEW --data-dir")
    restore_cmd.add_argument("--from", dest="source", required=True)
    args = parser.parse_args(argv)
    try:
        data_dir = local_path(args.data_dir)
        database = data_dir / "inventory.sqlite3"
        if args.command == "init":
            if database.exists():
                raise ValueError("The database already exists. Init will not overwrite or reseed it.")
            username = input("Owner username: ").strip()
            if not username or len(username) > 60 or any(ord(c) < 32 for c in username):
                raise ValueError("Use a non-empty owner username of at most 60 characters.")
            password_hash = new_password()
            initialize_database(database, username, password_hash, secrets.token_urlsafe(48))
            print(
                f"Created {database}. Seven product definitions; no sample brands, stock, "
                "customers, stitching rates or Tailors."
            )
        elif args.command == "check":
            with closing(connect_database(database)) as conn:
                inspect_database(conn)
            print(
                f"SQLite integrity: ok. Foreign keys: ok. Schema version: {SCHEMA_VERSION}. "
                "Product hierarchy: ok. Sales, customer, measurement, tailoring, Tailor-assignment and payment foundation: ok."
            )
            print("This does not verify browser behaviour, business balances or hardware performance.")
        elif args.command == "upgrade-v5":
            backup = upgrade_tailor_schema(database, args.backup_to)
            print(f"Schema-v4 backup created and checked: {backup}")
            print("Database upgraded to schema version 5 with empty Tailor records.")
        elif args.command == "reset-password":
            # Verify this is an existing application database before prompting.
            with closing(connect_database(database)) as conn:
                inspect_database(conn)
                password_hash = new_password()
                conn.execute("BEGIN IMMEDIATE")
                try:
                    conn.execute("UPDATE users SET password_hash = ?, session_version = session_version + 1", (password_hash,))
                    conn.execute("UPDATE login_guard SET failures = 0, window_start = 0 WHERE id = 1")
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
            print("Owner password changed. Existing sign-in sessions are invalidated.")
        elif args.command == "backup":
            print(f"Backup created and integrity checked: {backup_database(database, args.to)}")
        elif args.command == "restore":
            print(f"Restored and integrity checked: {restore_database(args.source, data_dir)}")
            print("Use the owner credentials from the backup. Previous browser sessions are invalidated.")
        elif args.command == "serve":
            host = ipaddress.IPv4Address(args.host)
            private_ranges = (ipaddress.ip_network("10.0.0.0/8"), ipaddress.ip_network("172.16.0.0/12"), ipaddress.ip_network("192.168.0.0/16"))
            if str(host) != "127.0.0.1" and not any(host in network for network in private_ranges):
                raise ValueError("Bind to 127.0.0.1 or one specific private LAN IPv4 address on the main computer.")
            if not 1024 <= args.port <= 65535:
                raise ValueError("Choose a port between 1024 and 65535.")
            app = create_app(data_dir, trusted_hosts=["localhost", "127.0.0.1", str(host)])
            from waitress import serve
            print(f"Inventory foundation: http://{host}:{args.port} (Ctrl+C stops it)", flush=True)
            serve(app, host=str(host), port=args.port, threads=4, max_request_body_size=32768)
        return 0
    except (ValueError, OSError, sqlite3.Error, RuntimeError) as error:
        print(f"Cannot complete command: {error}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nCommand stopped.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
