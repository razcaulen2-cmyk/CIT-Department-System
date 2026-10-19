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
