import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app_factory import create_app
from services.database_backup import DatabaseBackupError


class DatabaseBackupRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session["admin"] = True

    def test_backup_route_confirms_creation_and_shows_download_link(self):
        with tempfile.TemporaryDirectory() as directory:
            backup = Path(directory) / "department_system_20261019_120000_a1b2c3d4.sql"
            backup.write_text("-- backup", encoding="ascii")
            with patch("routes.admin.create_database_backup", return_value=backup):
                with patch("routes.admin.get_database_backup_path", return_value=backup):
                    response = self.client.get("/database/backup", follow_redirects=True)

            self.assertEqual(response.status_code, 200)
            self.assertIn(b"Database backup created successfully", response.data)
            self.assertIn(backup.name.encode("ascii"), response.data)
            self.assertIn(b"/database/backups/", response.data)
            self.assertIn(f'download="{backup.name}"'.encode("ascii"), response.data)
            self.assertIn(b"showSaveFilePicker", response.data)
            self.assertIn(b"response.body.pipeTo(writable)", response.data)

    def test_saved_backup_route_returns_a_download(self):
        with tempfile.TemporaryDirectory() as directory:
            backup = Path(directory) / "department_system_20261019_120000_a1b2c3d4.sql"
            backup.write_text("-- backup", encoding="ascii")
            with patch("routes.admin.get_database_backup_path", return_value=backup):
                response = self.client.get(
                    f"/database/backups/{backup.name}",
                    headers={"If-None-Match": "*"},
                )

            self.assertEqual(response.status_code, 200)
            self.assertIn("attachment;", response.headers["Content-Disposition"])
            self.assertEqual(response.mimetype, "application/octet-stream")
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertTrue(response.data.startswith(b"-- backup"))
            response.close()

    def test_backup_failure_is_shown_after_redirect(self):
        with patch(
            "routes.admin.create_database_backup",
            side_effect=DatabaseBackupError("MySQL client is unavailable"),
        ):
            response = self.client.get("/database/backup", follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Database backup failed: MySQL client is unavailable", response.data)

    def test_backup_page_explains_download_and_shows_progress_feedback(self):
        response = self.client.get("/upload-csv")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"databaseBackupStatus", response.data)
        self.assertIn(b"role=\"status\"", response.data)
        self.assertIn(b"The backup is saved on the server", response.data)
        self.assertIn(b"press Ctrl+J", response.data)


    def test_restore_rejects_a_missing_or_invalid_csrf_token(self):
        with patch("routes.admin.restore_database_backup") as restore:
            response = self.client.post(
                "/database/restore",
                data={"csrf_token": "", "confirmation": "RESTORE"},
            )

        self.assertEqual(response.status_code, 302)
        restore.assert_not_called()

    def test_restore_requires_explicit_typed_confirmation(self):
        with self.client.session_transaction() as session:
            session["database_restore_csrf"] = "valid-token"
        with patch("routes.admin.restore_database_backup") as restore:
            response = self.client.post(
                "/database/restore",
                data={
                    "csrf_token": "valid-token",
                    "confirmation": "yes",
                    "backup_file": (io.BytesIO(b"invalid"), "backup.sql"),
                },
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 302)
        restore.assert_not_called()

    def test_restore_creates_and_retains_safety_backup_link(self):
        with tempfile.TemporaryDirectory() as directory:
            staged_backup = Path(directory) / "staged.sql"
            staged_backup.write_text("-- validated by mock", encoding="ascii")
            safety_backup = Path(directory) / "department_system_20261019_120000_a1b2c3d4.sql"
            with self.client.session_transaction() as session:
                session["database_restore_csrf"] = "valid-token"
            with patch("routes.admin.stage_restore_upload", return_value=staged_backup):
                with patch("routes.admin.restore_database_backup", return_value=safety_backup) as restore:
                    response = self.client.post(
                        "/database/restore",
                        data={
                            "csrf_token": "valid-token",
                            "confirmation": "RESTORE",
                            "backup_file": (io.BytesIO(b"backup"), "backup.sql"),
                        },
                        content_type="multipart/form-data",
                    )

            self.assertEqual(response.status_code, 302)
            restore.assert_called_once_with(staged_backup)
            self.assertFalse(staged_backup.exists())
            with self.client.session_transaction() as session:
                self.assertEqual(session["latest_database_backup"], safety_backup.name)


if __name__ == "__main__":
    unittest.main()
