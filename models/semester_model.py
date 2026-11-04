import json
from decimal import Decimal


def get_active_semester(cursor):
    cursor.execute(
        """
        SELECT id, academic_year, semester, fund_amount
        FROM school_terms
        WHERE is_active=TRUE
        ORDER BY id DESC
        LIMIT 1
        """
    )
    return cursor.fetchone()


def is_student_enrolled(cursor, semester_id, student_id):
    if not semester_id:
        return False
    cursor.execute(
        """
        SELECT 1
        FROM semester_enrollments
        WHERE semester_id=%s AND student_id=%s AND status='enrolled'
        LIMIT 1
        """,
        (semester_id, student_id),
    )
    return cursor.fetchone() is not None


def get_enrolled_student_ids(semester_id):
    if not semester_id:
        return set()
    from config import get_db_connection

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT student_id
        FROM semester_enrollments
        WHERE semester_id=%s AND status='enrolled'
        """,
        (semester_id,),
    )
    student_ids = {row[0] for row in cursor.fetchall()}
    cursor.close()
    conn.close()
    return student_ids


def get_semester_student_ids(semester_id):
    if not semester_id:
        return set()
    from config import get_db_connection

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT student_id FROM semester_enrollments WHERE semester_id=%s",
        (semester_id,),
    )
    student_ids = {row[0] for row in cursor.fetchall()}
    cursor.close()
    conn.close()
    return student_ids


def is_student_enrolled_in_semester(semester_id, student_id, include_dropped=False):
    if not semester_id:
        return False
    from config import get_db_connection

    conn = get_db_connection()
    cursor = conn.cursor()
    query = """
        SELECT 1
        FROM semester_enrollments
        WHERE semester_id=%s AND student_id=%s
    """
    if not include_dropped:
        query += " AND status='enrolled'"
    query += " LIMIT 1"
    cursor.execute(query, (semester_id, student_id))
    enrolled = cursor.fetchone() is not None
    cursor.close()
    conn.close()
    return enrolled


def get_student_semester_ids(student_id):
    from config import get_db_connection

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT semester_id FROM semester_enrollments WHERE student_id=%s",
        (student_id,),
    )
    semester_ids = {row[0] for row in cursor.fetchall()}
    cursor.close()
    conn.close()
    return semester_ids


def enroll_student(cursor, semester_id, student_id, payment_key, charge_fund=True):
    cursor.execute(
        """
        INSERT IGNORE INTO semester_enrollments (semester_id, student_id, status)
        VALUES (%s, %s, 'enrolled')
        """,
        (semester_id, student_id),
    )
    if cursor.rowcount == 0:
        return False

    if charge_fund:
        cursor.execute(
            "SELECT fund_amount FROM school_terms WHERE id=%s",
            (semester_id,),
        )
        term = cursor.fetchone()
        fund_amount = Decimal(str(term[0] or 0)) if term else Decimal("0.00")
        cursor.execute(
            """
            INSERT INTO student_funds
                (student_id, semester_id, amount_due, assessed_amount, paid_amount, is_semester_fund)
            VALUES (%s, %s, %s, %s, 0, TRUE)
            """,
            (payment_key, semester_id, fund_amount, fund_amount),
        )
    return True


def apply_unallocated_fund_transactions(
    cursor,
    semester_id,
    payment_key,
    transaction_ids=None,
):
    if transaction_ids is not None and not transaction_ids:
        return Decimal("0.00")

    cursor.execute(
        """
        SELECT id, amount_due
        FROM student_funds
        WHERE student_id=%s AND semester_id=%s
            AND is_semester_fund=TRUE AND amount_due > 0
        ORDER BY id
        FOR UPDATE
        """,
        (payment_key, semester_id),
    )
    fund_rows = [
        {"id": row[0], "amount_due": Decimal(str(row[1] or 0))}
        for row in cursor.fetchall()
    ]
    if not fund_rows:
        return Decimal("0.00")

    query = """
        SELECT t.id, t.amount
        FROM transactions t
        JOIN transaction_balance_snapshots snapshot
            ON snapshot.transaction_id=t.id
        WHERE t.student_id=%s AND t.semester_id=%s
            AND t.transaction_type='Funds'
            AND snapshot.transaction_type='Funds'
            AND JSON_LENGTH(snapshot.snapshot)=0
    """
    params = [payment_key, semester_id]
    if transaction_ids is not None:
        query += " AND t.id IN (" + ", ".join(["%s"] * len(transaction_ids)) + ")"
        params.extend(transaction_ids)
    query += " ORDER BY t.transaction_date, t.id FOR UPDATE"
    cursor.execute(query, tuple(params))
    transactions = cursor.fetchall()

    total_applied = Decimal("0.00")
    for transaction_id, transaction_amount in transactions:
        remaining = Decimal(str(transaction_amount))
        balance_snapshot = []
        for fund_row in fund_rows:
            if remaining <= 0:
                break
            due = fund_row["amount_due"]
            if due <= 0:
                continue
            applied = min(due, remaining)
            after_amount = due - applied
            cursor.execute(
                """
                UPDATE student_funds
                SET amount_due=%s, paid_amount=paid_amount+%s
                WHERE id=%s AND student_id=%s
                """,
                (after_amount, applied, fund_row["id"], payment_key),
            )
            balance_snapshot.append({
                "row_id": fund_row["id"],
                "before": format(due, ".2f"),
                "after": format(after_amount, ".2f"),
            })
            fund_row["amount_due"] = after_amount
            remaining -= applied
            total_applied += applied

        if balance_snapshot:
            cursor.execute(
                """
                UPDATE transaction_balance_snapshots
                SET snapshot=%s
                WHERE transaction_id=%s
                    AND transaction_type='Funds'
                    AND JSON_LENGTH(snapshot)=0
                """,
                (json.dumps(balance_snapshot), transaction_id),
            )

    return total_applied


def reprice_semester_funds(cursor, semester_id, fund_amount):
    fund_amount = Decimal(str(fund_amount))
    cursor.execute(
        """
        SELECT id, student_id, paid_amount
        FROM student_funds
        WHERE semester_id=%s AND is_semester_fund=TRUE
        ORDER BY id
        FOR UPDATE
        """,
        (semester_id,),
    )
    for row in cursor.fetchall():
        paid = Decimal(str(row[2] or 0))
        new_due = max(fund_amount - paid, Decimal("0.00"))
        cursor.execute(
            """
            UPDATE student_funds
            SET amount_due=%s, assessed_amount=%s
            WHERE id=%s
            """,
            (new_due, fund_amount, row[0]),
        )
