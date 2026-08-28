from config import get_db_connection


def get_all_students():

    conn = get_db_connection()

    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT *
        FROM students
        ORDER BY lastname ASC
    """)

    students = cursor.fetchall()

    conn.close()

    return students

def get_student(student_id):

    conn = get_db_connection()

    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT *
        FROM students
        WHERE id=%s
        """,
        (student_id,)
    )

    student = cursor.fetchone()

    conn.close()

    return student

def get_student_by_rfid(rfid_uid):

    conn = get_db_connection()

    cursor = conn.cursor(dictionary=True)

    # Some schemas store RFID in `rfid_uid`, others may store a student identifier in `student_id`.
    try:
        cursor.execute(
            """
            SELECT *
            FROM students
            WHERE rfid_uid=%s
            """,
            (rfid_uid,)
        )
    except Exception:
        cursor.execute(
            """
            SELECT *
            FROM students
            WHERE student_id=%s
            """,
            (rfid_uid,)
        )

    student = cursor.fetchone()

    conn.close()

    return student

def delete_student(student_id):

    conn = get_db_connection()

    cursor = conn.cursor()

    cursor.execute(
        """
        DELETE
        FROM students
        WHERE id=%s
        """,
        (student_id,)
    )

    conn.commit()

    conn.close()

def add_student(
    first_name,
    last_name,
    course,
    year_level
):

    conn = get_db_connection()

    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO students
        (
            firstname,
            lastname,
            course,
            year_level
        )
        VALUES
        (%s,%s,%s,%s)
        """,
        (
            first_name,
            last_name,
            course,
            year_level
        )
    )

    conn.commit()

    conn.close()

def update_student(
    student_id,
    first_name,
    last_name,
    course,
    year_level
):

    conn = get_db_connection()

    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE students
        SET

        firstname=%s,
        lastname=%s,
        course=%s,
        year_level=%s

        WHERE id=%s
        """,
        (
            first_name,
            last_name,
            course,
            year_level,
            student_id
        )
    )

    conn.commit()

    conn.close()