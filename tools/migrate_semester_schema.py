import argparse
from datetime import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import get_db_connection


TABLES_TO_BACK_UP = (
    "school_terms",
    "events",
    "student_funds",
    "fines",
    "attendance",
    "paper_attendance",
    "transactions",
)


def get_columns(cursor, table_name):
    cursor.execute(
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s
        """,
        (table_name,),
    )
    return {row[0] for row in cursor.fetchall()}


def ensure_column(cursor, table_name, column_name, definition):
    if column_name not in get_columns(cursor, table_name):
        cursor.execute(
            f"ALTER TABLE `{table_name}` ADD COLUMN `{column_name}` {definition}"
        )


def ensure_index(cursor, table_name, index_name, columns):
    cursor.execute(
        """
        SELECT 1
        FROM INFORMATION_SCHEMA.STATISTICS
        WHERE TABLE_SCHEMA=DATABASE()
          AND TABLE_NAME=%s
          AND INDEX_NAME=%s
        LIMIT 1
        """,
        (table_name, index_name),
    )
    if cursor.fetchone() is None:
        cursor.execute(
            f"CREATE INDEX `{index_name}` ON `{table_name}` ({columns})"
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


def make_backup(cursor, suffix):
    backups = []
    for table_name in TABLES_TO_BACK_UP:
        if not table_exists(cursor, table_name):
            continue
        backup_name = f"backup_{suffix}_{table_name}"
        if table_exists(cursor, backup_name):
            raise RuntimeError(f"Backup table already exists: {backup_name}")
        cursor.execute(f"CREATE TABLE `{backup_name}` LIKE `{table_name}`")
        cursor.execute(
            f"INSERT INTO `{backup_name}` SELECT * FROM `{table_name}`"
        )
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


def apply_migration(cursor, active_term_id):
    term_columns = get_columns(cursor, "school_terms")
    if "id" not in term_columns and "term_id" in term_columns:
        cursor.execute(
            "ALTER TABLE school_terms CHANGE COLUMN term_id id INT NOT NULL AUTO_INCREMENT"
        )

    ensure_column(cursor, "school_terms", "start_date", "DATE NULL")
    ensure_column(cursor, "school_terms", "end_date", "DATE NULL")
    ensure_column(
        cursor,
        "school_terms",
        "fund_amount",
        "DECIMAL(10, 2) NOT NULL DEFAULT 0",
    )

    ensure_column(cursor, "events", "semester_id", "INT NULL")
    ensure_index(cursor, "events", "idx_events_semester", "semester_id")

    ensure_column(cursor, "student_funds", "semester_id", "INT NULL")
    ensure_column(cursor, "student_funds", "assessed_amount", "DECIMAL(10, 2) NULL")
    ensure_column(
        cursor,
        "student_funds",
        "paid_amount",
        "DECIMAL(10, 2) NOT NULL DEFAULT 0",
    )
    ensure_column(
        cursor,
        "student_funds",
        "is_semester_fund",
        "BOOLEAN NOT NULL DEFAULT FALSE",
    )
    ensure_index(cursor, "student_funds", "idx_student_funds_semester", "semester_id")

    ensure_column(cursor, "fines", "semester_id", "INT NULL")
    ensure_column(cursor, "fines", "assessed_amount", "DECIMAL(10, 2) NULL")
    ensure_index(cursor, "fines", "idx_fines_semester", "semester_id")

    ensure_column(cursor, "attendance", "semester_id", "INT NULL")
    ensure_index(cursor, "attendance", "idx_attendance_semester", "semester_id")

    if not table_exists(cursor, "paper_attendance"):
        cursor.execute(
            """
            CREATE TABLE paper_attendance (
                event_id INT NOT NULL,
                student_id INT NOT NULL,
                status VARCHAR(16) NOT NULL,
                recorded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP,
                PRIMARY KEY (event_id, student_id),
                INDEX idx_paper_attendance_student (student_id)
            ) ENGINE=InnoDB
            """
        )
    ensure_column(cursor, "paper_attendance", "semester_id", "INT NULL")
    ensure_index(
        cursor,
        "paper_attendance",
        "idx_paper_attendance_semester",
        "semester_id",
    )

    ensure_column(cursor, "transactions", "semester_id", "INT NULL")
    ensure_index(cursor, "transactions", "idx_transactions_semester", "semester_id")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS semester_enrollments (
            id INT AUTO_INCREMENT PRIMARY KEY,
            semester_id INT NOT NULL,
            student_id INT NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'enrolled',
            enrolled_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            dropped_at TIMESTAMP NULL,
            UNIQUE KEY uq_semester_enrollment (semester_id, student_id),
            INDEX idx_semester_enrollments_student (student_id),
            INDEX idx_semester_enrollments_status (semester_id, status)
        ) ENGINE=InnoDB
        """
    )

    cursor.execute(
        "UPDATE events SET semester_id=%s WHERE semester_id IS NULL",
        (active_term_id,),
    )
    cursor.execute(
        """
        UPDATE student_funds
        SET semester_id=%s,
            assessed_amount=COALESCE(assessed_amount, amount_due)
        WHERE semester_id IS NULL
        """,
        (active_term_id,),
    )
    cursor.execute(
        """
        UPDATE fines f
        LEFT JOIN events e ON e.event_id=f.event_id
        SET f.semester_id=COALESCE(e.semester_id, %s),
            f.assessed_amount=COALESCE(f.assessed_amount, f.amount)
        WHERE f.semester_id IS NULL
        """,
        (active_term_id,),
    )
    cursor.execute(
        """
        UPDATE attendance a
        JOIN events e ON e.event_id=a.event_id
        SET a.semester_id=e.semester_id
        WHERE a.semester_id IS NULL
        """
    )
    cursor.execute(
        """
        UPDATE paper_attendance p
        JOIN events e ON e.event_id=p.event_id
        SET p.semester_id=e.semester_id
        WHERE p.semester_id IS NULL
        """
    )
    cursor.execute(
        """
        UPDATE transactions t
        LEFT JOIN school_terms st
          ON st.academic_year=t.academic_year
         AND st.semester=t.semester
        SET t.semester_id=COALESCE(st.id, %s)
        WHERE t.semester_id IS NULL
        """,
        (active_term_id,),
    )
    cursor.execute(
        """
        INSERT IGNORE INTO semester_enrollments (semester_id, student_id, status)
        SELECT %s, id, 'enrolled'
        FROM students
        """,
        (active_term_id,),
    )


def main():
    parser = argparse.ArgumentParser(
        description="Safely migrate the configured MySQL database for semester enrollment."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report active semester and table counts without changing the database.",
    )
    args = parser.parse_args()

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        term_columns = get_columns(cursor, "school_terms")
        term_id_column = "id" if "id" in term_columns else "term_id"
        cursor.execute(
            f"""
            SELECT `{term_id_column}`, academic_year, semester
            FROM school_terms
            WHERE is_active=TRUE
            ORDER BY `{term_id_column}`
            """
        )
        active_terms = cursor.fetchall()
        if len(active_terms) != 1:
            raise RuntimeError(
                "Exactly one active semester is required; "
                f"found {len(active_terms)}."
            )
        active_term_id, academic_year, semester = active_terms[0]

        counts = {}
        for table_name in TABLES_TO_BACK_UP:
            if table_exists(cursor, table_name):
                cursor.execute(f"SELECT COUNT(*) FROM `{table_name}`")
                counts[table_name] = cursor.fetchone()[0]
        print(
            f"Active semester: {academic_year} {semester} (id={active_term_id})"
        )
        print(f"Current records: {counts}")
        if args.dry_run:
            return

        suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
        backups = make_backup(cursor, suffix)
        conn.commit()
        print("Verified backup tables:")
        for source, backup, count in backups:
            print(f"  {backup}: {count} rows copied from {source}")

        apply_migration(cursor, active_term_id)
        conn.commit()

        cursor.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM students) AS students,
                (SELECT COUNT(*) FROM semester_enrollments
                 WHERE semester_id=%s AND status='enrolled') AS enrolled,
                (SELECT COUNT(*) FROM events
                 WHERE semester_id=%s) AS events,
                (SELECT COUNT(*) FROM student_funds
                 WHERE semester_id=%s) AS funds,
                (SELECT COUNT(*) FROM fines
                 WHERE semester_id=%s) AS fines
            """,
            (active_term_id,) * 4,
        )
        print(f"Migration verified: {cursor.fetchone()}")
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    main()
