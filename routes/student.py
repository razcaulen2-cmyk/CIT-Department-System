import mysql.connector
from flask import Blueprint, redirect, render_template, session

from config import get_db_connection

student_bp = Blueprint("student", __name__)


@student_bp.route("/student-dashboard")
def student_dashboard():
    if "student" not in session:
        return redirect("/student-login")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM students WHERE id=%s", (session["student"],))
    student = cursor.fetchone()

    cursor.execute("SELECT DISTINCT academic_year FROM school_terms ORDER BY academic_year DESC")
    academic_years = cursor.fetchall()

    cursor.execute("SELECT * FROM school_terms WHERE is_active=TRUE LIMIT 1")
    active_term = cursor.fetchone()

    try:
        cursor.execute("SELECT * FROM system_settings LIMIT 1")
        settings = cursor.fetchone()
    except mysql.connector.errors.ProgrammingError:
        settings = None

    conn.close()

    if not settings:
        settings = {
            "academic_year": active_term.get("academic_year") if active_term else "",
            "semester": active_term.get("semester") if active_term else "",
        }

    return render_template(
        "student/dashboard.html",
        student=student,
        academic_years=academic_years,
        active_term=active_term,
        settings=settings,
    )