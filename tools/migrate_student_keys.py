import argparse
from datetime import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import get_db_connection


FINANCIAL_TABLES = (
    "student_funds",
    "fines",
    "transactions",
    "transaction_adjustments",
    "fine_payment_allocations",
)
REQUIRED_TABLES = ("students", "student_funds", "fines", "transactions")
OPTIONAL_TABLE_DDL = {
    "transaction_adjustments": """
        CREATE TABLE transaction_adjustments (
            adjustment_id INT AUTO_INCREMENT PRIMARY KEY,
            transaction_id INT NOT NULL,
            student_key INT NULL,
            student_id VARCHAR(32) NOT NULL,
            account_type VARCHAR(16) NOT NULL,
            amount_delta DECIMAL(10, 2) NOT NULL,
            remarks TEXT NOT NULL,
            balance_row_id INT NULL,
            event_id INT NULL,
            fine_type VARCHAR(50) NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_adjustments_transaction (transaction_id),
            INDEX idx_adjustments_student_account (student_key, account_type),
            INDEX idx_adjustments_balance_row (balance_row_id),
            INDEX idx_adjustments_fine_identity (student_key, event_id, fine_type)
        ) ENGINE=InnoDB
    """,
    "fine_payment_allocations": """
        CREATE TABLE fine_payment_allocations (
            allocation_id INT AUTO_INCREMENT PRIMARY KEY,
            transaction_id INT NOT NULL,
            source_fine_id INT NOT NULL,
            student_key INT NULL,
            student_id VARCHAR(32) NOT NULL,
            event_id INT NOT NULL,
            fine_type VARCHAR(50) NOT NULL,
            amount_paid DECIMAL(10, 2) NOT NULL,
            UNIQUE KEY uq_fine_payment_source (transaction_id, source_fine_id),
            INDEX idx_fine_payment_identity (student_key, event_id, fine_type)
        ) ENGINE=InnoDB
    """,
}
INDEXES = (
    ("student_funds", "idx_student_funds_student_key", "student_key", False),
    (
        "fines",
        "idx_fines_student_event_type",
        "student_key, event_id, fine_type",
        False,
    ),
    ("fines", "idx_fines_student_key", "student_key", False),
    ("transactions", "idx_transactions_student_key", "student_key", False),
    (
        "transaction_adjustments",
        "idx_adjustments_student_account",
        "student_key, account_type",
        False,
    ),
    (
        "transaction_adjustments",
        "idx_adjustments_fine_identity",
        "student_key, event_id, fine_type",
        False,
    ),
    (
        "fine_payment_allocations",
        "idx_fine_payment_identity",
        "student_key, event_id, fine_type",
        False,
    ),
)
FOREIGN_KEYS = (
    ("student_funds", "fk_student_funds_student_key"),
    ("fines", "fk_fines_student_key"),
    ("transactions", "fk_transactions_student_key"),
    ("transaction_adjustments", "fk_adjustments_student_key"),
    ("fine_payment_allocations", "fk_fine_payment_student_key"),
)


def table_exists(cursor, table_name):
    cursor.execute(
        """
        SELECT 1
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s
        LIMIT 1
        """,
        (table_name,),
    )
    return cursor.fetchone() is not None


def get_columns(cursor, table_name):
    cursor.execute(
        """
        SELECT COLUMN_NAME, IS_NULLABLE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s
        """,
        (table_name,),
    )
    return {row[0]: row[1] for row in cursor.fetchall()}


def get_column_names(cursor, table_name):
    cursor.execute(
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s
        ORDER BY ORDINAL_POSITION
        """,
        (table_name,),
    )
    return [row[0] for row in cursor.fetchall()]


def index_exists(cursor, table_name, index_name):
    cursor.execute(
        """
        SELECT 1
        FROM INFORMATION_SCHEMA.STATISTICS
        WHERE TABLE_SCHEMA=DATABASE()
          AND TABLE_NAME=%s AND INDEX_NAME=%s
        LIMIT 1
        """,
        (table_name, index_name),
    )
    return cursor.fetchone() is not None


def foreign_key_exists(cursor, table_name, constraint_name):
    cursor.execute(
        """
        SELECT 1
        FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS
        WHERE CONSTRAINT_SCHEMA=DATABASE()
          AND TABLE_NAME=%s
          AND CONSTRAINT_NAME=%s
          AND CONSTRAINT_TYPE='FOREIGN KEY'
        LIMIT 1
        """,
        (table_name, constraint_name),
    )
    return cursor.fetchone() is not None


def make_backup(cursor, suffix):
    backups = []
    for table_name in FINANCIAL_TABLES:
        if not table_exists(cursor, table_name):
            continue
        backup_name = f"backup_student_key_{suffix}_{table_name}"
        if table_exists(cursor, backup_name):
            raise RuntimeError(f"Backup table already exists: {backup_name}")
        cursor.execute(f"CREATE TABLE `{backup_name}` LIKE `{table_name}`")
        cursor.execute(f"INSERT INTO `{backup_name}` SELECT * FROM `{table_name}`")
        cursor.execute(f"SELECT COUNT(*) FROM `{table_name}`")
        source_count = cursor.fetchone()[0]
        cursor.execute(f"SELECT COUNT(*) FROM `{backup_name}`")
        backup_count = cursor.fetchone()[0]
        if source_count != backup_count:
            raise RuntimeError(
                f"Backup verification failed for {table_name}: "
                f"{source_count} source rows vs {backup_count} backup rows."
            )
        backups.append((table_name, backup_name, source_count))
    return backups


def ensure_optional_tables(cursor):
    for table_name, ddl in OPTIONAL_TABLE_DDL.items():
        if not table_exists(cursor, table_name):
            cursor.execute(ddl)


def ensure_student_key_column(cursor, table_name):
    columns = get_columns(cursor, table_name)
    if "student_id" not in columns:
        raise RuntimeError(f"{table_name} is missing the legacy student_id column.")
    if "student_key" not in columns:
        cursor.execute(
            f"ALTER TABLE `{table_name}` ADD COLUMN student_key INT NULL"
        )


def backfill_student_keys(cursor, table_name):
    cursor.execute(
        f"""
        UPDATE `{table_name}` AS record
        JOIN students AS student
          ON BINARY student.student_id=BINARY record.student_id
        SET record.student_key=student.id
        WHERE record.student_key IS NULL
        """
    )
    cursor.execute(
        f"""
        UPDATE `{table_name}` AS record
        JOIN students AS student
          ON BINARY record.student_id=BINARY CAST(student.id AS CHAR)
        LEFT JOIN students AS external_match
          ON BINARY external_match.student_id=BINARY record.student_id
        SET record.student_key=student.id
        WHERE record.student_key IS NULL AND external_match.id IS NULL
        """
    )


def count_unmapped_rows(cursor, table_name):
    cursor.execute(
        f"SELECT COUNT(*) FROM `{table_name}` WHERE student_key IS NULL"
    )
    return cursor.fetchone()[0]


def archive_unmapped_fines(cursor):
    unresolved_count = count_unmapped_rows(cursor, "fines")
    if not unresolved_count:
        return 0

    archive_table = "unresolved_student_fines"
    if not table_exists(cursor, archive_table):
        cursor.execute(f"CREATE TABLE `{archive_table}` LIKE fines")

    archive_columns = get_columns(cursor, archive_table)
    columns = [
        column
        for column in get_column_names(cursor, "fines")
        if column in archive_columns
    ]
    column_list = ", ".join(f"`{column}`" for column in columns)
    cursor.execute(
        f"""
        INSERT IGNORE INTO `{archive_table}` ({column_list})
        SELECT {column_list}
        FROM fines
        WHERE student_key IS NULL
        """
    )

    if "archived_at" not in archive_columns:
        cursor.execute(
            f"""
            ALTER TABLE `{archive_table}`
            ADD COLUMN archived_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            """
        )
    if "archive_reason" not in archive_columns:
        cursor.execute(
            f"""
            ALTER TABLE `{archive_table}`
            ADD COLUMN archive_reason VARCHAR(255) NOT NULL
                DEFAULT 'No matching student record was available during key migration'
            """
        )

    cursor.execute(
        f"""
        SELECT COUNT(*)
        FROM fines AS source
        JOIN `{archive_table}` AS archived
          ON archived.fine_id=source.fine_id
        WHERE source.student_key IS NULL
        """
    )
    archived_count = cursor.fetchone()[0]
    if archived_count != unresolved_count:
        raise RuntimeError(
            "Unable to verify the archive of all unmatched fines; "
            "no unmatched fine rows were removed."
        )

    cursor.execute("DELETE FROM fines WHERE student_key IS NULL")
    if cursor.rowcount != unresolved_count:
        raise RuntimeError(
            "Unexpected number of unmatched fines removed after archive verification."
        )
    return unresolved_count


def count_duplicate_fines(cursor):
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM (
            SELECT student_key, event_id, fine_type
            FROM fines
            WHERE student_key IS NOT NULL
              AND event_id IS NOT NULL
              AND fine_type IS NOT NULL
            GROUP BY student_key, event_id, fine_type
            HAVING COUNT(*) > 1
        ) AS duplicate_fines
        """
    )
    return cursor.fetchone()[0]


def count_ambiguous_rows(cursor, table_name):
    cursor.execute(
        f"""
        SELECT COUNT(*)
        FROM `{table_name}` AS record
        JOIN students AS external_match
          ON BINARY external_match.student_id=BINARY record.student_id
        JOIN students AS internal_match
          ON BINARY record.student_id=BINARY CAST(internal_match.id AS CHAR)
        WHERE external_match.id<>internal_match.id
        """
    )
    return cursor.fetchone()[0]


def ensure_not_null_student_key(cursor, table_name):
    if get_columns(cursor, table_name)["student_key"] == "YES":
        cursor.execute(
            f"ALTER TABLE `{table_name}` MODIFY COLUMN student_key INT NOT NULL"
        )


def ensure_index(cursor, table_name, index_name, columns, unique):
    if index_exists(cursor, table_name, index_name):
        return
    unique_clause = "UNIQUE " if unique else ""
    cursor.execute(
        f"CREATE {unique_clause}INDEX `{index_name}` "
        f"ON `{table_name}` ({columns})"
    )


def apply_migration(cursor):
    for table_name in REQUIRED_TABLES:
        if not table_exists(cursor, table_name):
            raise RuntimeError(f"Required table is missing: {table_name}")

    ensure_optional_tables(cursor)
    for table_name in FINANCIAL_TABLES:
        ensure_student_key_column(cursor, table_name)

    ambiguous = {
        table_name: count_ambiguous_rows(cursor, table_name)
        for table_name in FINANCIAL_TABLES
    }
    ambiguous = {table: count for table, count in ambiguous.items() if count}
    if ambiguous:
        raise RuntimeError(
            "Some legacy IDs match one student's current ID and another "
            f"student's internal key: {ambiguous}. Resolve these rows before migrating."
        )

    for table_name in FINANCIAL_TABLES:
        backfill_student_keys(cursor, table_name)

    unmapped = {
        table_name: count_unmapped_rows(cursor, table_name)
        for table_name in FINANCIAL_TABLES
    }
    archived_fines = archive_unmapped_fines(cursor)
    unmapped = {
        table: count
        for table, count in unmapped.items()
        if count and table != "fines"
    }
    if unmapped:
        raise RuntimeError(
            "Could not map every legacy financial row to a student. "
            f"Unmapped row counts: {unmapped}. Resolve these rows and rerun."
        )
    if archived_fines:
        print(
            f"Archived {archived_fines} unresolved fines in "
            "unresolved_student_fines."
        )

    duplicate_fines = count_duplicate_fines(cursor)
    if duplicate_fines:
        print(
            f"Preserving {duplicate_fines} duplicate fine groups and their "
            "payment history; no fine rows will be merged."
        )

    for table_name in FINANCIAL_TABLES:
        ensure_not_null_student_key(cursor, table_name)

    for table_name, index_name, columns, unique in INDEXES:
        ensure_index(cursor, table_name, index_name, columns, unique)

    for table_name, constraint_name in FOREIGN_KEYS:
        if not foreign_key_exists(cursor, table_name, constraint_name):
            cursor.execute(
                f"""
                ALTER TABLE `{table_name}`
                ADD CONSTRAINT `{constraint_name}`
                FOREIGN KEY (student_key) REFERENCES students(id)
                """
            )


def report_dry_run(cursor):
    for table_name in REQUIRED_TABLES:
        if not table_exists(cursor, table_name):
            raise RuntimeError(f"Required table is missing: {table_name}")

    tables = [table for table in FINANCIAL_TABLES if table_exists(cursor, table)]
    print("Financial row counts and legacy IDs without a student match:")
    for table_name in tables:
        cursor.execute(f"SELECT COUNT(*) FROM `{table_name}`")
        row_count = cursor.fetchone()[0]
        columns = get_columns(cursor, table_name)
        key_filter = "AND record.student_key IS NULL" if "student_key" in columns else ""
        cursor.execute(
            f"""
            SELECT COUNT(*)
            FROM `{table_name}` AS record
            WHERE 1=1 {key_filter}
              AND NOT EXISTS (
                  SELECT 1 FROM students
                  WHERE BINARY students.student_id=BINARY record.student_id
              )
              AND NOT EXISTS (
                  SELECT 1 FROM students
                  WHERE BINARY record.student_id=BINARY CAST(students.id AS CHAR)
              )
            """
        )
        unmapped = cursor.fetchone()[0]
        ambiguous = count_ambiguous_rows(cursor, table_name)
        print(
            f"  {table_name}: {row_count} rows; "
            f"{unmapped} unresolved; {ambiguous} ambiguous"
        )
    print("Unresolved fine rows will be preserved in unresolved_student_fines.")


def main():
    parser = argparse.ArgumentParser(
        description="Migrate finance records to immutable students.id keys."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report row counts and unmapped legacy IDs without changing data.",
    )
    args = parser.parse_args()

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if args.dry_run:
            report_dry_run(cursor)
            return

        for table_name in REQUIRED_TABLES:
            if not table_exists(cursor, table_name):
                raise RuntimeError(f"Required table is missing: {table_name}")
        suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
        backups = make_backup(cursor, suffix)
        conn.commit()
        print("Verified backups:")
        for source, backup, count in backups:
            print(f"  {backup}: {count} rows copied from {source}")

        apply_migration(cursor)
        conn.commit()
        print("Student key migration completed.")
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    main()
