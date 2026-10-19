import json

from config import get_db_connection
from models import attendance_model, semester_model, student_model
from datetime import datetime, date, timedelta, time
from decimal import Decimal


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
	if 'semester_id' not in existing_columns:
		alter_clauses.append('ADD COLUMN semester_id INT NULL')

	if alter_clauses:
		cursor.execute(f"ALTER TABLE events {', '.join(alter_clauses)}")
		conn.commit()

	conn.close()


def ensure_fine_assessment_column():
	conn = get_db_connection()
	cursor = conn.cursor()
	cursor.execute(
		"""
		SELECT COLUMN_NAME
		FROM INFORMATION_SCHEMA.COLUMNS
		WHERE TABLE_SCHEMA = DATABASE()
		  AND TABLE_NAME = 'fines'
		"""
	)
	existing_columns = {row[0] for row in cursor.fetchall()}
	if 'assessed_amount' not in existing_columns:
		cursor.execute(
			"ALTER TABLE fines ADD COLUMN assessed_amount DECIMAL(10,2) NULL"
		)
		cursor.execute(
			"UPDATE fines SET assessed_amount = amount WHERE assessed_amount IS NULL"
		)
		conn.commit()
	cursor.close()
	conn.close()


def ensure_fine_payment_allocations():
	conn = get_db_connection()
	cursor = conn.cursor(dictionary=True)
	cursor.execute(
		"""
		SELECT COUNT(*) AS table_count
		FROM INFORMATION_SCHEMA.TABLES
		WHERE TABLE_SCHEMA = DATABASE()
		  AND TABLE_NAME = 'fine_payment_allocations'
		"""
	)
	table_exists = cursor.fetchone()['table_count'] > 0
	if not table_exists:
		cursor.execute(
			"""
			CREATE TABLE IF NOT EXISTS fine_payment_allocations (
				allocation_id INT AUTO_INCREMENT PRIMARY KEY,
				transaction_id INT NOT NULL,
				source_fine_id INT NOT NULL,
				student_id VARCHAR(32) NOT NULL,
				event_id INT NOT NULL,
				fine_type VARCHAR(50) NOT NULL,
				amount_paid DECIMAL(10,2) NOT NULL,
				UNIQUE KEY uq_fine_payment_source (transaction_id, source_fine_id),
				INDEX idx_fine_payment_identity (student_id, event_id, fine_type)
			)
			"""
		)
		cursor.execute(
			"""
			SELECT COUNT(*) AS table_count
			FROM INFORMATION_SCHEMA.TABLES
			WHERE TABLE_SCHEMA = DATABASE()
			  AND TABLE_NAME = 'transaction_balance_snapshots'
			"""
		)
		if cursor.fetchone()['table_count']:
			cursor.execute(
				"""
				SELECT t.id, t.student_id, snapshot.snapshot
				FROM transactions t
				JOIN transaction_balance_snapshots snapshot
					ON snapshot.transaction_id = t.id
				WHERE t.transaction_type = 'Fines'
				ORDER BY t.id
				"""
			)
			for transaction in cursor.fetchall():
				snapshot_rows = transaction['snapshot']
				if isinstance(snapshot_rows, str):
					snapshot_rows = json.loads(snapshot_rows)
				for item in snapshot_rows:
					amount_paid = (
						Decimal(str(item['before'])) - Decimal(str(item['after']))
					)
					if amount_paid <= 0:
						continue
					cursor.execute(
						"""
						SELECT event_id, fine_type
						FROM fines
						WHERE fine_id = %s AND student_id = %s
						""",
						(item['row_id'], transaction['student_id']),
					)
					fine = cursor.fetchone()
					if not fine:
						continue
					cursor.execute(
						"""
						INSERT IGNORE INTO fine_payment_allocations
							(transaction_id, source_fine_id, student_id, event_id, fine_type, amount_paid)
						VALUES (%s, %s, %s, %s, %s, %s)
						""",
						(
							transaction['id'],
							item['row_id'],
							transaction['student_id'],
							fine['event_id'],
							fine['fine_type'],
							amount_paid,
						),
					)
	conn.commit()
	cursor.close()
	conn.close()


def ensure_exemption_tables():
	conn = get_db_connection()
	cursor = conn.cursor()
	cursor.execute(
		"""
		CREATE TABLE IF NOT EXISTS exemption_lists (
			id INT AUTO_INCREMENT PRIMARY KEY,
			name VARCHAR(120) NOT NULL,
			year_level VARCHAR(32) NULL,
			created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
		)
		"""
	)
	cursor.execute(
		"""
		CREATE TABLE IF NOT EXISTS exemption_list_students (
			list_id INT NOT NULL,
			student_id INT NOT NULL,
			PRIMARY KEY (list_id, student_id),
			INDEX (student_id)
		)
		"""
	)
	cursor.execute(
		"""
		CREATE TABLE IF NOT EXISTS event_exemptions (
			event_id INT NOT NULL,
			student_id INT NOT NULL,
			PRIMARY KEY (event_id, student_id),
			INDEX (student_id)
		)
		"""
	)
	conn.commit()
	conn.close()


def ensure_paper_attendance_table():
	conn = get_db_connection()
	cursor = conn.cursor()
	cursor.execute(
		"""
		CREATE TABLE IF NOT EXISTS paper_attendance (
			event_id INT NOT NULL,
			semester_id INT NULL,
			student_id INT NOT NULL,
			status VARCHAR(16) NOT NULL,
			recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
			PRIMARY KEY (event_id, student_id),
			INDEX (student_id),
			INDEX idx_paper_attendance_semester (semester_id)
		)
		"""
	)
	conn.commit()
	conn.close()


def get_paper_attendance_for_event(event_id):
	ensure_paper_attendance_table()
	conn = get_db_connection()
	cursor = conn.cursor(dictionary=True)
	cursor.execute(
		"SELECT student_id, status FROM paper_attendance WHERE event_id=%s",
		(event_id,),
	)
	overrides = {row['student_id']: row['status'] for row in cursor.fetchall()}
	conn.close()
	return overrides


def get_paper_attendance_for_student(student_id):
	ensure_paper_attendance_table()
	conn = get_db_connection()
	cursor = conn.cursor(dictionary=True)
	cursor.execute(
		"SELECT event_id, status FROM paper_attendance WHERE student_id=%s",
		(student_id,),
	)
	overrides = {row['event_id']: row['status'] for row in cursor.fetchall()}
	conn.close()
	return overrides


def save_paper_attendance(event_id, student_id, status):
	ensure_paper_attendance_table()
	if status not in ('present', 'late'):
		raise ValueError('Paper attendance status must be present or late')
	conn = get_db_connection()
	cursor = conn.cursor()
	cursor.execute(
		"""
		INSERT INTO paper_attendance (event_id, semester_id, student_id, status)
		SELECT event_id, semester_id, %s, %s
		FROM events
		WHERE event_id=%s
		ON DUPLICATE KEY UPDATE status=VALUES(status)
		""",
		(student_id, status, event_id),
	)
	conn.commit()
	conn.close()


def clear_paper_attendance(event_id, student_id):
	ensure_paper_attendance_table()
	conn = get_db_connection()
	cursor = conn.cursor()
	cursor.execute(
		"DELETE FROM paper_attendance WHERE event_id=%s AND student_id=%s",
		(event_id, student_id),
	)
	conn.commit()
	conn.close()


def get_exemption_lists():
	ensure_exemption_tables()
	conn = get_db_connection()
	cursor = conn.cursor(dictionary=True)
	cursor.execute(
		"""
		SELECT l.id, l.name, l.year_level,
		       COUNT(ls.student_id) AS student_count
		FROM exemption_lists l
		LEFT JOIN exemption_list_students ls ON ls.list_id = l.id
		GROUP BY l.id, l.name, l.year_level
		ORDER BY l.name
		"""
	)
	lists = cursor.fetchall()
	conn.close()
	return lists


def create_exemption_list(name, student_ids=None, year_level=None):
	ensure_exemption_tables()
	student_ids = sorted({int(student_id) for student_id in (student_ids or [])})
	conn = get_db_connection()
	cursor = conn.cursor()
	cursor.execute(
		"INSERT INTO exemption_lists (name, year_level) VALUES (%s, %s)",
		(name.strip(), year_level or None),
	)
	list_id = cursor.lastrowid
	if student_ids:
		cursor.executemany(
			"INSERT INTO exemption_list_students (list_id, student_id) VALUES (%s, %s)",
			[(list_id, student_id) for student_id in student_ids],
		)
	conn.commit()
	conn.close()
	return list_id


def get_exemption_list(list_id):
	ensure_exemption_tables()
	conn = get_db_connection()
	cursor = conn.cursor(dictionary=True)
	cursor.execute(
		"SELECT id, name, year_level FROM exemption_lists WHERE id=%s",
		(list_id,),
	)
	exemption_list = cursor.fetchone()
	if exemption_list:
		cursor.execute(
			"SELECT student_id FROM exemption_list_students WHERE list_id=%s",
			(list_id,),
		)
		exemption_list['student_ids'] = [row['student_id'] for row in cursor.fetchall()]
	cursor.close()
	conn.close()
	return exemption_list


def update_exemption_list(list_id, name, student_ids=None, year_level=None):
	ensure_exemption_tables()
	student_ids = sorted({int(student_id) for student_id in (student_ids or [])})
	conn = get_db_connection()
	cursor = conn.cursor()
	cursor.execute(
		"UPDATE exemption_lists SET name=%s, year_level=%s WHERE id=%s",
		(name.strip(), year_level or None, list_id),
	)
	cursor.execute("DELETE FROM exemption_list_students WHERE list_id=%s", (list_id,))
	if student_ids:
		cursor.executemany(
			"INSERT INTO exemption_list_students (list_id, student_id) VALUES (%s, %s)",
			[(list_id, student_id) for student_id in student_ids],
		)
	conn.commit()
	updated = cursor.rowcount >= 0
	cursor.close()
	conn.close()
	return updated


def get_event_exemption_ids(event_id):
	ensure_exemption_tables()
	conn = get_db_connection()
	cursor = conn.cursor()
	cursor.execute("SELECT student_id FROM event_exemptions WHERE event_id=%s", (event_id,))
	student_ids = {row[0] for row in cursor.fetchall()}
	conn.close()
	return student_ids


def get_exempted_event_ids_for_student(student_id):
	ensure_exemption_tables()
	conn = get_db_connection()
	cursor = conn.cursor()
	cursor.execute(
		"SELECT event_id FROM event_exemptions WHERE student_id=%s",
		(student_id,),
	)
	event_ids = {row[0] for row in cursor.fetchall()}
	conn.close()
	return event_ids


def get_exemption_list_student_ids(list_ids):
	ensure_exemption_tables()
	list_ids = sorted({int(list_id) for list_id in (list_ids or [])})
	if not list_ids:
		return set()
	conn = get_db_connection()
	cursor = conn.cursor()
	placeholders = ','.join(['%s'] * len(list_ids))
	cursor.execute(
		f"SELECT student_id FROM exemption_list_students WHERE list_id IN ({placeholders})",
		tuple(list_ids),
	)
	student_ids = {row[0] for row in cursor.fetchall()}
	cursor.execute(
		f"""
		SELECT s.id
		FROM students s
		JOIN exemption_lists l ON l.year_level IS NOT NULL
		WHERE l.id IN ({placeholders}) AND CAST(s.year_level AS CHAR) = l.year_level
		""",
		tuple(list_ids),
	)
	student_ids.update(row[0] for row in cursor.fetchall())
	conn.close()
	return student_ids


def save_event_exemptions(event_id, student_ids):
	ensure_exemption_tables()
	student_ids = sorted({int(student_id) for student_id in (student_ids or [])})
	conn = get_db_connection()
	cursor = conn.cursor()
	cursor.execute("DELETE FROM event_exemptions WHERE event_id=%s", (event_id,))
	if student_ids:
		cursor.executemany(
			"INSERT INTO event_exemptions (event_id, student_id) VALUES (%s, %s)",
			[(event_id, student_id) for student_id in student_ids],
		)
	conn.commit()
	conn.close()


def remove_event_exemption(event_id, student_id):
	ensure_exemption_tables()
	conn = get_db_connection()
	cursor = conn.cursor()
	cursor.execute(
		"DELETE FROM event_exemptions WHERE event_id=%s AND student_id=%s",
		(event_id, student_id),
	)
	removed = cursor.rowcount > 0
	conn.commit()
	cursor.close()
	conn.close()
	return removed


def get_all_events():
	ensure_event_columns()
	conn = get_db_connection()
	cursor = conn.cursor(dictionary=True)
	cursor.execute("""
		SELECT
			event_id AS id,
			semester_id,
			event_name AS name,
			(SELECT academic_year FROM school_terms WHERE id=events.semester_id) AS academic_year,
			(SELECT semester FROM school_terms WHERE id=events.semester_id) AS semester_name,
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
		"SELECT id FROM school_terms WHERE is_active=TRUE ORDER BY id DESC LIMIT 1"
	)
	active_term = cursor.fetchone()
	if not active_term:
		cursor.close()
		conn.close()
		raise ValueError('Create or activate a semester before creating events.')
	cursor.execute(
		"""
		INSERT INTO events
			(semester_id, event_name, event_date, absent_fine, late_fine, login_time, logout_time, login_cutoff_time, logout_cutoff_time, grace_period)
		VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
		""",
		(
			active_term[0],
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
			semester_id,
			event_name AS name,
			(SELECT academic_year FROM school_terms WHERE id=events.semester_id) AS academic_year,
			(SELECT semester FROM school_terms WHERE id=events.semester_id) AS semester_name,
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
	ensure_exemption_tables()
	ensure_paper_attendance_table()
	conn = get_db_connection()
	cursor = conn.cursor()
	cursor.execute("DELETE FROM event_exemptions WHERE event_id=%s", (event_id,))
	cursor.execute("DELETE FROM paper_attendance WHERE event_id=%s", (event_id,))
	cursor.execute("DELETE FROM fines WHERE event_id=%s", (event_id,))
	cursor.execute("DELETE FROM attendance WHERE event_id=%s", (event_id,))
	cursor.execute("DELETE FROM events WHERE event_id=%s", (event_id,))
	conn.commit()
	conn.close()


def create_or_update_fine(student_id, event_id, fine_type, amount):
	conn = get_db_connection()
	cursor = conn.cursor()
	cursor.execute(
		"""
		SELECT fine_id, amount, assessed_amount
		FROM fines
		WHERE student_id=%s AND event_id=%s AND fine_type=%s
		LIMIT 1
		FOR UPDATE
		""",
		(student_id, event_id, fine_type),
	)
	fine = cursor.fetchone()
	assessed_amount = Decimal(str(amount)).quantize(Decimal('0.01'))
	cursor.execute(
		"""
		SELECT COALESCE(SUM(amount_paid), 0)
		FROM fine_payment_allocations
		WHERE student_id=%s AND event_id=%s AND fine_type=%s
		""",
		(student_id, event_id, fine_type),
	)
	allocated_paid = Decimal(str(cursor.fetchone()[0] or 0))
	if fine:
		previous_assessed = Decimal(
			str(fine[2] if fine[2] is not None else fine[1] or 0)
		)
		previous_due = Decimal(str(fine[1] or 0))
		previously_paid = max(
			previous_assessed - previous_due,
			Decimal('0.00'),
		)
		amount_due = max(
			assessed_amount - max(allocated_paid, previously_paid),
			Decimal('0.00'),
		)
		cursor.execute(
			"""
			UPDATE fines
			SET amount=%s, assessed_amount=%s,
			    semester_id=(SELECT semester_id FROM events WHERE event_id=%s)
			WHERE fine_id=%s
			""",
			(amount_due, assessed_amount, event_id, fine[0]),
		)
	else:
		amount_due = max(assessed_amount - allocated_paid, Decimal('0.00'))
		cursor.execute(
			"""
			INSERT INTO fines
				(student_id, semester_id, event_id, fine_type, amount, assessed_amount)
			SELECT %s, semester_id, %s, %s, %s, %s
			FROM events
			WHERE event_id=%s
			""",
			(student_id, event_id, fine_type, amount_due, assessed_amount, event_id),
		)
	conn.commit()
	cursor.close()
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


def remove_fines_for_student_record(student, event_id):
	student_ids = {
		student.get('id'),
		student.get('student_id'),
	}
	for student_id in student_ids:
		if student_id is not None:
			remove_event_fine(student_id, event_id)


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

	enrolled_student_ids = semester_model.get_enrolled_student_ids(event.get('semester_id'))
	if not enrolled_student_ids:
		return

	ensure_fine_assessment_column()
	ensure_fine_payment_allocations()
	students = [
		student for student in student_model.get_all_students()
		if student.get('id') in enrolled_student_ids
	]
	exempted_student_ids = get_event_exemption_ids(event['id'])
	paper_attendance = get_paper_attendance_for_event(event['id'])
	if not is_event_closed(event):
		for student in students:
			if student.get('id') in exempted_student_ids:
				remove_fines_for_student_record(student, event['id'])
			elif student.get('id') in paper_attendance:
				remove_fines_for_student_record(student, event['id'])
				if paper_attendance[student['id']] == 'late':
					create_or_update_fine(student.get('student_id') or student.get('id'), event['id'], 'Late', float(event.get('late_fine') or 0))
		return

	attendance_records = attendance_model.get_attendance_by_event(event['id'])
	attendance_by_student = {}
	for record in attendance_records:
		attendance_by_student.setdefault(record['student_id'], []).append(record)

	has_login_window = bool(event.get('login_time') or event.get('login_cutoff_time'))
	has_logout_window = bool(event.get('logout_time') or event.get('logout_cutoff_time'))

	for student in students:
		student_id = student.get('student_id') or student.get('id')
		if student.get('id') in exempted_student_ids:
			remove_fines_for_student_record(student, event['id'])
			continue
		if student.get('id') in paper_attendance:
			remove_fines_for_student_record(student, event['id'])
			if paper_attendance[student['id']] == 'late':
				create_or_update_fine(student_id, event['id'], 'Late', float(event.get('late_fine') or 0))
			continue
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
			semester_id,
			event_name AS name,
			(SELECT academic_year FROM school_terms WHERE id=events.semester_id) AS academic_year,
			(SELECT semester FROM school_terms WHERE id=events.semester_id) AS semester_name,
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