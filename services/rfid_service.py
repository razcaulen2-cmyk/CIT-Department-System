"""
RFID Utility Functions

This file will later contain:

• RFID validation
• RFID mapping
• RFID attendance
• RFID login
"""
from models import student_model, attendance_model
from datetime import datetime


def process_rfid_tap(rfid_uid, event_id):
	student = student_model.get_student_by_rfid(rfid_uid)
	if not student:
		return None

	timestamp = datetime.now()
	status = 'present'
	attendance_model.record_attendance(event_id, student['id'], status, timestamp)

	return {
		'student': student,
		'status': status,
		'timestamp': timestamp
	}