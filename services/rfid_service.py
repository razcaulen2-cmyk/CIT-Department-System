"""
RFID Utility Functions

This file will later contain:

• RFID validation
• RFID mapping
• RFID attendance
• RFID login
"""
from models import event_model, semester_model, student_model, attendance_model
from datetime import datetime


def process_rfid_tap(rfid_uid, event_id):
	student = student_model.get_student_by_rfid(rfid_uid)
	if not student:
		return None
	event = event_model.get_event(event_id)
	if not event or not semester_model.is_student_enrolled_in_semester(
		event.get('semester_id'),
		student['id'],
	):
		return None

	timestamp = datetime.now()
	status = 'present'
	attendance_model.record_attendance(event_id, student['id'], status, timestamp)

	return {
		'student': student,
		'status': status,
		'timestamp': timestamp
	}