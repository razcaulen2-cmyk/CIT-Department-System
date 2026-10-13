from functools import wraps
import base64
import binascii
import csv
import io
import json
import re
import unicodedata
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import quote_plus

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session
from werkzeug.security import check_password_hash

from config import get_db_connection
from models import attendance_model, event_model
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
    conn.close()

    return render_template("admin/students.html", students=students)


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
        conn.commit()
        conn.close()

        return redirect("/students")

    return render_template("admin/add_student.html")


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
    cursor.execute("SELECT * FROM school_terms ORDER BY academic_year DESC, semester DESC")
    terms = cursor.fetchall()
    conn.close()

    return render_template("admin/academic_terms.html", terms=terms)


@admin_bp.route("/add-academic-term", methods=["GET", "POST"])
@require_admin
def add_academic_term():
    if request.method == "POST":
        academic_year = request.form["academic_year"]
        semester = request.form["semester"]
        start_date = request.form.get("start_date", None)
        end_date = request.form.get("end_date", None)
        is_active = request.form.get("is_active", False)
        is_active = is_active == "on"

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO school_terms
            (academic_year, semester, start_date, end_date, is_active)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (academic_year, semester, start_date, end_date, is_active),
        )
        conn.commit()
        conn.close()

        return redirect("/academic-terms")

    return render_template("admin/add_academic_term.html")


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
        is_active = request.form.get("is_active", False)
        is_active = is_active == "on"

        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE school_terms
            SET academic_year=%s, semester=%s, start_date=%s, end_date=%s, is_active=%s
            WHERE id=%s
            """,
            (academic_year, semester, start_date, end_date, is_active, id),
        )
        conn.commit()
        conn.close()
        return redirect("/academic-terms")

    cursor.execute("SELECT * FROM school_terms WHERE id=%s", (id,))
    term = cursor.fetchone()
    conn.close()

    return render_template("admin/edit_academic_term.html", term=term)


@admin_bp.route("/delete-academic-term/<id>", methods=["GET", "POST"])
@require_admin
def delete_academic_term(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM school_terms WHERE id=%s", (id,))
    term = cursor.fetchone()

    if request.method == "POST":
        cursor = conn.cursor()
        cursor.execute("DELETE FROM school_terms WHERE id=%s", (id,))
        conn.commit()
        conn.close()
        return redirect("/academic-terms")

    conn.close()

    if term is None:
        return redirect("/academic-terms")

    return render_template("admin/delete_academic_term.html", term=term)


# Finance Routes - Department Funds + Fines
@admin_bp.route("/finance")
@require_admin
def finance():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Get filter parameters
    year_level = request.args.get('year_level', '')
    course = request.args.get('course', '')
    
    # Get list of year levels and courses for filters
    cursor.execute("""
        SELECT DISTINCT year_level FROM students
        WHERE year_level IS NOT NULL
        ORDER BY year_level
    """)
    year_levels = [row['year_level'] for row in cursor.fetchall()]
    
    courses = ['BLIS', 'BSIS', 'BSCS']
    
    # Build query for student funds and fines
    query = """
        SELECT 
            s.id AS id,
            s.student_id,
            s.firstname,
            s.lastname,
            s.course,
            s.year_level,
            COALESCE(SUM(CASE WHEN sf.amount_due > 0 THEN sf.amount_due ELSE 0 END), 0) as total_funds,
            COALESCE(SUM(CASE WHEN f.amount > 0 THEN f.amount ELSE 0 END), 0) as total_fines
        FROM students s
        LEFT JOIN student_funds sf ON COALESCE(s.student_id, CAST(s.id AS CHAR)) = sf.student_id
        LEFT JOIN fines f ON COALESCE(s.student_id, CAST(s.id AS CHAR)) = f.student_id
        WHERE s.status = 'Active'
    """
    
    params = []

    if course:
        query += " AND s.course = %s"
        params.append(course)

    if year_level:
        query += " AND s.year_level = %s"
        params.append(year_level)

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
            ) AS total_funds,
            (
                SELECT COALESCE(SUM(f.amount), 0)
                FROM fines f
                WHERE f.student_id = COALESCE(s.student_id, CAST(s.id AS CHAR))
            ) AS total_fines
        FROM students s
        WHERE s.status = 'Active'
    """

    if course:
        query += " AND s.course = %s"

    if year_level:
        query += " AND s.year_level = %s"

    query += " ORDER BY s.lastname, s.firstname"

    cursor.execute(query, params)
    students_data = cursor.fetchall()

    cursor.execute("""
        SELECT DISTINCT academic_year FROM school_terms
        ORDER BY academic_year DESC
    """)
    academic_years = [row["academic_year"] for row in cursor.fetchall()]

    cursor.execute("""
        SELECT DISTINCT semester FROM school_terms
        ORDER BY semester
    """)
    semesters = [row["semester"] for row in cursor.fetchall()]
    
    cursor.close()
    conn.close()
    
    return render_template(
        "admin/finance.html",
        students=students_data,
        year_levels=year_levels,
        courses=courses,
        selected_year_level=year_level,
        selected_course=course,
        academic_years=academic_years,
        semesters=semesters
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

    events = event_model.get_all_events()
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
    cursor.execute("""
        SELECT COALESCE(SUM(amount_due), 0) as total_funds 
        FROM student_funds WHERE student_id = %s
    """, (payment_key,))
    funds = cursor.fetchone()
    total_funds = float(funds['total_funds']) if funds else 0
    
    # Get total fines balance
    cursor.execute("""
        SELECT COALESCE(SUM(amount), 0) as total_fines 
        FROM fines WHERE student_id = %s
    """, (payment_key,))
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
    
    # Get recent transactions
    cursor.execute("""
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
        ORDER BY t.transaction_date DESC
        LIMIT 50
    """)
    recent_transactions = cursor.fetchall()
    
    # Get academic years and semesters for the form
    cursor.execute("""
        SELECT DISTINCT academic_year FROM school_terms 
        ORDER BY academic_year DESC
    """)
    academic_years = [row['academic_year'] for row in cursor.fetchall()]
    
    cursor.execute("""
        SELECT DISTINCT semester FROM school_terms 
        ORDER BY semester
    """)
    semesters = [row['semester'] for row in cursor.fetchall()]
    
    cursor.close()
    conn.close()
    
    return render_template(
        "admin/payments.html",
        transactions=recent_transactions,
        academic_years=academic_years,
        semesters=semesters
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

        totals = {"Funds": Decimal("0.00"), "Fines": Decimal("0.00")}
        for transaction in transactions:
            transaction_type = transaction["transaction_type"]
            if transaction_type in totals:
                totals[transaction_type] += Decimal(str(transaction["amount"] or 0))

        return render_template(
            "admin/transaction_report.html",
            transactions=transactions,
            period_label=period_label,
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
                    SELECT id, student_id, firstname, lastname, course, year_level
                    FROM students
                    FOR UPDATE
                    """
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
                            INSERT INTO student_funds (student_id, fund_id, amount_due)
                            VALUES (%s, NULL, %s)
                            """,
                            (student_key, amount_due),
                        )
                    else:
                        cursor.execute(
                            """
                            INSERT INTO fines (student_id, event_id, fine_type, amount)
                            VALUES (%s, NULL, NULL, %s)
                            """,
                            (student_key, amount_due),
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

    return render_template(
        'admin/upload_csv.html',
        message=message,
        message_type=message_type,
        imported_count=imported_count,
        row_errors=row_errors,
        omitted_error_count=omitted_error_count,
    )


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
    
    # Validate input
    if not all([student_id, transaction_type, payment_type, amount, academic_year, semester]):
        return {"error": "Missing required fields"}, 400
    if transaction_type not in {"Funds", "Fines"}:
        return {"error": "Choose Funds or Fines for the transaction type"}, 400
    if payment_type not in {"Partial", "Full"}:
        return {"error": "Choose Partial or Full for the payment type"}, 400
    
    try:
        amount = float(amount)
        if amount <= 0:
            return {"error": "Amount must be greater than 0"}, 400
    except ValueError:
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
        cursor.execute("""
            INSERT INTO transactions 
            (student_id, transaction_type, payment_type, amount, academic_year, semester, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            payment_key,
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
                SELECT id, amount_due
                FROM student_funds
                WHERE student_id = %s AND amount_due > 0
                ORDER BY amount_due ASC, id ASC
                FOR UPDATE
                """,
                (payment_key,),
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
                    SET amount_due = %s
                    WHERE id = %s AND student_id = %s
                    """,
                    (after_amount, row['id'], payment_key),
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
                WHERE student_id = %s AND amount > 0
                ORDER BY event_id, fine_id
                FOR UPDATE
                """,
                (payment_key,),
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
