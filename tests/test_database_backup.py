import tempfile
import unittest
from pathlib import Path
from unittest.mock import call, patch

from services import database_backup


class DatabaseBackupValidationTests(unittest.TestCase):
    def write_dump(self, content):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        path = Path(temp_dir.name) / "backup.sql"
        path.write_text(content, encoding="ascii")
        return path

    def test_accepts_backup_generated_for_configured_database(self):
        path = self.write_dump(
            "-- CIT-DEPT-SYSTEM-BACKUP v1 database=department_system\n"
            "-- MySQL dump 10.13\n"
            "CREATE TABLE `students` (id int);\n"
            "-- Dump completed on 2026-10-19 18:00:00\n"
        )

        self.assertEqual(
            database_backup.validate_restore_dump(path),
            "department_system",
        )

    def test_accepts_legacy_mysqldump_declaring_the_configured_database(self):
        path = self.write_dump(
            "-- MySQL dump 10.13\n"
            "CREATE DATABASE /*!32312 IF NOT EXISTS*/ `department_system`;\n"
            "USE `department_system`;\n"
            "-- Dump completed on 2026-10-19 18:00:00\n"
        )

        self.assertEqual(
            database_backup.validate_restore_dump(path),
            "department_system",
        )

    def test_rejects_dump_for_another_database(self):
        path = self.write_dump(
            "-- MySQL dump 10.13\n"
            "CREATE DATABASE `another_database`;\n"
            "USE `another_database`;\n"
            "-- Dump completed on 2026-10-19 18:00:00\n"
        )

        with self.assertRaisesRegex(
            database_backup.DatabaseBackupError,
            "does not identify the configured database",
        ):
            database_backup.validate_restore_dump(path)

    def test_rejects_dump_switching_to_another_database(self):
        path = self.write_dump(
            "-- CIT-DEPT-SYSTEM-BACKUP v1 database=department_system\n"
            "-- MySQL dump 10.13\n"
            "USE `department_system`;\n"
            "USE `another_database`;\n"
            "-- Dump completed on 2026-10-19 18:00:00\n"
        )

        with self.assertRaisesRegex(
            database_backup.DatabaseBackupError,
            "does not match this system",
        ):
            database_backup.validate_restore_dump(path)

    def test_rejects_a_truncated_dump_without_completion_footer(self):
        path = self.write_dump(
            "-- CIT-DEPT-SYSTEM-BACKUP v1 database=department_system\n"
            "-- MySQL dump 10.13\n"
            "CREATE TABLE `students` (id int);\n"
        )

        with self.assertRaisesRegex(
            database_backup.DatabaseBackupError,
            "appears incomplete",
        ):
            database_backup.validate_restore_dump(path)


class DatabaseRestoreSafetyTests(unittest.TestCase):
    def test_creates_safety_backup_before_replacing_database(self):
        safety_backup = Path("current-safety.sql")
        calls = []
        with patch.object(database_backup, "validate_restore_dump", return_value="department_system"):
            with patch.object(database_backup, "create_database_backup", return_value=safety_backup) as backup:
                with patch.object(database_backup, "_clear_database_objects", side_effect=lambda name: calls.append(("clear", name))):
                    with patch.object(database_backup, "_import_dump", side_effect=lambda path, name: calls.append(("import", path, name))):
                        result = database_backup.restore_database(Path("chosen.sql"))

        backup.assert_called_once_with()
        self.assertEqual(result, safety_backup)
        self.assertEqual(
            calls,
            [
                ("clear", "department_system"),
                ("import", Path("chosen.sql"), "department_system"),
            ],
        )

    def test_recovers_current_database_if_selected_dump_import_fails(self):
        safety_backup = Path("current-safety.sql")
        with patch.object(database_backup, "validate_restore_dump", return_value="department_system"):
            with patch.object(database_backup, "create_database_backup", return_value=safety_backup):
                with patch.object(database_backup, "_clear_database_objects"):
                    with patch.object(
                        database_backup,
                        "_import_dump",
                        side_effect=[
                            database_backup.DatabaseBackupError("selected dump failed"),
                            None,
                        ],
                    ) as import_dump:
                        with self.assertRaisesRegex(
                            database_backup.DatabaseBackupError,
                            "original database was recovered",
                        ) as raised:
                            database_backup.restore_database(Path("chosen.sql"))

        self.assertEqual(raised.exception.safety_backup, safety_backup)
        self.assertEqual(
            import_dump.call_args_list,
            [
                call(Path("chosen.sql"), "department_system"),
                call(safety_backup, "department_system"),
            ],
        )

    def test_reports_safety_backup_if_automatic_recovery_fails(self):
        safety_backup = Path("current-safety.sql")
        with patch.object(database_backup, "validate_restore_dump", return_value="department_system"):
            with patch.object(database_backup, "create_database_backup", return_value=safety_backup):
                with patch.object(database_backup, "_clear_database_objects"):
                    with patch.object(
                        database_backup,
                        "_import_dump",
                        side_effect=[
                            database_backup.DatabaseBackupError("selected dump failed"),
                            database_backup.DatabaseBackupError("safety dump failed"),
                        ],
                    ):
                        with self.assertRaisesRegex(
                            database_backup.DatabaseBackupError,
                            "automatic recovery.*also failed",
                        ) as raised:
                            database_backup.restore_database(Path("chosen.sql"))

        self.assertEqual(raised.exception.safety_backup, safety_backup)


if __name__ == "__main__":
    unittest.main()
