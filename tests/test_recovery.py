"""Backup and restore safety checks for the user-run verification step."""

from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from manage import backup_database, inspect_database, restore_database, upgrade_tailor_schema
from shop.db import connect_database, initialize_database


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.database = self.data / "inventory.sqlite3"
        initialize_database(self.database, "owner", "test-password-hash", "s" * 48)

    def tearDown(self):
        self.temp.cleanup()

    def test_backup_is_checked_and_never_overwritten(self):
        target = self.root / "backups" / "inventory.sqlite3"
        backup_database(self.database, target)
        with closing(connect_database(target)) as connection:
            inspect_database(connection)
        with self.assertRaises(FileExistsError):
            backup_database(self.database, target)

    def test_schema_v4_upgrade_creates_verified_backup_before_tailor_tables(self):
        with closing(connect_database(self.database)) as connection:
            connection.execute("DROP TABLE tailoring_item_assignments")
            connection.execute("DROP TABLE tailors")
            connection.execute(
                "UPDATE settings SET value = 'measurement-templates-rates-v4' "
                "WHERE key = 'schema_identity'"
            )
            connection.execute("PRAGMA user_version = 4")
            connection.commit()

        backup = self.root / "backups" / "before-tailors.sqlite3"
        upgrade_tailor_schema(self.database, backup)

        with closing(connect_database(backup)) as connection:
            self.assertEqual(4, connection.execute("PRAGMA user_version").fetchone()[0])
            tables = {
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            self.assertNotIn("tailors", tables)
        with closing(connect_database(self.database)) as connection:
            inspect_database(connection)
            self.assertEqual(5, connection.execute("PRAGMA user_version").fetchone()[0])
            self.assertIsNotNone(
                connection.execute(
                    "SELECT name FROM sqlite_master WHERE name = 'tailors'"
                ).fetchone()
            )

    def test_restore_uses_new_directory_and_rotates_session_secret(self):
        backup = self.root / "backup.sqlite3"
        backup_database(self.database, backup)
        with closing(connect_database(backup)) as connection:
            old_secret = connection.execute("SELECT value FROM settings WHERE key = 'secret_key'").fetchone()[0]
        restored = restore_database(backup, self.root / "restored-data")
        with closing(connect_database(restored)) as connection:
            inspect_database(connection)
            new_secret = connection.execute("SELECT value FROM settings WHERE key = 'secret_key'").fetchone()[0]
        self.assertNotEqual(old_secret, new_secret)
        with self.assertRaises(ValueError):
            restore_database(backup, self.root / "restored-data")


if __name__ == "__main__":
    unittest.main()
