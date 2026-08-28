import re
import time

from flask import Blueprint, jsonify, redirect, render_template, request, session
from werkzeug.security import check_password_hash

from config import get_db_connection

auth_bp = Blueprint("auth", __name__)
last_scan = {}


@auth_bp.route("/student-login", methods=["GET", "POST"])
def student_login():
    if request.method == "POST":
        raw_student_id = request.form["student_id"].strip()
        student_id = re.sub(r"\D", "", raw_student_id)
        if not student_id:
            student_id = raw_student_id

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM students WHERE student_id=%s", (student_id,))
        student = cursor.fetchone()
        conn.close()

        if student:
            session["student"] = student["id"]
            if request.accept_mimetypes.accept_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({"success": True, "redirect": "/student-dashboard"})
            return redirect("/student-dashboard")

        error_msg = "Invalid School ID."
        if request.accept_mimetypes.accept_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({"success": False, "message": error_msg})
        return render_template("student/login.html", error=error_msg)

    # If requested as modal fragment, return only the inner student card
    if request.args.get('modal'):
        return render_template('fragments/student_login_fragment.html')

    return render_template("student/login.html")


@auth_bp.route("/admin-login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        data = request.get_json(silent=True) or request.form
        username = (data.get("username") or "").strip()
        password = data.get("password", "")

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM admins WHERE username=%s", (username,))
        admin = cursor.fetchone()
        conn.close()

        if admin and check_password_hash(admin.get("password", ""), password):
            admin_id = admin.get("admin_id") or admin.get("id")
            if admin_id:
                session["admin"] = admin_id
                # Always redirect to admin dashboard on successful login
                redirect_target = "/admin-dashboard"
                # If client expects JSON (AJAX modal), return JSON success
                if request.accept_mimetypes.accept_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({"success": True, "redirect": redirect_target})
                return redirect(redirect_target)
            error = "Login error: Database configuration issue"
        else:
            error = "Invalid Username or Password"
        # if this was an AJAX login attempt, return JSON error immediately
        if request.accept_mimetypes.accept_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({"success": False, "message": error})
    # If requested as modal fragment, return the form fragment
    if request.args.get('modal'):
        return render_template('fragments/admin_login_fragment.html', error=error)

    return render_template("admin/login.html", error=error)


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect("/")


@auth_bp.route("/student-logout")
def student_logout():
    session.pop("student", None)
    return redirect("/student-login")


@auth_bp.route("/verify-rfid", methods=["POST"])
def verify_rfid():
    data = request.get_json() or {}
    raw_value = str(data.get("student_id", "")).strip()

    if not raw_value:
        return jsonify({"success": False})

    candidates = [raw_value]
    digits_only = re.sub(r"\D", "", raw_value)
    if digits_only and digits_only != raw_value:
        candidates.append(digits_only)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    student = None
    for candidate in candidates:
        cursor.execute("SELECT * FROM students WHERE student_id = %s", (candidate,))
        student = cursor.fetchone()
        if student:
            break

    conn.close()

    if student:
        session["student"] = student["id"]
        last_scan.update(
            {
                "timestamp": time.time(),
                "raw": raw_value,
                "candidates": candidates,
                "found": True,
                "matched": student["student_id"],
            }
        )
        return jsonify(
            {
                "success": True,
                "id": student["id"],
                "firstname": student["firstname"],
                "lastname": student["lastname"],
                "course": student["course"],
                "year_level": student["year_level"],
            }
        )

    last_scan.update(
        {
            "timestamp": time.time(),
            "raw": raw_value,
            "candidates": candidates,
            "found": False,
            "matched": None,
        }
    )

    return jsonify({"success": False})


@auth_bp.route("/debug-last-scan")
def debug_last_scan():
    return jsonify(last_scan)
