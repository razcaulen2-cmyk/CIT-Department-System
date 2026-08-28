from functools import wraps
import os
import re
from urllib.parse import quote_plus

from flask import Blueprint, flash, redirect, render_template, request, session
from werkzeug.utils import secure_filename

from config import get_db_connection
from models import event_model

admin_bp = Blueprint("admin", __name__)


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
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM students WHERE id=%s", (id,))
    student = cursor.fetchone()

    if request.method == "POST":
        raw_rfid_value = request.form["student_id"]
        rfid_value = re.sub(r"\D", "", raw_rfid_value).strip() or raw_rfid_value.strip()

        cursor = conn.cursor()
        cursor.execute("SELECT * FROM students WHERE student_id=%s", (rfid_value,))
        existing = cursor.fetchone()

        if existing:
            conn.close()
            return "RFID already assigned."

        cursor.execute("UPDATE students SET student_id=%s WHERE id=%s", (rfid_value, id))
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
    
    cursor.close()
    conn.close()
    
    return render_template(
        "admin/finance.html",
        students=students_data,
        year_levels=year_levels,
        courses=courses,
        selected_year_level=year_level,
        selected_course=course
    )


# API endpoint to get student balance via QR/ID tap
@admin_bp.route("/api/student-balance/<student_id>", methods=["GET"])
@require_admin
def get_student_balance(student_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Get student info
    cursor.execute("""
        SELECT student_id, firstname, lastname, course, year_level 
        FROM students WHERE student_id = %s
    """, (student_id,))
    student = cursor.fetchone()
    
    if not student:
        cursor.close()
        conn.close()
        return {"error": "Student not found"}, 404
    
    # Get total funds balance
    cursor.execute("""
        SELECT COALESCE(SUM(amount_due), 0) as total_funds 
        FROM student_funds WHERE student_id = %s
    """, (student_id,))
    funds = cursor.fetchone()
    total_funds = float(funds['total_funds']) if funds else 0
    
    # Get total fines balance
    cursor.execute("""
        SELECT COALESCE(SUM(amount), 0) as total_fines 
        FROM fines WHERE student_id = %s
    """, (student_id,))
    fines = cursor.fetchone()
    total_fines = float(fines['total_fines']) if fines else 0
    
    cursor.close()
    conn.close()
    
    return {
        "student_id": student['student_id'],
        "firstname": student['firstname'],
        "lastname": student['lastname'],
        "course": student['course'],
        "year_level": student['year_level'],
        "total_funds": total_funds,
        "total_fines": total_fines,
        "total_balance": total_funds + total_fines
    }


# Payments & Transactions Page
@admin_bp.route("/payments")
@require_admin
def payments():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
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
            t.transaction_date
        FROM transactions t
        JOIN students s ON t.student_id = s.student_id
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


@admin_bp.route('/upload-csv', methods=['GET', 'POST'])
@require_admin
def upload_csv():
    message = None
    message_type = 'info'

    if request.method == 'POST':
        file = request.files.get('csv_file')
        if not file or file.filename == '':
            message = 'Please select a CSV file to upload.'
            message_type = 'danger'
        elif not file.filename.lower().endswith('.csv'):
            message = 'Only CSV files are allowed.'
            message_type = 'danger'
        else:
            filename = secure_filename(file.filename)
            upload_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'uploads')
            os.makedirs(upload_dir, exist_ok=True)
            upload_path = os.path.join(upload_dir, filename)
            file.save(upload_path)
            message = f'Uploaded {filename} successfully.'
            message_type = 'success'

    return render_template('admin/upload_csv.html', message=message, message_type=message_type)


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
    
    try:
        amount = float(amount)
        if amount <= 0:
            return {"error": "Amount must be greater than 0"}, 400
    except ValueError:
        return {"error": "Invalid amount"}, 400
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Verify student exists
    cursor.execute("SELECT student_id, firstname, lastname FROM students WHERE student_id = %s", (student_id,))
    student = cursor.fetchone()
    
    if not student:
        cursor.close()
        conn.close()
        return {"error": "Student not found"}, 404
    
    try:
        # Log the transaction
        cursor.execute("""
            INSERT INTO transactions 
            (student_id, transaction_type, payment_type, amount, academic_year, semester, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            student_id,
            transaction_type,
            payment_type,
            amount,
            academic_year,
            semester,
            session.get('admin', 'unknown')
        ))
        
        # Apply payment amount to balances (support Partial and Full)
        remaining = amount
        if transaction_type == 'Funds':
            # Apply to student_funds rows (oldest/smallest due first) without assuming an `id` column
            while remaining > 0:
                cursor.execute("SELECT amount_due FROM student_funds WHERE student_id = %s AND amount_due > 0 ORDER BY amount_due ASC LIMIT 1", (student_id,))
                row = cursor.fetchone()
                if not row:
                    break
                due = float(row['amount_due'])
                deduct = min(due, remaining)
                # update one matching row (LIMIT 1) by matching the current amount_due value
                cursor.execute("UPDATE student_funds SET amount_due = GREATEST(amount_due - %s, 0) WHERE student_id = %s AND amount_due = %s LIMIT 1", (deduct, student_id, row['amount_due']))
                remaining -= deduct
        else:  # Fines
            # Apply payment across fines records (oldest events first), identify rows by (student_id, event_id, fine_type)
            cursor.execute("SELECT student_id, event_id, fine_type, amount FROM fines WHERE student_id = %s AND amount > 0 ORDER BY event_id", (student_id,))
            fine_rows = cursor.fetchall()
            for row in fine_rows:
                if remaining <= 0:
                    break
                event_id = row.get('event_id')
                fine_type = row.get('fine_type')
                fine_amt = float(row.get('amount') or 0)
                deduct = min(fine_amt, remaining)
                cursor.execute("UPDATE fines SET amount = GREATEST(amount - %s, 0) WHERE student_id = %s AND event_id = %s AND fine_type = %s", (deduct, student_id, event_id, fine_type))
                remaining -= deduct
            # Remove fully paid fine records (optional cleanup)
            cursor.execute("DELETE FROM fines WHERE amount <= 0")
        
        conn.commit()
        
        return {
            "success": True,
            "message": f"Payment recorded: {student['firstname']} {student['lastname']} - PHP {amount}",
            "student_name": f"{student['firstname']} {student['lastname']}"
        }
    
    except Exception as e:
        conn.rollback()
        return {"error": str(e)}, 500
    
    finally:
        cursor.close()
        conn.close()

