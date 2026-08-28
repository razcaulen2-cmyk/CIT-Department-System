from config import get_db_connection
from models import attendance_model, student_model
from datetime import datetime, date, timedelta, time


def ensure_event_columns():
	conn = get_db_connection()
	cursor = conn.cursor()
	cursor.execute(
		"""
		SELECT COLUMN_NAME
		FROM INFORMATION_SCHEMA.COLUMNS
		WHERE TABLE_SCHEMA = DATABASE()
		  AND TABLE_NAME = 'events'
		"""
	)
	existing_columns = {row[0] for row in cursor.fetchall()}

	alter_clauses = []
	if 'login_time' not in existing_columns:
		alter_clauses.append('ADD COLUMN login_time TIME NULL')
	if 'logout_time' not in existing_columns:
		alter_clauses.append('ADD COLUMN logout_time TIME NULL')
	if 'login_cutoff_time' not in existing_columns:
		alter_clauses.append('ADD COLUMN login_cutoff_time TIME NULL')
	if 'logout_cutoff_time' not in existing_columns:
		alter_clauses.append('ADD COLUMN logout_cutoff_time TIME NULL')
	if 'grace_period' not in existing_columns:
		alter_clauses.append('ADD COLUMN grace_period INT NULL')
	if 'absent_fine' not in existing_columns:
		alter_clauses.append('ADD COLUMN absent_fine DECIMAL(10,2) NOT NULL DEFAULT 0')
	if 'late_fine' not in existing_columns:
		alter_clauses.append('ADD COLUMN late_fine DECIMAL(10,2) NOT NULL DEFAULT 0')

	if alter_clauses:
		cursor.execute(f"ALTER TABLE events {', '.join(alter_clauses)}")
		conn.commit()

	conn.close()


def get_all_events():
	ensure_event_columns()
	conn = get_db_connection()
	cursor = conn.cursor(dictionary=True)
	cursor.execute("""
		SELECT
			event_id AS id,
			event_name AS name,
			event_date AS date,
			absent_fine,
			late_fine,
			login_time,
			logout_time,
			login_cutoff_time,
			logout_cutoff_time,
			grace_period
		FROM events
		ORDER BY event_date DESC
	""")
	events = cursor.fetchall()
	conn.close()
	return events


def add_event(name, date, login_time=None, logout_time=None, login_cutoff_time=None, logout_cutoff_time=None, absent_fine=0, late_fine=0, grace_period=0, is_active=0):
	ensure_event_columns()
	conn = get_db_connection()
	cursor = conn.cursor()
	cursor.execute(
		"""
		INSERT INTO events
			(event_name, event_date, absent_fine, late_fine, login_time, logout_time, login_cutoff_time, logout_cutoff_time, grace_period)
		VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
		""",
		(
			name,
			date,
			absent_fine,
			late_fine,
			login_time,
			logout_time,
			login_cutoff_time,
			logout_cutoff_time,
			grace_period,
		),
	)
	conn.commit()
	conn.close()


def get_event(event_id):
	ensure_event_columns()
	conn = get_db_connection()
	cursor = conn.cursor(dictionary=True)
	cursor.execute(
		"""
		SELECT
			event_id AS id,
			event_name AS name,
			event_date AS date,
			absent_fine,
			late_fine,
			login_time,
			logout_time,
			login_cutoff_time,
			logout_cutoff_time,
			grace_period
		FROM events
		WHERE event_id=%s
		""",
		(event_id,)
	)
	ev = cursor.fetchone()
	conn.close()
	return ev


def update_event(event_id, name, date, login_time=None, logout_time=None, login_cutoff_time=None, logout_cutoff_time=None, absent_fine=0, late_fine=0, grace_period=0):
	ensure_event_columns()
	conn = get_db_connection()
	cursor = conn.cursor()
	cursor.execute(
		"""
		UPDATE events
		SET
			event_name = %s,
			event_date = %s,
			absent_fine = %s,
			late_fine = %s,
			login_time = %s,
			logout_time = %s,
			login_cutoff_time = %s,
			logout_cutoff_time = %s,
			grace_period = %s
		WHERE event_id = %s
		""",
		(
			name,
			date,
			absent_fine,
			late_fine,
			login_time,
			logout_time,
			login_cutoff_time,
			logout_cutoff_time,
			grace_period,
			event_id,
		),
	)
	conn.commit()
	conn.close()


def delete_event(event_id):
	conn = get_db_connection()
	cursor = conn.cursor()
	cursor.execute("DELETE FROM fines WHERE event_id=%s", (event_id,))
	cursor.execute("DELETE FROM attendance WHERE event_id=%s", (event_id,))
	cursor.execute("DELETE FROM events WHERE event_id=%s", (event_id,))
	conn.commit()
	conn.close()


def create_or_update_fine(student_id, event_id, fine_type, amount):
	conn = get_db_connection()
	cursor = conn.cursor()
	cursor.execute(
		"SELECT 1 FROM fines WHERE student_id=%s AND event_id=%s AND fine_type=%s LIMIT 1",
		(student_id, event_id, fine_type),
	)
	if cursor.fetchone():
		cursor.execute(
			"UPDATE fines SET amount=%s WHERE student_id=%s AND event_id=%s AND fine_type=%s",
			(amount, student_id, event_id, fine_type),
		)
	else:
		cursor.execute(
			"INSERT INTO fines (student_id, event_id, fine_type, amount) VALUES (%s, %s, %s, %s)",
			(student_id, event_id, fine_type, amount),
		)
	conn.commit()
	conn.close()


def remove_event_fine(student_id, event_id, fine_type=None):
	conn = get_db_connection()
	cursor = conn.cursor()
	if fine_type:
		cursor.execute(
			"DELETE FROM fines WHERE student_id=%s AND event_id=%s AND fine_type=%s",
			(student_id, event_id, fine_type),
		)
	else:
		cursor.execute(
			"DELETE FROM fines WHERE student_id=%s AND event_id=%s",
			(student_id, event_id),
		)
	conn.commit()
	conn.close()


def clear_fines_for_event(event_id):
	"""Remove all fines associated with a given event id."""
	conn = get_db_connection()
	cursor = conn.cursor()
	cursor.execute("DELETE FROM fines WHERE event_id=%s", (event_id,))
	conn.commit()
	conn.close()


def is_event_closed(event):
	if not event:
		return False

	date_value = event.get('date')
	if isinstance(date_value, str):
		try:
			date_value = datetime.strptime(date_value, "%Y-%m-%d").date()
		except Exception:
			return False
	if isinstance(date_value, datetime):
		date_value = date_value.date()
	if not isinstance(date_value, date):
		return False

	# Prefer logout cutoff/time when present
	logout_time = event.get('logout_cutoff_time') or event.get('logout_time')
	if logout_time:
		if isinstance(logout_time, timedelta):
			logout_time = (datetime.min + logout_time).time()
		elif isinstance(logout_time, str):
			parsed = None
			for fmt in ["%H:%M:%S", "%H:%M"]:
				try:
					parsed = datetime.strptime(logout_time, fmt).time()
					break
				except Exception:
					continue
			logout_time = parsed
		if logout_time:
			return datetime.combine(date_value, logout_time) < datetime.now()

	# If there's no logout window, and there's a login cutoff/time, treat login cutoff as the close
	login_close = event.get('login_cutoff_time') or event.get('login_time')
	if login_close and not (event.get('logout_cutoff_time') or event.get('logout_time')):
		if isinstance(login_close, timedelta):
			login_close = (datetime.min + login_close).time()
		elif isinstance(login_close, str):
			parsed = None
			for fmt in ["%H:%M:%S", "%H:%M"]:
				try:
					parsed = datetime.strptime(login_close, fmt).time()
					break
				except Exception:
					continue
			login_close = parsed
		if login_close:
			return datetime.combine(date_value, login_close) < datetime.now()

	# Fallback: end of day
	return datetime.combine(date_value, time(23, 59, 59)) < datetime.now()


def sync_fines_for_event(event):
	if not event or not event.get('id'):
		return
	if not is_event_closed(event):
		return

	students = student_model.get_all_students()
	attendance_records = attendance_model.get_attendance_by_event(event['id'])
	attendance_by_student = {}
	for record in attendance_records:
		attendance_by_student.setdefault(record['student_id'], []).append(record)

	has_login_window = bool(event.get('login_time') or event.get('login_cutoff_time'))
	has_logout_window = bool(event.get('logout_time') or event.get('logout_cutoff_time'))

	for student in students:
		student_id = student.get('student_id') or student.get('id')
		student_records = attendance_by_student.get(student.get('id'), [])
		login_record = next((r for r in student_records if r['status'] == 'login'), None)
		logout_record = next((r for r in student_records if r['status'] == 'logout'), None)

		# Single-window: login-only with special late-fee handling
		if has_login_window and not has_logout_window:
			if login_record:
				# Has login → Present (remove fines)
				remove_event_fine(student_id, event['id'])
			elif logout_record and not login_record:
				# Has logout but no login → Late (for one-time special events)
				create_or_update_fine(student_id, event['id'], 'Late', float(event.get('late_fine') or 0))
				remove_event_fine(student_id, event['id'], 'Absent')
			else:
				# No login and no logout → Absent
				create_or_update_fine(student_id, event['id'], 'Absent', float(event.get('absent_fine') or 0))
				remove_event_fine(student_id, event['id'], 'Late')
		elif has_logout_window and not has_login_window:
			if logout_record:
				remove_event_fine(student_id, event['id'])
			else:
				create_or_update_fine(student_id, event['id'], 'Absent', float(event.get('absent_fine') or 0))
		else:
			# Both windows present: keep existing semantics
			if logout_record and not login_record:
				create_or_update_fine(student_id, event['id'], 'Late', float(event.get('late_fine') or 0))
				remove_event_fine(student_id, event['id'], 'Absent')
			elif login_record and not logout_record:
				create_or_update_fine(student_id, event['id'], 'Absent', float(event.get('absent_fine') or 0))
				remove_event_fine(student_id, event['id'], 'Late')
			elif not login_record and not logout_record:
				create_or_update_fine(student_id, event['id'], 'Absent', float(event.get('absent_fine') or 0))
			else:
				remove_event_fine(student_id, event['id'])


def sync_all_closed_event_fines():
	for ev in get_all_events():
		sync_fines_for_event(ev)


def get_active_events():
	conn = get_db_connection()
	cursor = conn.cursor(dictionary=True)
	cursor.execute("""
		SELECT
			event_id AS id,
			event_name AS name,
			event_date AS date,
			absent_fine,
			late_fine,
			login_time,
			logout_time,
			login_cutoff_time,
			logout_cutoff_time,
			grace_period
		FROM events
		ORDER BY event_date DESC
	""")
	events = cursor.fetchall()
	conn.close()
	return events