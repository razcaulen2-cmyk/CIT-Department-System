from flask import Blueprint, flash, render_template, request, redirect, url_for, jsonify, current_app
from models import event_model, attendance_model, semester_model, student_model
from config import get_db_connection
from werkzeug.security import check_password_hash
from datetime import datetime, timedelta, time
from .admin import require_admin

events_bp = Blueprint(
    "events",
    __name__
)


def parse_time(value):
    try:
        return datetime.strptime(value, "%H:%M")
    except Exception:
        return None
@events_bp.route('/events', methods=['GET'])
@require_admin
def events_list():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """
        SELECT id, academic_year, semester, fund_amount, is_active
        FROM school_terms
        ORDER BY academic_year DESC,
                 CASE semester
                     WHEN '1st Semester' THEN 1
                     WHEN '2nd Semester' THEN 2
                     ELSE 3
                 END,
                 semester
        """
    )
    semesters = cursor.fetchall()
    cursor.close()
    conn.close()

    active_semester = next(
        (semester for semester in semesters if semester['is_active']),
        None,
    )
    requested_semester_id = request.args.get('semester_id', type=int)
    selected_semester = next(
        (semester for semester in semesters if semester['id'] == requested_semester_id),
        active_semester,
    )
    events = event_model.get_all_events()
    if selected_semester:
        events = [
            event for event in events
            if event.get('semester_id') == selected_semester['id']
        ]
    else:
        events = []

    return render_template(
        'admin/events.html',
        events=events,
        active_semester=active_semester,
        semesters=semesters,
        selected_semester=selected_semester,
        selected_semester_id=selected_semester['id'] if selected_semester else '',
    )


@events_bp.route('/events/<int:event_id>/exemptions', methods=['GET', 'POST'])
@require_admin
def event_exemptions(event_id):
    event = event_model.get_event(event_id)
    if not event:
        return jsonify({'success': False, 'message': 'Event not found'}), 404

    if request.method == 'POST':
        data = request.get_json(silent=True) or request.form
        student_ids = data.get('student_ids', [])
        list_ids = data.get('list_ids', [])
        if isinstance(student_ids, str):
            student_ids = [value for value in student_ids.split(',') if value]
        if isinstance(list_ids, str):
            list_ids = [value for value in list_ids.split(',') if value]
        try:
            resolved_ids = {int(student_id) for student_id in student_ids}
            resolved_ids.update(event_model.get_exemption_list_student_ids(list_ids))
        except (TypeError, ValueError):
            return jsonify({'success': False, 'message': 'Invalid exemption selection'}), 400
        event_model.save_event_exemptions(event_id, resolved_ids)
        event_model.sync_fines_for_event(event)
        return jsonify({'success': True, 'count': len(resolved_ids)})

    enrolled_student_ids = semester_model.get_semester_student_ids(event.get('semester_id'))
    students = [
        student for student in student_model.get_all_students()
        if student.get('id') in enrolled_student_ids
    ]
    for student in students:
        student['display_name'] = f"{student.get('lastname', '')}, {student.get('firstname', '')}".strip(', ')
    exempted_student_ids = event_model.get_event_exemption_ids(event_id)
    return jsonify({
        'success': True,
        'event': {'id': event['id'], 'name': event['name']},
        'students': students,
        'exempted_student_ids': sorted(exempted_student_ids),
        'exempted_students': [student for student in students if student.get('id') in exempted_student_ids],
        'lists': event_model.get_exemption_lists(),
    })


@events_bp.route('/events/<int:event_id>/exemptions/<int:student_id>', methods=['DELETE'])
@require_admin
def remove_event_exemption(event_id, student_id):
    event = event_model.get_event(event_id)
    if not event:
        return jsonify({'success': False, 'message': 'Event not found'}), 404
    event_model.remove_event_exemption(event_id, student_id)
    event_model.sync_fines_for_event(event)
    return jsonify({'success': True})


@events_bp.route('/exemption-lists', methods=['POST'])
@require_admin
def create_exemption_list():
    data = request.get_json(silent=True) or request.form
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'success': False, 'message': 'List name is required'}), 400
    student_ids = data.get('student_ids', [])
    if isinstance(student_ids, str):
        student_ids = [value for value in student_ids.split(',') if value]
    try:
        student_ids = [int(student_id) for student_id in student_ids]
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'Invalid student selection'}), 400
    list_id = event_model.create_exemption_list(name, student_ids, data.get('year_level') or None)
    return jsonify({'success': True, 'list': {'id': list_id, 'name': name, 'year_level': data.get('year_level') or None}})


@events_bp.route('/exemption-lists/<int:list_id>', methods=['GET', 'PUT'])
@require_admin
def edit_exemption_list(list_id):
    if request.method == 'GET':
        exemption_list = event_model.get_exemption_list(list_id)
        if not exemption_list:
            return jsonify({'success': False, 'message': 'Exemption list not found'}), 404
        return jsonify({'success': True, 'list': exemption_list})

    data = request.get_json(silent=True) or request.form
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'success': False, 'message': 'List name is required'}), 400
    student_ids = data.get('student_ids', [])
    if isinstance(student_ids, str):
        student_ids = [value for value in student_ids.split(',') if value]
    try:
        student_ids = [int(student_id) for student_id in student_ids]
        event_model.update_exemption_list(list_id, name, student_ids, data.get('year_level') or None)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'Invalid student selection'}), 400
    return jsonify({'success': True})


@events_bp.route('/events/create', methods=['POST'])
@require_admin
def create_event():
    form = request.form
    name = form.get('name')
    date = form.get('date')
    login_time = form.get('login_time')
    logout_time = form.get('logout_time')
    login_cutoff_time = form.get('login_cutoff_time')
    logout_cutoff_time = form.get('logout_cutoff_time')
    absent_fine = float(form.get('absent_fine') or 0)
    late_fine = float(form.get('late_fine') or 0)
    grace_period = int(form.get('grace_period') or 0)
    is_active = 1 if form.get('is_active') == 'on' else 0

    if login_time and not login_cutoff_time:
        login_dt = parse_time(login_time)
        if login_dt:
            login_cutoff_time = (login_dt + timedelta(minutes=grace_period)).strftime("%H:%M")

    if logout_time and not logout_cutoff_time:
        logout_dt = parse_time(logout_time)
        if logout_dt:
            logout_cutoff_time = (logout_dt + timedelta(minutes=grace_period)).strftime("%H:%M")

    try:
        event_model.add_event(
            name,
            date,
            login_time,
            logout_time,
            login_cutoff_time,
            logout_cutoff_time,
            absent_fine,
            late_fine,
            grace_period,
            is_active,
        )
    except ValueError as error:
        flash(str(error), 'danger')

    return redirect(url_for('events.events_list'))


@events_bp.route('/events/<int:event_id>/edit', methods=['POST'])
@require_admin
def edit_event(event_id):
    form = request.form
    name = form.get('name')
    date = form.get('date')
    login_time = form.get('login_time')
    logout_time = form.get('logout_time')
    login_cutoff_time = form.get('login_cutoff_time')
    logout_cutoff_time = form.get('logout_cutoff_time')
    absent_fine = float(form.get('absent_fine') or 0)
    late_fine = float(form.get('late_fine') or 0)
    grace_period = int(form.get('grace_period') or 0)

    if login_time and not login_cutoff_time:
        login_dt = parse_time(login_time)
        if login_dt:
            login_cutoff_time = (login_dt + timedelta(minutes=grace_period)).strftime("%H:%M")

    if logout_time and not logout_cutoff_time:
        logout_dt = parse_time(logout_time)
        if logout_dt:
            logout_cutoff_time = (logout_dt + timedelta(minutes=grace_period)).strftime("%H:%M")

    event_model.update_event(
        event_id,
        name,
        date,
        login_time,
        logout_time,
        login_cutoff_time,
        logout_cutoff_time,
        absent_fine,
        late_fine,
        grace_period,
    )

    return redirect(url_for(
        'events.events_list',
        semester_id=request.form.get('return_semester_id') or None,
    ))


@events_bp.route('/events/<int:event_id>/delete', methods=['POST'])
@require_admin
def delete_event(event_id):
    username = request.form.get('delete_username', '').strip()
    password = request.form.get('delete_password', '')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM admins WHERE username=%s", (username,))
    admin = cursor.fetchone()
    cursor.close()
    conn.close()

    if not admin or not check_password_hash(admin.get('password', ''), password):
        return redirect(url_for(
            'events.events_list',
            semester_id=request.form.get('return_semester_id') or None,
            delete_error='invalid',
        ))

    event_model.delete_event(event_id)
    return redirect(url_for(
        'events.events_list',
        semester_id=request.form.get('return_semester_id') or None,
    ))


def format_time_value(time_value):
    if not time_value:
        return None
    if isinstance(time_value, str):
        return time_value
    if isinstance(time_value, timedelta):
        time_value = (datetime.min + time_value).time()
    if isinstance(time_value, time):
        text = time_value.strftime('%I:%M')
        return text.lstrip('0') or '0'
    return None


def format_time_range(start, end):
    start_text = format_time_value(start)
    end_text = format_time_value(end)
    if start_text and end_text:
        return f"{start_text}-{end_text}"
    if start_text:
        return start_text
    return '—'


def format_attendance_time(timestamp_value):
    if not timestamp_value:
        return None
    from datetime import datetime
    if isinstance(timestamp_value, str):
        try:
            # Try common datetime formats
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%H:%M:%S", "%H:%M"):
                try:
                    parsed = datetime.strptime(timestamp_value, fmt)
                    break
                except Exception:
                    parsed = None
                    continue
            if not parsed:
                return None
            timestamp_value = parsed
        except Exception:
            return None
    if isinstance(timestamp_value, datetime):
        text = timestamp_value.strftime('%I:%M:%S %p')
        return text.lstrip('0') or '0'
    return None


@events_bp.route('/events/<int:event_id>/conduct', methods=['GET'])
@require_admin
def conduct_event(event_id):
    event = event_model.get_event(event_id)
    if event:
        event['login_range'] = format_time_range(event.get('login_time'), event.get('login_cutoff_time'))
        event['logout_range'] = format_time_range(event.get('logout_time'), event.get('logout_cutoff_time'))
    return render_template('admin/conduct_attendance.html', event=event)


def build_attendance_rows(event, students, course=None, year_level=None):
    enrolled_student_ids = semester_model.get_semester_student_ids(event.get('semester_id'))
    students = [student for student in students if student.get('id') in enrolled_student_ids]
    attendance_records = attendance_model.get_attendance_by_event(event['id'])
    exempted_student_ids = event_model.get_event_exemption_ids(event['id'])
    paper_attendance = event_model.get_paper_attendance_for_event(event['id'])
    attendance_by_student = {}
    for record in attendance_records:
        attendance_by_student.setdefault(record['student_id'], []).append(record)

    # Determine event type based on configuration
    has_login_window = bool(event.get('login_time') or event.get('login_cutoff_time'))
    has_logout_window = bool(event.get('logout_time') or event.get('logout_cutoff_time'))

    rows = []
    for student in students:
        if course and student.get('course') != course:
            continue
        if year_level and str(student.get('year_level')) != str(year_level):
            continue

        student_records = attendance_by_student.get(student['id'], [])
        login_record = next((r for r in student_records if r['status'] == 'login'), None)
        logout_record = next((r for r in student_records if r['status'] == 'logout'), None)

        if student['id'] in exempted_student_ids:
            status = 'Exempted'
            source = 'Exemption'
        elif student['id'] in paper_attendance:
            status = 'Present' if paper_attendance[student['id']] == 'present' else 'Late'
            source = 'Paper'
        elif has_login_window and not has_logout_window:
            # Login-only event: Present if has login
            status = 'Present' if login_record else 'Absent'
            source = 'System' if login_record else 'Not recorded'
        elif has_logout_window and not has_login_window:
            # Logout-only event: Present if has logout
            status = 'Present' if logout_record else 'Absent'
            source = 'System' if logout_record else 'Not recorded'
        else:
            # Two-window event: need both or determine based on records
            if logout_record and not login_record:
                status = 'Late'
            elif login_record and not logout_record:
                status = 'Absent'
            elif not login_record and not logout_record:
                status = 'Absent'
            else:
                status = 'Present'
            source = 'System' if login_record or logout_record else 'Not recorded'

        login_time_text = format_attendance_time(login_record['timestamp']) if login_record else None
        logout_time_text = format_attendance_time(logout_record['timestamp']) if logout_record else None

        rows.append({
            'student_id': student['id'],
            'firstname': student['firstname'],
            'lastname': student['lastname'],
            'course': student.get('course'),
            'year_level': student.get('year_level'),
            'status': status,
            'source': source,
            'login_time': login_time_text,
            'logout_time': logout_time_text,
            'event_name': event['name'],
        })

    rows.sort(key=lambda row: (row['lastname'] or '', row['firstname'] or ''))
    return rows


@events_bp.route('/attendance', methods=['GET'])
@require_admin
def attendance_page():
    academic_year = request.args.get('academic_year', '').strip()
    semester = request.args.get('semester', '').strip()

    students = student_model.get_all_students()
    events = event_model.get_all_events()

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """
        SELECT academic_year, semester
        FROM school_terms
        ORDER BY academic_year DESC,
                 CASE semester
                     WHEN '1st Semester' THEN 1
                     WHEN '2nd Semester' THEN 2
                     ELSE 3
                 END,
                 semester
        """
    )
    terms = cursor.fetchall()
    cursor.close()
    conn.close()

    # derive distinct course list and year levels from students
    courses = sorted({s['course'] for s in students if s.get('course')})
    year_levels = sorted({s['year_level'] for s in students if s.get('year_level')})

    academic_years = sorted({term['academic_year'] for term in terms}, reverse=True)
    available_semesters = {
        term['semester'] for term in terms if term['academic_year'] == academic_year
    }
    if semester not in available_semesters:
        semester = ''

    filtered_events = [
        event for event in events
        if (not academic_year or event.get('academic_year') == academic_year)
        and (not semester or event.get('semester_name') == semester)
    ]

    return render_template(
        'admin/attendance.html',
        courses=courses,
        year_levels=year_levels,
        events=filtered_events,
        academic_years=academic_years,
        selected_academic_year=academic_year,
        terms=terms,
        selected_semester=semester,
    )


@events_bp.route('/attendance/event/<int:event_id>', methods=['GET'])
@require_admin
def attendance_event_data(event_id):
    event = event_model.get_event(event_id)
    if not event:
        return jsonify({'success': False, 'message': 'Event not found'}), 404

    students = student_model.get_all_students()
    rows = build_attendance_rows(
        event,
        students,
        request.args.get('course') or None,
        request.args.get('year_level') or None,
    )
    return jsonify({
        'success': True,
        'event': {'id': event['id'], 'name': event['name'], 'date': str(event['date'])},
        'rows': rows,
    })


@events_bp.route('/attendance/event/<int:event_id>/paper', methods=['POST'])
@require_admin
def update_paper_attendance(event_id):
    event = event_model.get_event(event_id)
    if not event:
        return jsonify({'success': False, 'message': 'Event not found'}), 404

    data = request.get_json(silent=True) or request.form
    try:
        student_id = int(data.get('student_id'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'Invalid student'}), 400

    student = student_model.get_student(student_id)
    if not student:
        return jsonify({'success': False, 'message': 'Student not found'}), 404
    if not semester_model.is_student_enrolled_in_semester(event.get('semester_id'), student_id):
        return jsonify({'success': False, 'message': 'Student is not currently enrolled in this event semester.'}), 409

    status = (data.get('status') or '').lower()
    try:
        if status == 'clear':
            event_model.clear_paper_attendance(event_id, student_id)
        else:
            event_model.save_paper_attendance(event_id, student_id, status)
        event_model.sync_fines_for_event(event)
    except ValueError as error:
        return jsonify({'success': False, 'message': str(error)}), 400

    return jsonify({'success': True, 'status': status})


def sort_attendance_rows(rows, sort_keys):
    if not sort_keys:
        return rows

    priority = ['course', 'year', 'name']
    selected = [sort_key for sort_key in priority if sort_key in sort_keys]
    if not selected:
        return rows

    def row_sort_key(r):
        key = []
        for sort_key in selected:
            if sort_key == 'course':
                key.append((r.get('course') or '').strip().lower())
            elif sort_key == 'year':
                try:
                    key.append(int(r.get('year_level')))
                except Exception:
                    key.append(0)
            elif sort_key == 'name':
                lastname = (r.get('lastname') or '').strip().lower()
                firstname = (r.get('firstname') or '').strip().lower()
                key.extend([lastname, firstname])
        return tuple(key)

    rows.sort(key=row_sort_key)
    return rows


@events_bp.route('/attendance/report', methods=['GET'])
@require_admin
def attendance_report():
    event_id = request.args.get('event_id')
    status_option = request.args.get('status_option', 'both')
    course = request.args.get('course')
    year_level = request.args.get('year_level')
    sort_by = request.args.getlist('sort_by')
    output_format = request.args.get('output_format', 'pdf')

    if not event_id or not event_id.isdigit():
        return redirect(url_for('events.attendance_page'))

    event = event_model.get_event(int(event_id))
    if not event:
        return redirect(url_for('events.attendance_page'))

    students = student_model.get_all_students()
    rows = build_attendance_rows(event, students, course, year_level)

    if status_option == 'present':
        rows = [r for r in rows if r['status'] == 'Present']
    elif status_option == 'absent':
        rows = [r for r in rows if r['status'] in ('Absent', 'Late')]

    rows = sort_attendance_rows(rows, sort_by)

    if output_format == 'excel':
        return generate_attendance_excel(event, rows)
    return generate_attendance_pdf(event, rows)


def generate_attendance_pdf(event, rows):
    from io import BytesIO
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, leftMargin=0.5*inch, rightMargin=0.5*inch, topMargin=0.5*inch, bottomMargin=0.5*inch)
    styles = getSampleStyleSheet()
    title = Paragraph(f"Attendance Report: {event.get('name')} ({event.get('date')})", styles['Heading2'])

    data = [["Student", "Course", "Year", "Login Time", "Logout Time", "Status"]]
    for row in rows:
        data.append([
            f"{row['lastname']}, {row['firstname']}",
            row['course'] or '',
            row['year_level'] or '',
            row['login_time'] or '—',
            row['logout_time'] or '—',
            row['status'],
        ])

    table = Table(data, repeatRows=1, hAlign='LEFT')
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f5f5f5')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('LINEBEFORE', (0, 0), (-1, -1), 0.25, colors.grey),
        ('LINEAFTER', (0, 0), (-1, -1), 0.25, colors.grey),
        ('LINEABOVE', (0, 1), (-1, 1), 0.25, colors.grey),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
    ]))

    elements = [title, Spacer(1, 0.2*inch), table]
    doc.build(elements)

    buffer.seek(0)
    return current_app.response_class(buffer.read(), mimetype='application/pdf', headers={
        'Content-Disposition': f'attachment;filename=attendance_report_{event.get("id")}.pdf'
    })


def generate_attendance_excel(event, rows):
    from io import BytesIO
    import pandas as pd

    data = []
    for row in rows:
        data.append({
            'Student': f"{row['lastname']}, {row['firstname']}",
            'Course': row['course'] or '',
            'Year': row['year_level'] or '',
            'Login Time': row['login_time'] or '',
            'Logout Time': row['logout_time'] or '',
            'Status': row['status'],
        })

    df = pd.DataFrame(data)
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Attendance', index=False)
    buffer.seek(0)

    return current_app.response_class(buffer.read(), mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers={
        'Content-Disposition': f'attachment;filename=attendance_report_{event.get("id")}.xlsx'
    })


@events_bp.route('/events/record_rfid', methods=['POST'])
@require_admin
def record_rfid():
    data = request.get_json() or request.form
    rfid_uid = data.get('rfid_uid')
    event_id = data.get('event_id')

    if not rfid_uid or not event_id:
        return jsonify({'success': False, 'message': 'Missing parameters'}), 400

    event = event_model.get_event(event_id)
    if not event:
        return jsonify({'success': False, 'message': 'Event not found'}), 404

    student = student_model.get_student_by_rfid(rfid_uid)
    if not student:
        return jsonify({'success': False, 'message': 'RFID not registered'}), 404
    if not semester_model.is_student_enrolled_in_semester(event.get('semester_id'), student['id']):
        return jsonify({
            'success': False,
            'message': 'Student is not enrolled in this event semester.',
        }), 403

    now = datetime.now()
    event_date = event.get('date')
    login_time = event.get('login_time')
    logout_time = event.get('logout_time')
    login_cutoff = event.get('login_cutoff_time')
    logout_cutoff = event.get('logout_cutoff_time')

    def combine_datetime(date_value, time_value):
        if not date_value or not time_value:
            return None

        if isinstance(date_value, str):
            try:
                date_value = datetime.strptime(date_value, "%Y-%m-%d").date()
            except Exception:
                return None

        from datetime import timedelta as datetime_timedelta

        if isinstance(time_value, datetime_timedelta):
            time_value = (datetime.min + time_value).time()
        elif isinstance(time_value, str):
            parsed = None
            for fmt in ["%H:%M:%S", "%H:%M"]:
                try:
                    parsed = datetime.strptime(time_value, fmt).time()
                    break
                except Exception:
                    continue
            if not parsed:
                return None
            time_value = parsed

        if isinstance(time_value, time):
            return datetime.combine(date_value, time_value)

        return None

    grace_period = int(event.get('grace_period') or 0)
    login_start = combine_datetime(event_date, login_time)
    login_end = combine_datetime(event_date, login_cutoff)
    logout_start = combine_datetime(event_date, logout_time)
    logout_end = combine_datetime(event_date, logout_cutoff)

    if not login_end and login_time:
        login_end = combine_datetime(event_date, login_time)
    if not logout_end and logout_time:
        logout_end = combine_datetime(event_date, logout_time)

    if login_start and login_end and login_end <= login_start:
        login_end = login_start + timedelta(minutes=grace_period)
    if logout_start and logout_end and logout_end <= logout_start:
        logout_end = logout_start + timedelta(minutes=grace_period)

    if login_end and login_start and grace_period > 0 and login_end == login_start:
        login_end = login_start + timedelta(minutes=grace_period)
    if logout_end and logout_start and grace_period > 0 and logout_end == logout_start:
        logout_end = logout_start + timedelta(minutes=grace_period)

    status = None
    if login_start and login_end and login_start <= now <= login_end:
        status = 'login'
    elif logout_start and logout_end and logout_start <= now <= logout_end:
        status = 'logout'
    else:
        if login_start and now < login_start:
            return jsonify({'success': False, 'message': 'Event has not started yet. Please wait until login time.'}), 400
        if logout_end and now > logout_end:
            return jsonify({'success': False, 'message': 'Event is already closed.'}), 400
        if login_end and logout_start and login_end < now < logout_start:
            return jsonify({'success': False, 'message': 'Attendance window is not open. Please wait until logout time.'}), 400
        return jsonify({'success': False, 'message': 'Unable to determine tap period. Please contact the administrator.'}), 400

    if attendance_model.attendance_exists(event_id, student['id'], status):
        verb = 'in' if status == 'login' else 'out'
        return jsonify({'success': False, 'message': f"{student['firstname']} {student['lastname']} has already logged {verb}."}), 400

    timestamp = now
    attendance_model.record_attendance(event_id, student['id'], status, timestamp)

    verb = 'in' if status == 'login' else 'out'
    return jsonify({
        'success': True,
        'student': student,
        'status': status,
        'course': student.get('course'),
        'year_level': student.get('year_level'),
        'message': f"{student['firstname']} {student['lastname']} ({student.get('course')} - Year {student.get('year_level')}) logged {verb}."
    })
