import mysql.connector
from flask import Blueprint, jsonify, redirect, render_template, session

from config import get_db_connection
from models import attendance_model, event_model, semester_model, student_model

student_bp = Blueprint("student", __name__)


@student_bp.route("/student-dashboard")
def student_dashboard():
    if "student" not in session:
        return redirect("/student-login")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM students WHERE id=%s", (session["student"],))
    student = cursor.fetchone()

    balance_key = student.get('student_id') or str(student['id']) if student else None
    cursor.execute(
        "SELECT COALESCE(SUM(amount_due), 0) AS total_funds FROM student_funds WHERE student_id=%s",
        (balance_key,),
    )
    total_funds = float(cursor.fetchone()['total_funds'] or 0)
    cursor.execute(
        "SELECT COALESCE(SUM(amount), 0) AS total_fines FROM fines WHERE student_id=%s",
        (balance_key,),
    )
    total_fines = float(cursor.fetchone()['total_fines'] or 0)

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
        total_funds=total_funds,
        total_fines=total_fines,
        total_balance=total_funds + total_fines,
    )


@student_bp.route("/student/attendance", methods=["GET"])
def student_attendance():
    student_id = session.get("student")
    if not student_id:
        return jsonify({"success": False, "message": "Please log in to view attendance."}), 401

    student = student_model.get_student(student_id)
    if not student:
        return jsonify({"success": False, "message": "Student not found."}), 404

    attendance_records = attendance_model.get_attendance_for_student(student["id"])
    records_by_event = {}
    for record in attendance_records:
        records_by_event.setdefault(record["event_id"], []).append(record)

    exempted_event_ids = event_model.get_exempted_event_ids_for_student(student["id"])
    paper_attendance = event_model.get_paper_attendance_for_student(student["id"])
    enrolled_semester_ids = semester_model.get_student_semester_ids(student["id"])
    history = []
    for event in event_model.get_all_events():
        if event.get("semester_id") not in enrolled_semester_ids:
            continue
        records = records_by_event.get(event["id"], [])
        statuses = {record["status"] for record in records}
        has_login_window = bool(event.get("login_time") or event.get("login_cutoff_time"))
        has_logout_window = bool(event.get("logout_time") or event.get("logout_cutoff_time"))

        if event["id"] in exempted_event_ids:
            status = "Exempted"
        elif event["id"] in paper_attendance:
            status = "Present" if paper_attendance[event["id"]] == "present" else "Late"
        elif has_login_window and not has_logout_window:
            status = "Present" if "login" in statuses else "Absent"
        elif has_logout_window and not has_login_window:
            status = "Present" if "logout" in statuses else "Absent"
        elif "logout" in statuses and "login" not in statuses:
            status = "Late"
        elif "login" in statuses and "logout" in statuses:
            status = "Present"
        else:
            status = "Absent"

        history.append({
            "event_name": event["name"],
            "event_date": str(event["date"]),
            "status": status,
        })

    return jsonify({"success": True, "events": history})