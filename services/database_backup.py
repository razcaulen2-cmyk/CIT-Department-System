import os
import re
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import mysql.connector

from config import get_db_connection


BACKUP_MARKER = "-- CIT-DEPT-SYSTEM-BACKUP v1 database="
MAX_RESTORE_BYTES = 1024 * 1024 * 1024
DATABASE_IDENTIFIER = re.compile(r"^[A-Za-z0-9_$-]+$")


class DatabaseBackupError(RuntimeError):
    def __init__(self, message, safety_backup=None):
        super().__init__(message)
        self.safety_backup = safety_backup


def _database_name():
    name = os.getenv("DB_NAME", "department_system")
    if not DATABASE_IDENTIFIER.fullmatch(name):
        raise DatabaseBackupError("The configured database name is not supported for backup and restore.")
    return name


def _backup_directory():
    configured_path = os.getenv("DATABASE_BACKUP_DIR")
    if configured_path:
        directory = Path(configured_path).expanduser()
    else:
        directory = Path.home() / "Documents" / "Department System Backups"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _mysql_tool(name):
    executable = shutil.which(name) or shutil.which(f"{name}.exe")
    if executable:
        return executable

    roots = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "MySQL",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "MySQL",
    ]
    for root in roots:
        if root.is_dir():
            candidates = sorted(root.glob(f"MySQL Server*/bin/{name}.exe"), reverse=True)
            if candidates:
                return str(candidates[0])

    raise DatabaseBackupError(
        f"MySQL {name} was not found. Install MySQL Server with its command-line tools "
        "or add the MySQL bin folder to PATH."
    )


def _option_file_value(value):
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


@contextmanager
def _mysql_defaults_file(directory):
    fd, path = tempfile.mkstemp(
        prefix="mysql_client_",
        suffix=".cnf",
        dir=directory,
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as defaults:
            defaults.write("[client]\n")
            defaults.write(f"host={_option_file_value(os.getenv('DB_HOST', 'localhost'))}\n")
            defaults.write(f"user={_option_file_value(os.getenv('DB_USER', 'root'))}\n")
            defaults.write(f"password={_option_file_value(os.getenv('DB_PASSWORD', ''))}\n")
        yield path
    finally:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass


def _make_backup_filename(database_name):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{database_name}_{stamp}_{uuid4().hex[:8]}.sql"


def get_database_backup_path(filename):
    database_name = _database_name()
    pattern = re.escape(database_name) + r"_\d{8}_\d{6}_[a-f0-9]{8}\.sql"
    if not re.fullmatch(pattern, filename):
        raise DatabaseBackupError("The requested backup file name is invalid.")
    backup_path = _backup_directory() / filename
    if not backup_path.is_file():
        raise DatabaseBackupError("That backup file is not available on this server.")
    return backup_path


def _verify_generated_backup(path, database_name, expected_tables):
    marker = f"{BACKUP_MARKER}{database_name}\n"
    temporary_path = path.with_suffix(".marked.sql")
    create_table_count = 0
    try:
        with temporary_path.open("wb") as marked_dump:
            marked_dump.write(marker.encode("ascii"))
            with path.open("rb") as source:
                for line in source:
                    if re.match(rb"CREATE TABLE [`]?", line, re.IGNORECASE):
                        create_table_count += 1
                    marked_dump.write(line)
        if create_table_count < expected_tables:
            raise DatabaseBackupError(
                f"Backup verification failed: expected at least {expected_tables} table definitions, "
                f"found {create_table_count}."
            )
        temporary_path.replace(path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def stage_restore_upload(stream):
    directory = _backup_directory()
    path = directory / f"restore_upload_{uuid4().hex}.sql"
    size = 0
    try:
        with path.open("wb") as staged:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_RESTORE_BYTES:
                    raise DatabaseBackupError("The selected backup exceeds the 1 GB restore limit.")
                staged.write(chunk)
        if size == 0:
            raise DatabaseBackupError("The selected backup file is empty.")
    except (OSError, DatabaseBackupError):
        if path.exists():
            path.unlink()
        raise
    return path


def create_database_backup():
    database_name = _database_name()
    directory = _backup_directory()
    backup_path = directory / _make_backup_filename(database_name)

    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        cursor.execute("SHOW FULL TABLES")
        expected_tables = sum(1 for row in cursor.fetchall() if row[1] == "BASE TABLE")
    except mysql.connector.Error as error:
        raise DatabaseBackupError(f"Could not inspect the configured database: {error}") from error
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

    try:
        with _mysql_defaults_file(directory) as defaults_path:
            command = [
                _mysql_tool("mysqldump"),
                f"--defaults-extra-file={defaults_path}",
                "--single-transaction",
                "--routines",
                "--triggers",
                "--events",
                "--set-gtid-purged=OFF",
                database_name,
            ]
            with backup_path.open("wb") as output:
                result = subprocess.run(
                    command,
                    stdout=output,
                    stderr=subprocess.PIPE,
                    check=False,
                    timeout=600,
                )
        if result.returncode != 0:
            error_message = result.stderr.decode("utf-8", errors="replace").strip()
            raise DatabaseBackupError(
                "MySQL could not create the database backup."
                + (f" {error_message}" if error_message else "")
            )
        if backup_path.stat().st_size == 0:
            raise DatabaseBackupError("MySQL produced an empty database backup.")
        with backup_path.open("rb") as dump:
            if not dump.readline().startswith(b"-- MySQL dump"):
                raise DatabaseBackupError("MySQL produced a file that is not a valid dump.")
        _verify_generated_backup(backup_path, database_name, expected_tables)
    except (OSError, subprocess.SubprocessError) as error:
        if backup_path.exists():
            backup_path.unlink()
        raise DatabaseBackupError(f"Could not create the database backup: {error}") from error
    except DatabaseBackupError:
        if backup_path.exists():
            backup_path.unlink()
        raise

    return backup_path


def validate_restore_dump(path):
    database_name = _database_name()
    marker_database = None
    declared_databases = set()
    use_statements = set()
    saw_dump_header = False
    first_line = None
    last_nonempty_line = b""

    create_database_pattern = re.compile(
        rb"^\s*CREATE DATABASE\b.*?`([^`]+)`",
        re.IGNORECASE,
    )
    use_pattern = re.compile(rb"^\s*USE\s+`?([A-Za-z0-9_$-]+)`?\s*;", re.IGNORECASE)

    with path.open("rb") as dump:
        for line_number, line in enumerate(dump, start=1):
            if line.strip():
                last_nonempty_line = line.strip()
            if line_number == 1:
                first_line = line
                saw_dump_header = line.startswith(b"-- MySQL dump")
            elif (
                line_number == 2
                and first_line
                and first_line.startswith(BACKUP_MARKER.encode("ascii"))
            ):
                saw_dump_header = line.startswith(b"-- MySQL dump")
            if line.startswith(BACKUP_MARKER.encode("ascii")):
                try:
                    marker_database = line.decode("ascii").strip()[len(BACKUP_MARKER):]
                except UnicodeDecodeError as error:
                    raise DatabaseBackupError("The backup marker is malformed.") from error
            database_match = create_database_pattern.match(line)
            if database_match:
                declared_databases.add(database_match.group(1).decode("ascii", errors="replace"))
            use_match = use_pattern.match(line)
            if use_match:
                use_statements.add(use_match.group(1).decode("ascii", errors="replace"))

    if not saw_dump_header:
        raise DatabaseBackupError("Choose a valid MySQL dump created by this system or mysqldump.")
    if not last_nonempty_line.startswith(b"-- Dump completed on "):
        raise DatabaseBackupError("The selected backup appears incomplete; its mysqldump footer is missing.")
    if marker_database == database_name:
        pass
    elif marker_database:
        raise DatabaseBackupError("This backup belongs to a different database.")
    elif database_name not in declared_databases and database_name not in use_statements:
        raise DatabaseBackupError(
            "This dump does not identify the configured database. Use a backup created for this system."
        )
    if any(name != database_name for name in declared_databases | use_statements):
        raise DatabaseBackupError("This backup contains a database selection that does not match this system.")
    if not path.stat().st_size:
        raise DatabaseBackupError("The selected backup file is empty.")
    return database_name


def _quote_identifier(identifier):
    return "`" + identifier.replace("`", "``") + "`"


def _clear_database_objects(database_name):
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        cursor.execute("SET FOREIGN_KEY_CHECKS=0")
        cursor.execute("SHOW FULL TABLES")
        objects = cursor.fetchall()

        for name, object_type in objects:
            if object_type == "VIEW":
                cursor.execute(f"DROP VIEW IF EXISTS {_quote_identifier(name)}")
        for name, object_type in objects:
            if object_type != "VIEW":
                cursor.execute(f"DROP TABLE IF EXISTS {_quote_identifier(name)}")

        cursor.execute(
            "SELECT ROUTINE_NAME, ROUTINE_TYPE FROM INFORMATION_SCHEMA.ROUTINES "
            "WHERE ROUTINE_SCHEMA=%s",
            (database_name,),
        )
        routines = cursor.fetchall()
        for name, routine_type in routines:
            cursor.execute(
                f"DROP {routine_type} IF EXISTS {_quote_identifier(name)}"
            )

        cursor.execute(
            "SELECT EVENT_NAME FROM INFORMATION_SCHEMA.EVENTS WHERE EVENT_SCHEMA=%s",
            (database_name,),
        )
        for (name,) in cursor.fetchall():
            cursor.execute(f"DROP EVENT IF EXISTS {_quote_identifier(name)}")
    finally:
        try:
            cursor.execute("SET FOREIGN_KEY_CHECKS=1")
        finally:
            cursor.close()
            connection.close()


def _import_dump(path, database_name):
    directory = _backup_directory()
    with _mysql_defaults_file(directory) as defaults_path:
        command = [
            _mysql_tool("mysql"),
            f"--defaults-extra-file={defaults_path}",
            "--binary-mode=1",
            database_name,
        ]
        with path.open("rb") as dump:
            result = subprocess.run(
                command,
                stdin=dump,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=600,
            )
    if result.returncode != 0:
        error_message = result.stderr.decode("utf-8", errors="replace").strip()
        raise DatabaseBackupError(
            "MySQL could not restore the selected backup."
            + (f" {error_message}" if error_message else "")
        )


def restore_database(path):
    database_name = validate_restore_dump(path)
    safety_backup = create_database_backup()

    try:
        _clear_database_objects(database_name)
        _import_dump(path, database_name)
    except (DatabaseBackupError, mysql.connector.Error, OSError, subprocess.SubprocessError) as restore_error:
        try:
            _clear_database_objects(database_name)
            _import_dump(safety_backup, database_name)
        except (DatabaseBackupError, mysql.connector.Error, OSError, subprocess.SubprocessError) as recovery_error:
            raise DatabaseBackupError(
                "Restore failed, and automatic recovery from the safety backup also failed. "
                f"The safety backup is retained at {safety_backup}. The live database may need manual recovery. "
                f"Restore error: {restore_error}; recovery error: {recovery_error}",
                safety_backup=safety_backup,
            ) from restore_error
        raise DatabaseBackupError(
            "The selected backup could not be restored. The original database was recovered from the "
            f"automatic safety backup at {safety_backup}. Error: {restore_error}",
            safety_backup=safety_backup,
        ) from restore_error

    return safety_backup
