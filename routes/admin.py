from functools import wraps
import base64
import binascii
import csv
import hmac
import io
import json
import re
import secrets
import unicodedata
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import quote_plus

import mysql.connector
from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, send_file, session
from werkzeug.security import check_password_hash

from config import get_db_connection
from models import attendance_model, event_model, semester_model
from services.database_backup import (
    MAX_RESTORE_BYTES,
    DatabaseBackupError,
    create_database_backup,
    get_database_backup_path,
    restore_database as restore_database_backup,
    stage_restore_upload,
)
from services.windows_printer import list_local_printers, print_raw_receipt

admin_bp = Blueprint("admin", __name__)


def ensure_transaction_balance_snapshots(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS transaction_balance_snapshots (
            transaction_id INT PRIMARY KEY,
            transaction_type VARCHAR(16) NOT NULL,
            snapshot JSON NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def require_admin(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if "admin" not in session:
            # preserve original path so user can be redirected back after login
            next_param = request.path
            if request.query_string:
                try:
                    qs = request.query_string.decode()
                except Exception:
                    qs = ''
                if qs:
                    next_param = f"{next_param}?{qs}"
            return redirect("/admin-login?next=" + quote_plus(next_param))
        return view_func(*args, **kwargs)

    return wrapped


@admin_bp.route("/admin-dashboard")
@require_admin
def admin_dashboard():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT COUNT(*) total FROM students")
    total_students = cursor.fetchone()["total"]

    cursor.execute("SELECT COALESCE(SUM(amount_due), 0) as total_funds FROM student_funds")
    total_funds = float(cursor.fetchone()["total_funds"] or 0)

    cursor.execute("SELECT COALESCE(SUM(amount), 0) as total_fines FROM fines")
    total_fines = float(cursor.fetchone()["total_fines"] or 0)

    cursor.execute("SELECT COUNT(*) total FROM transactions WHERE DATE(transaction_date) = CURDATE()")
    today_transactions = cursor.fetchone()["total"] or 0

    cursor.execute(
        """
        SELECT course, COUNT(*) as count
        FROM students
        GROUP BY course
        ORDER BY course
        """
    )
    course_rows = cursor.fetchall()
    course_labels = [row["course"] for row in course_rows]
    course_data = [row["count"] for row in course_rows]

    cursor.execute(
        """
        SELECT semester, COALESCE(SUM(amount), 0) as total
        FROM transactions
        GROUP BY semester
        ORDER BY CASE semester
            WHEN '1st' THEN 1
            WHEN '2nd' THEN 2
            WHEN 'Summer' THEN 3
            ELSE 4
        END
        """
    )
    semester_rows = cursor.fetchall()
    semester_labels = [row["semester"] for row in semester_rows]
    payments_data = [row["total"] for row in semester_rows]

    conn.close()

    return render_template(
        "admin/dashboard.html",
        total_students=total_students,
        total_funds=f"{total_funds:.2f}",
        total_fines=f"{total_fines:.2f}",
        today_transactions=today_transactions,
        recent_transactions=[],
        course_labels=course_labels,
        course_data=course_data,
        semester_labels=semester_labels,
        payments_data=payments_data,
    )


@admin_bp.route("/students")
@require_admin
def students():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM students ORDER BY id DESC")
    students = cursor.fetchall()
    cursor.execute(
        """
        SELECT id, academic_year, semester, fund_amount
        FROM school_terms
        WHERE is_active=TRUE
        ORDER BY id DESC
        LIMIT 1
        """
    )
    active_semester = cursor.fetchone()
    conn.close()

    return render_template(
        "admin/students.html",
        students=students,
        active_semester=active_semester,
    )


@admin_bp.route("/add-student", methods=["GET", "POST"])
@require_admin
def add_student():
    if request.method == "POST":
        firstname = request.form["firstname"].strip().upper()
        lastname = request.form["lastname"].strip().upper()
        course = request.form["course"].strip().upper()
        year_level = request.form["year_level"].strip()

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id
            FROM students
            WHERE firstname=%s AND lastname=%s AND course=%s AND year_level=%s
            LIMIT 1
            """,
            (firstname, lastname, course, year_level),
        )
        if cursor.fetchone():
            conn.close()
            flash("A student with the same name, course, and year level already exists.", "danger")
            return redirect(request.referrer or "/students")

        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO students
            (firstname, lastname, course, year_level, status)
            VALUES (%s, %s, %s, %s, 'Active')
            """,
            (firstname, lastname, course, year_level),
        )
        student_id = cursor.lastrowid
        enroll_active = request.form.get("enroll_active_semester") == "1"
        if enroll_active:
            cursor.execute(
                """
                SELECT id
                FROM school_terms
                WHERE is_active=TRUE
                ORDER BY id DESC
                LIMIT 1
                """
            )
            active_semester = cursor.fetchone()
            if active_semester:
                semester_model.enroll_student(
                    cursor,
                    active_semester[0],
                    student_id,
                    str(student_id),
                )
            else:
                flash("Student was created, but there is no active semester to enroll them in.", "warning")
        conn.commit()
        conn.close()

        flash(
            "Student created and enrolled in the active semester."
            if enroll_active and active_semester
            else "Student created successfully.",
            "success",
        )
        return redirect("/students")

    return redirect("/students")


@admin_bp.route("/delete-student/<id>", methods=["GET", "POST"])
@require_admin
def delete_student(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM students WHERE id=%s", (id,))
    student = cursor.fetchone()

    if request.method == "POST":
        cursor = conn.cursor()
        cursor.execute("DELETE FROM students WHERE id=%s", (id,))
        conn.commit()
        conn.close()
        return redirect("/students")

    conn.close()

    if student is None:
        return redirect("/admin-dashboard")

    return render_template("admin/delete_student.html", student=student)


@admin_bp.route("/edit-student/<id>", methods=["GET", "POST"])
@require_admin
def edit_student(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == "POST":
        firstname = request.form["firstname"].strip().upper()
        lastname = request.form["lastname"].strip().upper()
        course = request.form["course"].strip().upper()
        year_level = request.form["year_level"].strip()

        cursor.execute(
            """
            SELECT id
            FROM students
            WHERE firstname=%s AND lastname=%s AND course=%s AND year_level=%s AND id != %s
            LIMIT 1
            """,
            (firstname, lastname, course, year_level, id),
        )
        if cursor.fetchone():
            conn.close()
            flash("Another student with the same name, course, and year level already exists.", "danger")
            return redirect(request.referrer or "/students")

        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE students
            SET firstname=%s, lastname=%s, course=%s, year_level=%s
            WHERE id=%s
            """,
            (firstname, lastname, course, year_level, id),
        )
        conn.commit()
        conn.close()
        return redirect("/students")

    cursor.execute("SELECT * FROM students WHERE id=%s", (id,))
    student = cursor.fetchone()
    conn.close()

    return render_template("admin/edit_student.html", student=student)


@admin_bp.route("/map-rfid/<int:id>", methods=["GET", "POST"])
@require_admin
def map_rfid(id):
    event_model.ensure_fine_payment_allocations()
    conn = get_db_connection()
    if request.method == "POST":
        conn.start_transaction()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM students WHERE id=%s", (id,))
    student = cursor.fetchone()

    if request.method == "POST":
        if not student:
            conn.close()
            return "Student not found.", 404

        raw_rfid_value = request.form.get("student_id", "").strip()
        rfid_value = re.sub(r"\D", "", raw_rfid_value).strip() or raw_rfid_value.strip()
        if not rfid_value:
            conn.close()
            return "Enter a valid student ID.", 400
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, student_id FROM students WHERE id=%s FOR UPDATE",
            (id,),
        )
        locked_student = cursor.fetchone()
        if not locked_student:
            conn.rollback()
            conn.close()
            return "Student not found.", 404

        cursor.execute(
            "SELECT id FROM students WHERE student_id=%s AND id<>%s",
            (rfid_value, id),
        )
        existing = cursor.fetchone()
        if existing:
            conn.rollback()
            conn.close()
            return "Student ID is already assigned to another student.", 409

        current_key = str(locked_student[1] or id)
        source_keys = [current_key]
        legacy_key = str(id)
        if legacy_key not in source_keys:
            cursor.execute(
                """
                SELECT id
                FROM students
                WHERE student_id=%s AND id<>%s
                LIMIT 1
                """,
                (legacy_key, id),
            )
            if not cursor.fetchone():
                source_keys.append(legacy_key)

        for source_key in source_keys:
            if source_key == rfid_value:
                continue
            cursor.execute(
                """
                SELECT source.fine_id
                FROM fines AS source
                JOIN fines AS destination
                  ON destination.event_id = source.event_id
                 AND destination.fine_type = source.fine_type
                WHERE source.student_id=%s AND destination.student_id=%s
                LIMIT 1
                """,
                (source_key, rfid_value),
            )
            if cursor.fetchone():
                conn.rollback()
                conn.close()
                return (
                    "Cannot remap this ID because both IDs have fines for the same event. "
                    "Resolve the duplicate fine records first."
                ), 409

        for source_key in source_keys:
            if source_key == rfid_value:
                continue
            cursor.execute(
                "UPDATE student_funds SET student_id=%s WHERE student_id=%s",
                (rfid_value, source_key),
            )
            cursor.execute(
                "UPDATE fines SET student_id=%s WHERE student_id=%s",
                (rfid_value, source_key),
            )
            cursor.execute(
                "UPDATE fine_payment_allocations SET student_id=%s WHERE student_id=%s",
                (rfid_value, source_key),
            )
            cursor.execute(
                "UPDATE transactions SET student_id=%s WHERE student_id=%s",
                (rfid_value, source_key),
            )
        if current_key != rfid_value:
            cursor.execute(
                "UPDATE students SET student_id=%s WHERE id=%s",
                (rfid_value, id),
            )
        conn.commit()
        conn.close()
        return redirect("/students")

    conn.close()
    return render_template("rfid/map.html", student=student)


@admin_bp.route("/academic-terms")
@require_admin
def academic_terms():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """
        SELECT st.*,
               (SELECT COUNT(*)
                FROM semester_enrollments se
                WHERE se.semester_id=st.id AND se.status='enrolled') AS enrolled_count
        FROM school_terms st
        ORDER BY st.academic_year DESC,
                 CASE st.semester
                     WHEN '1st Semester' THEN 1
                     WHEN '2nd Semester' THEN 2
                     ELSE 3
                 END,
                 st.semester
        """
    )
    terms = cursor.fetchall()
    conn.close()

    return render_template("admin/academic_terms.html", terms=terms)


@admin_bp.route("/add-academic-term", methods=["GET", "POST"])
@require_admin
def add_academic_term():
    if request.method == "POST":
        academic_year = request.form.get("academic_year", "").strip()
        if not academic_year or len(academic_year) > 20:
            flash("Enter a valid academic year (up to 20 characters).", "danger")
            return redirect("/academic-terms")

        semester_definitions = (
            ("1st Semester", "first"),
            ("2nd Semester", "second"),
            ("Summer Class", "summer"),
        )
        semester_values = []
        try:
            for semester, prefix in semester_definitions:
                start_date = request.form.get(f"{prefix}_start_date") or None
                end_date = request.form.get(f"{prefix}_end_date") or None
                try:
                    if start_date:
                        date.fromisoformat(start_date)
                    if end_date:
                        date.fromisoformat(end_date)
                except ValueError:
                    raise ValueError(f"{semester}: enter valid start and end dates.") from None
                if start_date and end_date and start_date > end_date:
                    raise ValueError(f"{semester}: end date must not be before start date.")

                raw_fund_amount = request.form.get(f"{prefix}_fund_amount")
                if raw_fund_amount is None:
                    raise InvalidOperation
                fund_amount = Decimal(raw_fund_amount)
                if (
                    not fund_amount.is_finite()
                    or fund_amount < 0
                    or fund_amount > Decimal("99999999.99")
                ):
                    raise InvalidOperation
                fund_amount = fund_amount.quantize(Decimal("0.01"))
                semester_values.append(
                    (semester, start_date, end_date, fund_amount)
                )
        except ValueError as error:
            flash(
                str(error) if str(error) else "Enter a valid non-negative fund amount for each semester.",
                "danger",
            )
            return redirect("/academic-terms")
        except InvalidOperation:
            flash("Enter a valid non-negative fund amount for each semester.", "danger")
            return redirect("/academic-terms")

        set_active = request.form.get("is_active") == "on"
        active_semester = request.form.get("active_semester", "")
        semester_names = {semester for semester, _ in semester_definitions}
        if set_active and active_semester not in semester_names:
            flash("Choose which semester should be active.", "danger")
            return redirect("/academic-terms")

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM school_terms WHERE academic_year=%s LIMIT 1",
            (academic_year,),
        )
        if cursor.fetchone():
            cursor.close()
            conn.close()
            flash("That academic year already exists.", "danger")
            return redirect("/academic-terms")

        try:
            if set_active:
                cursor.execute("UPDATE school_terms SET is_active=FALSE")
            for semester, start_date, end_date, fund_amount in semester_values:
                cursor.execute(
                    """
                    INSERT INTO school_terms
                    (academic_year, semester, start_date, end_date, fund_amount, is_active)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        academic_year,
                        semester,
                        start_date,
                        end_date,
                        fund_amount,
                        set_active and semester == active_semester,
                    ),
                )
            conn.commit()
        except mysql.connector.Error:
            conn.rollback()
            raise
        finally:
            cursor.close()
            conn.close()

        return redirect("/academic-terms")

    return redirect("/academic-terms")


@admin_bp.route("/edit-academic-term/<id>", methods=["GET", "POST"])
@require_admin
def edit_academic_term(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == "POST":
        academic_year = request.form["academic_year"]
        semester = request.form["semester"]
        start_date = request.form.get("start_date", None)
        end_date = request.form.get("end_date", None)
        try:
            raw_fund_amount = request.form.get("fund_amount")
            if raw_fund_amount is None:
                raise InvalidOperation
            fund_amount = Decimal(raw_fund_amount)
            if not fund_amount.is_finite() or fund_amount < 0 or fund_amount > Decimal("99999999.99"):
                raise InvalidOperation
            fund_amount = fund_amount.quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            conn.close()
            flash("Enter a valid non-negative fund amount.", "danger")
            return redirect("/academic-terms")
        is_active = request.form.get("is_active", False)
        is_active = is_active == "on"

        cursor = conn.cursor()
        cursor.execute("SELECT id FROM school_terms WHERE id=%s", (id,))
        if not cursor.fetchone():
            conn.close()
            flash("Semester not found.", "danger")
            return redirect("/academic-terms")
        cursor.execute(
            """
            SELECT id FROM school_terms
            WHERE academic_year=%s AND semester=%s AND id<>%s
            LIMIT 1
            """,
            (academic_year, semester, id),
        )
        if cursor.fetchone():
            conn.close()
            flash("That academic year and semester already exist.", "danger")
            return redirect("/academic-terms")
        if is_active:
            cursor.execute("UPDATE school_terms SET is_active=FALSE")
        cursor.execute(
            """
            UPDATE school_terms
            SET academic_year=%s, semester=%s, start_date=%s, end_date=%s,
                fund_amount=%s, is_active=%s
            WHERE id=%s
            """,
            (academic_year, semester, start_date, end_date, fund_amount, is_active, id),
        )
        cursor.execute(
            """
            UPDATE transactions
            SET academic_year=%s, semester=%s
            WHERE semester_id=%s
            """,
            (academic_year, semester, id),
        )
        semester_model.reprice_semester_funds(cursor, id, fund_amount)
        conn.commit()
        conn.close()
        return redirect("/academic-terms")

    cursor.execute("SELECT * FROM school_terms WHERE id=%s", (id,))
    term = cursor.fetchone()
    conn.close()

    return redirect("/academic-terms")


@admin_bp.route("/delete-academic-term/<id>", methods=["GET", "POST"])
@require_admin
def delete_academic_term(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM school_terms WHERE id=%s", (id,))
    term = cursor.fetchone()

    if request.method == "POST":
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM semester_enrollments WHERE semester_id=%s) +
                (SELECT COUNT(*) FROM events WHERE semester_id=%s) +
                (SELECT COUNT(*) FROM student_funds WHERE semester_id=%s) +
                (SELECT COUNT(*) FROM fines WHERE semester_id=%s) +
                (SELECT COUNT(*) FROM attendance WHERE semester_id=%s) +
                (SELECT COUNT(*) FROM transactions WHERE semester_id=%s) AS linked_rows
            """,
            (id, id, id, id, id, id),
        )
        if cursor.fetchone()[0]:
            conn.close()
            flash("This semester has enrollment or historical records and cannot be deleted.", "danger")
            return redirect("/academic-terms")
        cursor.execute("DELETE FROM school_terms WHERE id=%s", (id,))
        conn.commit()
        conn.close()
        return redirect("/academic-terms")

    conn.close()

    if term is None:
        return redirect("/academic-terms")

    return render_template("admin/delete_academic_term.html", term=term)


@admin_bp.route("/academic-terms/<int:semester_id>/students")
@require_admin
def semester_students(semester_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM school_terms WHERE id=%s", (semester_id,))
    semester = cursor.fetchone()
    if not semester:
        conn.close()
        return redirect("/academic-terms")
    cursor.execute(
        """
        SELECT s.id, s.student_id, s.firstname, s.lastname, s.course, s.year_level,
               se.status, se.enrolled_at, se.dropped_at
        FROM students s
        LEFT JOIN semester_enrollments se
          ON se.student_id=s.id AND se.semester_id=%s
        ORDER BY s.lastname, s.firstname
        """,
        (semester_id,),
    )
    students = cursor.fetchall()
    conn.close()
    return render_template(
        "admin/semester_students.html",
        semester=semester,
        students=students,
    )


@admin_bp.route(
    "/academic-terms/<int:semester_id>/students/<int:student_id>/enroll",
    methods=["POST"],
)
@require_admin
def enroll_semester_student(semester_id, student_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT student_id FROM students WHERE id=%s",
        (student_id,),
    )
    student_key = cursor.fetchone()
    if not student_key:
        conn.close()
        flash("Student not found.", "danger")
        return redirect(f"/academic-terms/{semester_id}/students")
    cursor.execute(
        "SELECT status FROM semester_enrollments WHERE semester_id=%s AND student_id=%s",
        (semester_id, student_id),
    )
    existing_enrollment = cursor.fetchone()
    if existing_enrollment:
        conn.close()
        flash("This student already has an enrollment record for the semester.", "warning")
        return redirect(f"/academic-terms/{semester_id}/students")
    cursor.execute(
        "SELECT id FROM school_terms WHERE id=%s",
        (semester_id,),
    )
    if not cursor.fetchone():
        conn.close()
        flash("Semester not found.", "danger")
        return redirect("/academic-terms")
    semester_model.enroll_student(
        cursor,
        semester_id,
        student_id,
        student_key[0] or str(student_id),
    )
    conn.commit()
    conn.close()
    flash("Student enrolled. The semester fund has been added to their balance.", "success")
    return redirect(f"/academic-terms/{semester_id}/students")


@admin_bp.route(
    "/academic-terms/<int:semester_id>/students/<int:student_id>/drop",
    methods=["POST"],
)
@require_admin
def drop_semester_student(semester_id, student_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE semester_enrollments
        SET status='dropped', dropped_at=CURRENT_TIMESTAMP
        WHERE semester_id=%s AND student_id=%s AND status='enrolled'
        """,
        (semester_id, student_id),
    )
    if cursor.rowcount:
        conn.commit()
        flash("Student dropped. Existing funds and fines remain on the account.", "success")
    else:
        conn.rollback()
        flash("No active enrollment was found for this student.", "warning")
    conn.close()
    return redirect(f"/academic-terms/{semester_id}/students")


# Finance Routes - Department Funds + Fines
@admin_bp.route("/finance")
@require_admin
def finance():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Get filter parameters
    year_level = request.args.get('year_level', '')
    course = request.args.get('course', '')
    semester_id = request.args.get('semester_id', '')
    
    # Get list of year levels and courses for filters
    cursor.execute("""
        SELECT DISTINCT year_level FROM students
        WHERE year_level IS NOT NULL
        ORDER BY year_level
    """)
    year_levels = [row['year_level'] for row in cursor.fetchall()]
    
    courses = ['BLIS', 'BSIS', 'BSCS']
    cursor.execute(
        """
        SELECT id, academic_year, semester
        FROM school_terms
        ORDER BY academic_year DESC, semester
        """
    )
    terms = cursor.fetchall()
    if semester_id:
        if not semester_id.isdigit() or int(semester_id) not in {term["id"] for term in terms}:
            conn.close()
            return "Choose a valid semester.", 400
        semester_id = int(semester_id)

    # Run event fines sync asynchronously so the page doesn't block while recalculating
    try:
        import threading

        threading.Thread(target=event_model.sync_all_closed_event_fines, daemon=True).start()
    except Exception:
        # if threading fails for some reason, fall back to synchronous (safer)
        try:
            event_model.sync_all_closed_event_fines()
        except Exception:
            pass

    # Use subqueries to fetch per-student aggregates. This avoids large GROUP BY joins
    funds_semester_filter = " AND sf.semester_id=%s" if semester_id else ""
    fines_semester_filter = " AND f.semester_id=%s" if semester_id else ""
    query = """
        SELECT
            s.id AS id,
            s.student_id,
            s.firstname,
            s.lastname,
            s.course,
            s.year_level,
            (
                SELECT COALESCE(SUM(sf.amount_due), 0)
                FROM student_funds sf
                WHERE sf.student_id = COALESCE(s.student_id, CAST(s.id AS CHAR))
                {funds_semester_filter}
            ) AS total_funds,
            (
                SELECT COALESCE(SUM(f.amount), 0)
                FROM fines f
                WHERE f.student_id = COALESCE(s.student_id, CAST(s.id AS CHAR))
                {fines_semester_filter}
            ) AS total_fines
        FROM students s
        WHERE s.status = 'Active'
    """.format(
        funds_semester_filter=funds_semester_filter,
        fines_semester_filter=fines_semester_filter,
    )

    params = []
    if semester_id:
        params.extend([semester_id, semester_id])
    if course:
        query += " AND s.course = %s"
        params.append(course)

    if year_level:
        query += " AND s.year_level = %s"
        params.append(year_level)

    query += " ORDER BY s.lastname, s.firstname"

    cursor.execute(query, params)
    students_data = cursor.fetchall()

    cursor.close()
    conn.close()
    
    return render_template(
        "admin/finance.html",
        students=students_data,
        year_levels=year_levels,
        courses=courses,
        selected_year_level=year_level,
        selected_course=course,
        terms=terms,
        selected_semester_id=semester_id
    )


@admin_bp.route("/balance-report")
@require_admin
def balance_report():
    balance_type = request.args.get("balance_type", "").strip().lower()
    course = request.args.get("course", "").strip().upper()
    if course == "ALL":
        course = "all"
    valid_balance_types = {"funds", "fines", "overall"}
    valid_courses = {"all", "BLIS", "BSCS", "BSIS"}

    if balance_type not in valid_balance_types or course not in valid_courses:
        return "Choose a valid balance type and course.", 400

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        query = """
            SELECT
                COALESCE(s.student_id, CAST(s.id AS CHAR)) AS report_student_id,
                s.firstname,
                s.lastname,
                s.course,
                s.year_level,
                (
                    SELECT COALESCE(SUM(sf.amount_due), 0)
                    FROM student_funds sf
                    WHERE sf.student_id = COALESCE(s.student_id, CAST(s.id AS CHAR))
                ) AS total_funds,
                (
                    SELECT COALESCE(SUM(f.amount), 0)
                    FROM fines f
                    WHERE f.student_id = COALESCE(s.student_id, CAST(s.id AS CHAR))
                ) AS total_fines
            FROM students s
            WHERE s.status = 'Active'
            """
        params = ()
        if course != "all":
            query += " AND s.course = %s"
            params = (course,)
        cursor.execute(query, params)
        students = cursor.fetchall()
        balance_field = {
            "funds": "total_funds",
            "fines": "total_fines",
            "overall": None,
        }[balance_type]
        for student in students:
            student["total_funds"] = Decimal(str(student["total_funds"] or 0))
            student["total_fines"] = Decimal(str(student["total_fines"] or 0))
            student["overall_balance"] = student["total_funds"] + student["total_fines"]

        def name_sort_key(value):
            normalized = unicodedata.normalize(
                "NFKD", str(value or "").casefold().replace("�", "n")
            )
            return "".join(
                character for character in normalized
                if not unicodedata.combining(character)
            )

        students.sort(
            key=lambda student: (
                str(student["course"] or "").casefold(),
                name_sort_key(student["lastname"]),
                name_sort_key(student["firstname"]),
            )
        )
        if balance_field:
            students = [student for student in students if student[balance_field] > 0]
        else:
            students = [student for student in students if student["overall_balance"] > 0]

        report_total = sum(
            (
                student[balance_field] if balance_field
                else student["overall_balance"]
                for student in students
            ),
            Decimal("0.00"),
        )
        report_title = {
            "funds": "Funds Balance Report",
            "fines": "Fines Balance Report",
            "overall": "Overall Balance Report",
        }[balance_type]
        return render_template(
            "admin/balance_report.html",
            students=students,
            balance_type=balance_type,
            course=course,
            report_title=report_title,
            report_total=report_total,
            generated_at=date.today(),
        )
    finally:
        cursor.close()
        conn.close()


@admin_bp.route("/api/students/<student_key>/attendance", methods=["GET"])
@require_admin
def get_student_attendance_history(student_key):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """
        SELECT id, student_id, firstname, lastname, course, year_level
        FROM students
        WHERE id=%s OR student_id=%s
        LIMIT 1
        """,
        (student_key, student_key),
    )
    student = cursor.fetchone()
    cursor.close()
    conn.close()

    if not student:
        return jsonify({'success': False, 'message': 'Student not found'}), 404

    enrolled_semester_ids = semester_model.get_student_semester_ids(student['id'])
    events = [
        event for event in event_model.get_all_events()
        if event.get('semester_id') in enrolled_semester_ids
    ]
    attendance_records = attendance_model.get_attendance_for_student(student['id'])
    records_by_event = {}
    for record in attendance_records:
        records_by_event.setdefault(record['event_id'], []).append(record)

    exempted_event_ids = event_model.get_exempted_event_ids_for_student(student['id'])
    paper_attendance = event_model.get_paper_attendance_for_student(student['id'])
    history = []
    for event in events:
        records = records_by_event.get(event['id'], [])
        statuses = {record['status'] for record in records}
        has_login_window = bool(event.get('login_time') or event.get('login_cutoff_time'))
        has_logout_window = bool(event.get('logout_time') or event.get('logout_cutoff_time'))

        if event['id'] in exempted_event_ids:
            status = 'Exempted'
        elif event['id'] in paper_attendance:
            status = 'Present' if paper_attendance[event['id']] == 'present' else 'Late'
        elif has_login_window and not has_logout_window:
            status = 'Present' if 'login' in statuses else 'Absent'
        elif has_logout_window and not has_login_window:
            status = 'Present' if 'logout' in statuses else 'Absent'
        elif 'logout' in statuses and 'login' not in statuses:
            status = 'Late'
        elif 'login' in statuses and 'logout' in statuses:
            status = 'Present'
        else:
            status = 'Absent'

        history.append({
            'event_name': event['name'],
            'event_date': str(event['date']),
            'status': status,
        })

    return jsonify({
        'success': True,
        'student': student,
        'events': history,
    })


# API endpoint to get student balance via QR/ID tap
@admin_bp.route("/api/student-balance/<student_id>", methods=["GET"])
@require_admin
def get_student_balance(student_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    selected_semester_id = request.args.get("semester_id")
    if selected_semester_id:
        if not selected_semester_id.isdigit():
            cursor.close()
            conn.close()
            return {"error": "Choose a valid semester."}, 400
        cursor.execute(
            "SELECT id FROM school_terms WHERE id=%s",
            (selected_semester_id,),
        )
        if not cursor.fetchone():
            cursor.close()
            conn.close()
            return {"error": "Choose a valid semester."}, 400
    
    # Get student info
    cursor.execute(
        """
        SELECT id, student_id, firstname, lastname, course, year_level
        FROM students WHERE student_id = %s
        """,
        (student_id,),
    )
    student = cursor.fetchone()

    if not student:
        cursor.execute("""
            SELECT id, student_id, firstname, lastname, course, year_level
            FROM students
            WHERE id = %s AND student_id IS NULL
        """, (student_id,))
        student = cursor.fetchone()
    
    if not student:
        cursor.close()
        conn.close()
        return {"error": "Student not found"}, 404

    payment_key = student['student_id'] or str(student['id'])
    
    # Get total funds balance
    funds_query = """
        SELECT COALESCE(SUM(amount_due), 0) as total_funds
        FROM student_funds
        WHERE student_id = %s
    """
    funds_params = [payment_key]
    if selected_semester_id:
        funds_query += " AND semester_id=%s"
        funds_params.append(selected_semester_id)
    cursor.execute(funds_query, tuple(funds_params))
    funds = cursor.fetchone()
    total_funds = float(funds['total_funds']) if funds else 0
    
    # Get total fines balance
    fines_query = """
        SELECT COALESCE(SUM(amount), 0) as total_fines
        FROM fines
        WHERE student_id = %s
    """
    fines_params = [payment_key]
    if selected_semester_id:
        fines_query += " AND semester_id=%s"
        fines_params.append(selected_semester_id)
    cursor.execute(fines_query, tuple(fines_params))
    fines = cursor.fetchone()
    total_fines = float(fines['total_fines']) if fines else 0
    
    cursor.close()
    conn.close()
    
    return {
        "student_id": student['student_id'],
        "payment_key": payment_key,
        "firstname": student['firstname'],
        "lastname": student['lastname'],
        "course": student['course'],
        "year_level": student['year_level'],
        "semester_id": int(selected_semester_id) if selected_semester_id else None,
        "total_funds": total_funds,
        "total_fines": total_fines,
        "total_balance": total_funds + total_fines
    }


@admin_bp.route("/api/thermal-printers", methods=["GET"])
@require_admin
def get_thermal_printers():
    try:
        return jsonify({"printers": list_local_printers()})
    except OSError as error:
        return jsonify({"error": str(error)}), 503


@admin_bp.route("/api/thermal-printers/print", methods=["POST"])
@require_admin
def print_thermal_receipt():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "A printer name and receipt payload are required."}), 400

    printer_name = data.get("printer_name")
    payload_base64 = data.get("payload")
    if not isinstance(printer_name, str) or not printer_name.strip():
        return jsonify({"error": "Select a Windows printer queue."}), 400
    if not isinstance(payload_base64, str) or not payload_base64:
        return jsonify({"error": "The receipt payload is missing."}), 400
    if len(payload_base64) > 1_400_000:
        return jsonify({"error": "The receipt payload is too large."}), 413

    try:
        payload = base64.b64decode(payload_base64, validate=True)
    except (binascii.Error, ValueError):
        return jsonify({"error": "The receipt payload is not valid base64 data."}), 400
    if not payload:
        return jsonify({"error": "The receipt payload is empty."}), 400

    try:
        available_printers = list_local_printers()
        if printer_name not in available_printers:
            return jsonify({"error": "The selected printer queue is no longer available."}), 404
        job_id = print_raw_receipt(printer_name, payload)
    except OSError as error:
        return jsonify({"error": f"Windows could not send the receipt to the printer: {error}"}), 503

    return jsonify({"success": True, "job_id": job_id})


# Payments & Transactions Page
@admin_bp.route("/payments")
@require_admin
def payments():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    ensure_transaction_balance_snapshots(cursor)

    cursor.execute("""
        SELECT id, academic_year, semester
        FROM school_terms
        ORDER BY academic_year DESC,
                 CASE semester
                     WHEN '1st Semester' THEN 1
                     WHEN '2nd Semester' THEN 2
                     ELSE 3
                 END,
                 semester
    """)
    terms = cursor.fetchall()
    academic_years = sorted(
        {term["academic_year"] for term in terms},
        reverse=True,
    )
    selected_academic_year = request.args.get("academic_year", "").strip()
    if selected_academic_year not in academic_years:
        selected_academic_year = ""

    available_terms = [
        term for term in terms
        if term["academic_year"] == selected_academic_year
    ]
    selected_semester_id = request.args.get("semester_id", "").strip()
    if not any(str(term["id"]) == selected_semester_id for term in available_terms):
        selected_semester_id = ""
    transaction_search = request.args.get("search", "").strip()[:100]

    query = """
        SELECT 
            t.id,
            t.student_id,
            s.firstname,
            s.lastname,
            t.transaction_type,
            t.payment_type,
            t.amount,
            t.academic_year,
            t.semester,
            t.transaction_date,
            snapshot.transaction_id IS NOT NULL AS reversible
        FROM transactions t
        JOIN students s ON t.student_id = COALESCE(s.student_id, CAST(s.id AS CHAR))
        LEFT JOIN transaction_balance_snapshots snapshot ON snapshot.transaction_id = t.id
    """
    filters = []
    params = []
    if transaction_search:
        search_pattern = f"%{transaction_search}%"
        filters.append("""
            (
                s.firstname LIKE %s
                OR s.lastname LIKE %s
                OR CONCAT(s.firstname, ' ', s.lastname) LIKE %s
                OR CAST(t.student_id AS CHAR) LIKE %s
                OR CAST(t.id AS CHAR) LIKE %s
                OR t.transaction_type LIKE %s
                OR t.payment_type LIKE %s
                OR CAST(t.amount AS CHAR) LIKE %s
                OR t.academic_year LIKE %s
                OR t.semester LIKE %s
                OR CAST(t.transaction_date AS CHAR) LIKE %s
            )
        """)
        params.extend([search_pattern] * 11)
    if selected_academic_year:
        filters.append("t.academic_year=%s")
        params.append(selected_academic_year)
    if selected_semester_id:
        selected_term = next(
            term for term in available_terms
            if str(term["id"]) == selected_semester_id
        )
        filters.append(
            """
            (t.semester_id=%s OR (
                t.semester_id IS NULL
                AND t.academic_year=%s
                AND t.semester=%s
            ))
            """
        )
        params.extend([
            int(selected_semester_id),
            selected_term["academic_year"],
            selected_term["semester"],
        ])
    if filters:
        query += " WHERE " + " AND ".join(filters)
    query += """
        ORDER BY t.transaction_date DESC
        LIMIT 50
    """
    cursor.execute(query, tuple(params))
    recent_transactions = cursor.fetchall()

    cursor.close()
    conn.close()
    
    return render_template(
        "admin/payments.html",
        transactions=recent_transactions,
        terms=terms,
        academic_years=academic_years,
        selected_academic_year=selected_academic_year,
        available_terms=available_terms,
        selected_semester_id=selected_semester_id,
        transaction_search=transaction_search,
    )


@admin_bp.route("/transaction-report")
@require_admin
def transaction_report():
    period = request.args.get("period", "").strip().lower()
    if period not in {"day", "week", "month", "overall"}:
        return "Choose a valid transaction report period.", 400

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT CURDATE() AS report_date, NOW() AS generated_at")
        report_clock = cursor.fetchone()
        report_date = report_clock["report_date"]

        if period == "day":
            start_date = report_date
            end_date = start_date + timedelta(days=1)
            period_label = f"Day - {start_date.strftime('%B %d, %Y')}"
        elif period == "week":
            start_date = report_date - timedelta(days=report_date.weekday())
            end_date = start_date + timedelta(days=7)
            period_label = (
                f"Week - {start_date.strftime('%b %d, %Y')} "
                f"to {(end_date - timedelta(days=1)).strftime('%b %d, %Y')}"
            )
        elif period == "month":
            start_date = report_date.replace(day=1)
            if start_date.month == 12:
                end_date = date(start_date.year + 1, 1, 1)
            else:
                end_date = date(start_date.year, start_date.month + 1, 1)
            period_label = start_date.strftime("%B %Y")
        else:
            start_date = None
            end_date = None
            period_label = "All recorded transactions"

        query = """
            SELECT
                t.id,
                t.student_id,
                COALESCE(
                    NULLIF(TRIM(CONCAT_WS(' ', s.firstname, s.lastname)), ''),
                    t.student_id
                ) AS student_name,
                t.transaction_type,
                t.payment_type,
                t.amount,
                t.academic_year,
                t.semester,
                t.transaction_date
            FROM transactions t
            LEFT JOIN students s
                ON t.student_id = COALESCE(s.student_id, CAST(s.id AS CHAR))
        """
        params = ()
        if start_date is not None:
            query += " WHERE t.transaction_date >= %s AND t.transaction_date < %s"
            params = (start_date, end_date)
        query += " ORDER BY t.transaction_date, t.id"
        cursor.execute(query, params)
        transactions = cursor.fetchall()

        semester_labels = set()
        for transaction in transactions:
            academic_year = (transaction["academic_year"] or "").strip()
            semester = (transaction["semester"] or "").strip()
            if academic_year and semester:
                semester_labels.add(f"{academic_year} · {semester}")
            else:
                semester_labels.add("Semester not recorded")

        if len(semester_labels) == 1:
            semester_label = next(iter(semester_labels))
        elif semester_labels:
            semester_label = "Multiple Semesters"
        else:
            semester_label = "No transactions"

        totals = {"Funds": Decimal("0.00"), "Fines": Decimal("0.00")}
        for transaction in transactions:
            transaction_type = transaction["transaction_type"]
            if transaction_type in totals:
                totals[transaction_type] += Decimal(str(transaction["amount"] or 0))

        return render_template(
            "admin/transaction_report.html",
            transactions=transactions,
            period_label=period_label,
            semester_label=semester_label,
            generated_at=report_clock["generated_at"],
            transaction_count=len(transactions),
            total_amount=sum(totals.values(), Decimal("0.00")),
            funds_total=totals["Funds"],
            fines_total=totals["Fines"],
        )
    finally:
        cursor.close()
        conn.close()


@admin_bp.route('/upload-csv', methods=['GET', 'POST'])
@require_admin
def upload_csv():
    message = None
    message_type = 'info'
    imported_count = 0
    row_errors = []
    omitted_error_count = 0

    if request.method == "GET":
        session["database_restore_csrf"] = secrets.token_urlsafe(32)

    if request.method == 'POST':
        file = request.files.get('csv_file')
        import_type = request.form.get('import_type', '').strip()
        if not file or file.filename == '':
            message = 'Please select a CSV file to upload.'
            message_type = 'danger'
        elif not file.filename.lower().endswith('.csv'):
            message = 'Only CSV files are allowed.'
            message_type = 'danger'
        elif import_type not in ('Funds', 'Fines'):
            message = 'Choose whether this file contains Funds or Fines.'
            message_type = 'danger'
        else:
            conn = None
            cursor = None
            try:
                csv_text = file.stream.read().decode('utf-8-sig')
                reader = csv.DictReader(io.StringIO(csv_text))
                if not reader.fieldnames:
                    raise ValueError('The CSV file is empty or has no header row.')

                header_map = {}
                for header in reader.fieldnames:
                    normalized_header = ' '.join(
                        (header or '').strip().casefold().replace('_', ' ').split()
                    )
                    if normalized_header in ('student name', 'name'):
                        header_map['student_name'] = header
                    elif normalized_header in ('year', 'year level'):
                        header_map['year'] = header
                    elif normalized_header == 'course':
                        header_map['course'] = header
                    elif normalized_header in ('amount', 'amount due'):
                        header_map['amount'] = header

                required_headers = {
                    'STUDENT NAME': 'student_name',
                    'YEAR': 'year',
                    'COURSE': 'course',
                    'AMOUNT': 'amount',
                }
                missing = [
                    label for label, key in required_headers.items()
                    if key not in header_map
                ]
                if missing:
                    raise ValueError(
                        'Missing required CSV columns: ' + ', '.join(missing) +
                        '. Required format: STUDENT NAME, YEAR, COURSE, AMOUNT.'
                    )

                parsed_rows = []
                for row_number, row in enumerate(reader, start=2):
                    if not row or not any((value or '').strip() for value in row.values()):
                        continue

                    student_name = ' '.join(
                        (row.get(header_map['student_name']) or '').split()
                    )
                    course = ' '.join(
                        (row.get(header_map['course']) or '').split()
                    ).upper()
                    year_text = ' '.join(
                        (row.get(header_map['year']) or '').split()
                    )
                    amount_text = (row.get(header_map['amount']) or '').strip().replace(',', '')

                    year_match = re.search(r'\d+', year_text)
                    if not student_name:
                        row_errors.append(f'Row {row_number}: student name is blank.')
                        continue
                    if not year_match:
                        row_errors.append(
                            f'Row {row_number}: year must include a year-level number.'
                        )
                        continue
                    if not course:
                        row_errors.append(f'Row {row_number}: course is blank.')
                        continue
                    try:
                        amount_due = Decimal(amount_text)
                        if (
                            not amount_due.is_finite()
                            or amount_due <= 0
                            or amount_due > Decimal('99999999.99')
                        ):
                            raise InvalidOperation
                        amount_due = amount_due.quantize(Decimal('0.01'))
                    except (InvalidOperation, ValueError):
                        row_errors.append(
                            f'Row {row_number}: amount must be positive with up to two decimal places.'
                        )
                        continue

                    parsed_rows.append({
                        'row_number': row_number,
                        'student_name': student_name,
                        'normalized_name': re.sub(
                            r'[^\w]', '', student_name.casefold()
                        ),
                        'year_level': year_match.group(),
                        'course': course,
                        'amount_due': amount_due,
                    })

                conn = get_db_connection()
                cursor = conn.cursor(dictionary=True)
                conn.start_transaction()
                cursor.execute(
                    """
                    SELECT id
                    FROM school_terms
                    WHERE is_active=TRUE
                    ORDER BY id DESC
                    LIMIT 1
                    FOR UPDATE
                    """
                )
                active_term = cursor.fetchone()
                if not active_term:
                    raise ValueError("Activate a semester before importing balances.")
                cursor.execute(
                    """
                    SELECT s.id, s.student_id, s.firstname, s.lastname, s.course, s.year_level
                    FROM students s
                    JOIN semester_enrollments se
                      ON se.student_id=s.id
                     AND se.semester_id=%s
                     AND se.status='enrolled'
                    FOR UPDATE
                    """,
                    (active_term['id'],),
                )
                students_by_key = {}
                for student in cursor.fetchall():
                    full_name = ' '.join(
                        f"{student.get('firstname') or ''} {student.get('lastname') or ''}".split()
                    )
                    lookup_key = (
                        re.sub(r'[^\w]', '', full_name.casefold()),
                        str(student.get('year_level') or '').strip(),
                        (student.get('course') or '').strip().upper(),
                    )
                    students_by_key.setdefault(lookup_key, []).append(student)

                matched_rows = []
                for row in parsed_rows:
                    lookup_key = (
                        row['normalized_name'],
                        row['year_level'],
                        row['course'],
                    )
                    matches = students_by_key.get(lookup_key, [])
                    if not matches:
                        row_errors.append(
                            f"Row {row['row_number']}: no student matches "
                            f"{row['student_name']} (Year {row['year_level']}, {row['course']})."
                        )
                    elif len(matches) > 1:
                        row_errors.append(
                            f"Row {row['row_number']}: student match is ambiguous for "
                            f"{row['student_name']} (Year {row['year_level']}, {row['course']})."
                        )
                    else:
                        student = matches[0]
                        matched_rows.append((
                            student.get('student_id') or str(student['id']),
                            row['amount_due'],
                        ))

                for student_key, amount_due in matched_rows:
                    if import_type == 'Funds':
                        cursor.execute(
                            """
                            INSERT INTO student_funds (student_id, semester_id, fund_id, amount_due)
                            VALUES (%s, %s, NULL, %s)
                            """,
                            (student_key, active_term['id'], amount_due),
                        )
                    else:
                        cursor.execute(
                            """
                            INSERT INTO fines (student_id, semester_id, event_id, fine_type, amount)
                            VALUES (%s, %s, NULL, NULL, %s)
                            """,
                            (student_key, active_term['id'], amount_due),
                        )
                conn.commit()
                imported_count = len(matched_rows)
            except (UnicodeDecodeError, csv.Error, ValueError) as error:
                if conn:
                    conn.rollback()
                message = str(error) or 'Unable to read the CSV file.'
                message_type = 'danger'
            except Exception as error:
                if conn:
                    conn.rollback()
                message = f'Import failed; no changes were saved. {error}'
                message_type = 'danger'
            else:
                omitted_error_count = max(0, len(row_errors) - 15)
                row_errors = row_errors[:15]
                if imported_count:
                    message = f'Imported {imported_count} {import_type.lower()} row(s).'
                    message_type = 'success' if not row_errors else 'warning'
                elif row_errors:
                    message = 'No rows were imported. Review the row errors below.'
                    message_type = 'danger'
                else:
                    message = 'The CSV contains no data rows.'
                    message_type = 'warning'
            finally:
                if cursor:
                    cursor.close()
                if conn:
                    conn.close()

    backup_filename = session.get("latest_database_backup")
    if backup_filename:
        try:
            get_database_backup_path(backup_filename)
        except DatabaseBackupError:
            session.pop("latest_database_backup", None)
            backup_filename = None

    return render_template(
        'admin/upload_csv.html',
        message=message,
        message_type=message_type,
        imported_count=imported_count,
        row_errors=row_errors,
        omitted_error_count=omitted_error_count,
        database_restore_csrf=session.get("database_restore_csrf"),
        backup_filename=backup_filename,
    )


@admin_bp.route("/database/backup", methods=["GET"])
@require_admin
def download_database_backup():
    try:
        backup_path = create_database_backup()
    except (DatabaseBackupError, OSError, mysql.connector.Error) as error:
        current_app.logger.error("Database backup failed: %s", error)
        flash(f"Database backup failed: {error}", "danger")
        return redirect("/upload-csv")

    session["latest_database_backup"] = backup_path.name
    return send_file(
        backup_path,
        as_attachment=True,
        download_name=backup_path.name,
        mimetype="application/sql",
    )


@admin_bp.route("/database/backups/<filename>", methods=["GET"])
@require_admin
def download_saved_database_backup(filename):
    try:
        backup_path = get_database_backup_path(filename)
    except (DatabaseBackupError, OSError) as error:
        return str(error), 404
    return send_file(
        backup_path,
        as_attachment=True,
        download_name=backup_path.name,
        mimetype="application/sql",
    )


@admin_bp.route("/database/restore", methods=["POST"])
@require_admin
def restore_database():
    request.max_content_length = MAX_RESTORE_BYTES + 1024 * 1024
    if request.content_length and request.content_length > MAX_RESTORE_BYTES + 1024 * 1024:
        flash("The selected backup exceeds the 1 GB restore limit.", "danger")
        return redirect("/upload-csv")

    submitted_token = request.form.get("csrf_token", "")
    expected_token = session.get("database_restore_csrf", "")
    if not expected_token or not hmac.compare_digest(submitted_token, expected_token):
        flash("Restore request expired. Reload this page and try again.", "danger")
        return redirect("/upload-csv")
    if request.form.get("confirmation", "").strip().upper() != "RESTORE":
        flash("Type RESTORE exactly to confirm replacing the current database.", "danger")
        return redirect("/upload-csv")

    uploaded_file = request.files.get("backup_file")
    if not uploaded_file or not uploaded_file.filename:
        flash("Choose a MySQL backup file to restore.", "danger")
        return redirect("/upload-csv")
    if not uploaded_file.filename.lower().endswith(".sql"):
        flash("Only .sql MySQL backup files can be restored.", "danger")
        return redirect("/upload-csv")

    staged_path = None
    try:
        staged_path = stage_restore_upload(uploaded_file.stream)
        safety_backup = restore_database_backup(staged_path)
        session["latest_database_backup"] = safety_backup.name
        flash(
            "Database restored successfully. An automatic pre-restore safety backup is available below.",
            "success",
        )
    except (DatabaseBackupError, OSError, mysql.connector.Error) as error:
        current_app.logger.error("Database restore failed: %s", error)
        if isinstance(error, DatabaseBackupError) and error.safety_backup:
            session["latest_database_backup"] = error.safety_backup.name
        flash(str(error), "danger")
    finally:
        if staged_path and staged_path.exists():
            try:
                staged_path.unlink()
            except OSError as error:
                current_app.logger.error("Could not remove staged database restore file: %s", error)
                flash(
                    "The restore upload could not be removed from the server's temporary backup folder.",
                    "warning",
                )

    session["database_restore_csrf"] = secrets.token_urlsafe(32)
    return redirect("/upload-csv")


# API endpoint to process payment transaction
@admin_bp.route("/api/process-payment", methods=["POST"])
@require_admin
def process_payment():
    from datetime import datetime
    
    data = request.get_json()
    student_id = data.get('student_id')
    transaction_type = data.get('transaction_type')  # Funds or Fines
    payment_type = data.get('payment_type')  # Partial or Full
    amount = data.get('amount')
    academic_year = data.get('academic_year')
    semester = data.get('semester')
    semester_id = data.get('semester_id')
    
    # Validate input
    if not all([student_id, transaction_type, payment_type, amount]) or (
        not semester_id and not all([academic_year, semester])
    ):
        return {"error": "Missing required fields"}, 400
    if transaction_type not in {"Funds", "Fines"}:
        return {"error": "Choose Funds or Fines for the transaction type"}, 400
    if payment_type not in {"Partial", "Full"}:
        return {"error": "Choose Partial or Full for the payment type"}, 400
    
    try:
        amount = Decimal(str(amount))
        if not amount.is_finite() or amount <= 0:
            return {"error": "Amount must be greater than 0"}, 400
        amount = amount.quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return {"error": "Invalid amount"}, 400

    if transaction_type == "Fines":
        event_model.ensure_fine_assessment_column()
        event_model.ensure_fine_payment_allocations()
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    ensure_transaction_balance_snapshots(cursor)
    
    # Verify student exists
    cursor.execute(
        "SELECT id, student_id, firstname, lastname FROM students WHERE student_id = %s",
        (student_id,),
    )
    student = cursor.fetchone()

    if not student:
        cursor.execute(
            """
            SELECT id, student_id, firstname, lastname
            FROM students
            WHERE id = %s AND student_id IS NULL
            """,
            (student_id,),
        )
        student = cursor.fetchone()
    
    if not student:
        cursor.close()
        conn.close()
        return {"error": "Student not found"}, 404

    payment_key = student['student_id'] or str(student['id'])
    
    try:
        # Log the transaction
        if semester_id:
            cursor.execute(
                """
                SELECT id, academic_year, semester
                FROM school_terms
                WHERE id=%s
                LIMIT 1
                """,
                (semester_id,),
            )
        else:
            cursor.execute(
                """
                SELECT id, academic_year, semester
                FROM school_terms
                WHERE academic_year=%s AND semester=%s
                LIMIT 1
                """,
                (academic_year, semester),
            )
        term_row = cursor.fetchone()
        if not term_row:
            return {"error": "Select a valid semester for this payment."}, 400
        semester_id = term_row["id"]
        academic_year = term_row["academic_year"]
        semester = term_row["semester"]

        cursor.execute("""
            INSERT INTO transactions 
            (student_id, semester_id, transaction_type, payment_type, amount, academic_year, semester, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            payment_key,
            semester_id,
            transaction_type,
            payment_type,
            amount,
            academic_year,
            semester,
            session.get('admin', 'unknown')
        ))
        transaction_no = cursor.lastrowid
        cursor.execute(
            "SELECT transaction_date FROM transactions WHERE id = %s",
            (transaction_no,),
        )
        transaction_date = cursor.fetchone()["transaction_date"]
        balance_snapshot = []
        
        # Apply payment amount to balances (support Partial and Full)
        remaining = Decimal(str(amount))
        if transaction_type == 'Funds':
            cursor.execute(
                """
                SELECT id, amount_due, paid_amount
                FROM student_funds
                WHERE student_id = %s AND semester_id=%s AND amount_due > 0
                ORDER BY amount_due ASC, id ASC
                FOR UPDATE
                """,
                (payment_key, semester_id),
            )
            fund_rows = cursor.fetchall()
            for row in fund_rows:
                if remaining <= 0:
                    break
                due = Decimal(str(row['amount_due']))
                deduct = min(due, remaining)
                after_amount = due - deduct
                cursor.execute(
                    """
                    UPDATE student_funds
                    SET amount_due = %s, paid_amount = paid_amount + %s
                    WHERE id = %s AND student_id = %s
                    """,
                    (after_amount, deduct, row['id'], payment_key),
                )
                balance_snapshot.append({
                    'row_id': row['id'],
                    'before': format(due, '.2f'),
                    'after': format(after_amount, '.2f'),
                })
                remaining -= deduct
        else:  # Fines
            cursor.execute(
                """
                SELECT fine_id, event_id, fine_type, amount
                FROM fines
                WHERE student_id = %s AND semester_id=%s AND amount > 0
                ORDER BY event_id, fine_id
                FOR UPDATE
                """,
                (payment_key, semester_id),
            )
            fine_rows = cursor.fetchall()
            for row in fine_rows:
                if remaining <= 0:
                    break
                fine_amount = Decimal(str(row['amount'] or 0))
                deduct = min(fine_amount, remaining)
                after_amount = fine_amount - deduct
                cursor.execute(
                    "UPDATE fines SET amount = %s WHERE fine_id = %s AND student_id = %s",
                    (after_amount, row['fine_id'], payment_key),
                )
                cursor.execute(
                    """
                    INSERT INTO fine_payment_allocations
                        (transaction_id, source_fine_id, student_id, event_id, fine_type, amount_paid)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        transaction_no,
                        row['fine_id'],
                        payment_key,
                        row['event_id'],
                        row['fine_type'],
                        deduct,
                    ),
                )
                balance_snapshot.append({
                    'row_id': row['fine_id'],
                    'event_id': row['event_id'],
                    'fine_type': row['fine_type'],
                    'before': format(fine_amount, '.2f'),
                    'after': format(after_amount, '.2f'),
                })
                remaining -= deduct

        cursor.execute(
            """
            INSERT INTO transaction_balance_snapshots
                (transaction_id, transaction_type, snapshot)
            VALUES (%s, %s, %s)
            """,
            (transaction_no, transaction_type, json.dumps(balance_snapshot)),
        )
        
        conn.commit()
        
        return {
            "success": True,
            "message": f"Payment recorded: {student['firstname']} {student['lastname']} - PHP {amount}",
            "student_name": f"{student['firstname']} {student['lastname']}",
            "transaction_date": transaction_date.strftime("%b %d, %Y %I:%M %p"),
            "transaction_no": transaction_no,
        }
    
    except Exception as e:
        conn.rollback()
        return {"error": str(e)}, 500
    
    finally:
        cursor.close()
        conn.close()


@admin_bp.route("/api/transactions/<int:transaction_id>", methods=["DELETE"])
@require_admin
def delete_transaction(transaction_id):
    data = request.get_json(silent=True) or {}
    password = data.get('password', '')
    if not password:
        return jsonify({'error': 'Enter your admin password to continue.'}), 400

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute(
            "SELECT password FROM admins WHERE admin_id = %s",
            (session.get('admin'),),
        )
        admin = cursor.fetchone()
        if not admin or not check_password_hash(admin.get('password') or '', password):
            return jsonify({'error': 'Incorrect admin password.'}), 401

        event_model.ensure_fine_payment_allocations()
        ensure_transaction_balance_snapshots(cursor)
        conn.start_transaction()
        cursor.execute(
            """
            SELECT id, student_id, transaction_type
            FROM transactions
            WHERE id = %s
            FOR UPDATE
            """,
            (transaction_id,),
        )
        transaction = cursor.fetchone()
        if not transaction:
            conn.rollback()
            return jsonify({'error': 'Transaction not found.'}), 404

        cursor.execute(
            """
            SELECT transaction_type, snapshot
            FROM transaction_balance_snapshots
            WHERE transaction_id = %s
            FOR UPDATE
            """,
            (transaction_id,),
        )
        saved_snapshot = cursor.fetchone()
        if not saved_snapshot:
            conn.rollback()
            return jsonify({
                'error': 'This older transaction has no saved balance snapshot and cannot be safely reversed.'
            }), 409
        if saved_snapshot['transaction_type'] != transaction['transaction_type']:
            conn.rollback()
            return jsonify({'error': 'The saved balance snapshot does not match this transaction.'}), 409

        cursor.execute(
            """
            SELECT id
            FROM transactions
            WHERE student_id = %s AND transaction_type = %s AND id > %s
            ORDER BY id
            LIMIT 1
            FOR UPDATE
            """,
            (transaction['student_id'], transaction['transaction_type'], transaction_id),
        )
        if cursor.fetchone():
            conn.rollback()
            return jsonify({
                'error': 'Delete this student’s newer transactions of the same type first so balances can be restored in order.'
            }), 409

        snapshot_rows = saved_snapshot['snapshot']
        if isinstance(snapshot_rows, str):
            snapshot_rows = json.loads(snapshot_rows)

        if transaction['transaction_type'] == 'Funds':
            table, key_column, amount_column = 'student_funds', 'id', 'amount_due'
        else:
            table, key_column, amount_column = 'fines', 'fine_id', 'amount'

        balances_to_restore = []
        for item in snapshot_rows:
            cursor.execute(
                f"""
                SELECT {amount_column} AS current_amount
                FROM {table}
                WHERE {key_column} = %s AND student_id = %s
                FOR UPDATE
                """,
                (item['row_id'], transaction['student_id']),
            )
            balance_row = cursor.fetchone()
            if not balance_row:
                conn.rollback()
                return jsonify({
                    'error': 'A balance row affected by this transaction no longer exists; no changes were made.'
                }), 409
            current_amount = Decimal(str(balance_row['current_amount']))
            before_amount = Decimal(item['before'])
            after_amount = Decimal(item['after'])
            if current_amount == before_amount:
                continue
            if current_amount != after_amount:
                conn.rollback()
                return jsonify({
                    'error': 'A balance affected by this transaction has changed since payment; no changes were made.'
                }), 409
            balances_to_restore.append(item)

        for item in balances_to_restore:
            if transaction['transaction_type'] == 'Funds':
                paid_for_transaction = Decimal(item['before']) - Decimal(item['after'])
                cursor.execute(
                    """
                    UPDATE student_funds
                    SET amount_due=%s,
                        paid_amount=GREATEST(paid_amount-%s, 0)
                    WHERE id=%s AND student_id=%s
                    """,
                    (
                        item['before'],
                        paid_for_transaction,
                        item['row_id'],
                        transaction['student_id'],
                    ),
                )
            else:
                cursor.execute(
                    f"""
                    UPDATE {table}
                    SET {amount_column} = %s
                    WHERE {key_column} = %s AND student_id = %s
                    """,
                    (item['before'], item['row_id'], transaction['student_id']),
                )

        cursor.execute(
            "DELETE FROM transaction_balance_snapshots WHERE transaction_id = %s",
            (transaction_id,),
        )
        cursor.execute(
            "DELETE FROM fine_payment_allocations WHERE transaction_id = %s",
            (transaction_id,),
        )
        cursor.execute("DELETE FROM transactions WHERE id = %s", (transaction_id,))
        if cursor.rowcount != 1:
            raise RuntimeError('Expected to delete exactly one transaction.')

        conn.commit()
        return jsonify({
            'success': True,
            'message': 'Transaction deleted and its balance changes were reversed.'
        })
    except (InvalidOperation, ValueError, TypeError, json.JSONDecodeError):
        conn.rollback()
        return jsonify({'error': 'The saved balance snapshot is invalid; no changes were made.'}), 500
    except Exception as error:
        conn.rollback()
        return jsonify({'error': f'Unable to reverse transaction: {error}'}), 500
    finally:
        cursor.close()
        conn.close()
