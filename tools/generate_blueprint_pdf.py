from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem
from reportlab.lib.units import inch
from reportlab.lib import colors

file_path = r"c:\Users\razca\Documents\Programs & Systems\Department Fines Tracker\system_blueprint.pdf"
styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name='CustomHeading1', parent=styles['Heading1'], fontSize=18, spaceAfter=12))
styles.add(ParagraphStyle(name='CustomHeading2', parent=styles['Heading2'], fontSize=14, spaceAfter=8))
styles.add(ParagraphStyle(name='CustomBodyText', parent=styles['BodyText'], fontSize=10, leading=14))

content = []
content.append(Paragraph('Department Fines Tracker - System Blueprint', styles['CustomHeading1']))
content.append(Paragraph('Generated from application code structure and route definitions.', styles['CustomBodyText']))
content.append(Spacer(1, 0.2*inch))

sections = [
    ('Application Overview', [
        'Flask web application using multiple blueprints for modular routing.',
        'MySQL database connection via mysql.connector and shared get_db_connection in config.py.',
        'Application factory defined in app_factory.py and started in app.py.',
        'Sessions are stored in secure cookies with HTTPOnly and SameSite=Lax settings.',
    ]),
    ('Blueprints and Routes', [
        'admin: Admin dashboard, student management, RFID mapping, academic terms, finance, payments, CSV upload, API endpoints for student balance and payment processing.',
        'auth: Admin login, student login, logout, RFID verification, debug last scan API.',
        'events: Event management, attendance pages, attendance reporting PDF/Excel export, RFID attendance recording.',
        'student: Student dashboard page with active term and academic year context.',
        'payments: Registered blueprint with no route handlers in payments.py.',
        'api: Registered blueprint with no routes defined in api.py.',
    ]),
    ('Database Model Files', [
        'student_model.py: CRUD operations for students and RFID lookup.',
        'event_model.py: Event CRUD, fine sync and event metadata management.',
        'attendance_model.py: Attendance recording, lookup, and reporting support.',
        'payment_model.py: Empty placeholder currently.',
    ]),
    ('Service Files', [
        'csv_service.py: Placeholder for future CSV import handling.',
        'payment_service.py: Placeholder for future payment validation and receipt generation.',
        'rfid_service.py: RFID tap processing utility that records attendance.',
    ]),
    ('Template Structure', [
        'admin/: Admin interface templates for dashboard, students, attendance, events, finance, payments, academic terms, login, file upload, and student management.',
        'student/: Student dashboard and login pages.',
        'public/: Public home page.',
        'fragments/: Partial HTML fragments for AJAX modal logins.',
        'layout/: Base layout templates for admin, student, and public sections.',
    ]),
    ('Database Tables Referenced', [
        'students, admins, student_funds, fines, transactions, school_terms, system_settings, events, attendance',
    ]),
    ('Key Features and Behavior', [
        'Admin users manage students, academic terms, events, finance, fines, and payments.',
        'Students log in with RFID or ID and view a student dashboard.',
        'Events support login/logout attendance windows with optional grace periods and fine sync.',
        'Attendance reports can be exported as PDF or Excel.',
        'Admin-facing finance page aggregates funds and fines, and payment transactions update balances.',
    ]),
]

for heading, items in sections:
    content.append(Paragraph(heading, styles['CustomHeading2']))
    content.append(ListFlowable([ListItem(Paragraph(item, styles['CustomBodyText']), bulletColor=colors.black) for item in items], bulletType='bullet'))
    content.append(Spacer(1, 0.15*inch))

content.append(Paragraph('Route Summary', styles['CustomHeading2']))
route_blocks = [
    ('Admin routes', [
        '/admin-dashboard (GET)',
        '/students (GET)',
        '/add-student (GET, POST)',
        '/delete-student/<id> (GET, POST)',
        '/edit-student/<id> (GET, POST)',
        '/map-rfid/<int:id> (GET, POST)',
        '/academic-terms (GET)',
        '/add-academic-term (GET, POST)',
        '/edit-academic-term/<id> (GET, POST)',
        '/delete-academic-term/<id> (GET, POST)',
        '/finance (GET)',
        '/api/student-balance/<student_id> (GET)',
        '/payments (GET)',
        '/upload-csv (GET, POST)',
        '/api/process-payment (POST)',
    ]),
    ('Auth routes', [
        '/student-login (GET, POST)',
        '/admin-login (GET, POST)',
        '/logout (GET)',
        '/student-logout (GET)',
        '/verify-rfid (POST)',
        '/debug-last-scan (GET)',
    ]),
    ('Events routes', [
        '/events (GET)',
        '/events/create (POST)',
        '/events/<int:event_id>/edit (POST)',
        '/events/<int:event_id>/delete (POST)',
        '/events/<int:event_id>/conduct (GET)',
        '/attendance (GET)',
        '/attendance/report (GET)',
        '/events/record_rfid (POST)',
    ]),
    ('Student routes', [
        '/student-dashboard (GET)',
    ]),
    ('Public route', [
        '/ (GET)',
    ]),
]
for heading, items in route_blocks:
    content.append(Paragraph(heading, styles['CustomBodyText']))
    content.append(ListFlowable([ListItem(Paragraph(item, styles['CustomBodyText']), bulletColor=colors.black) for item in items], bulletType='bullet'))
    content.append(Spacer(1, 0.12*inch))

SimpleDocTemplate(file_path, pagesize=letter, leftMargin=0.5*inch, rightMargin=0.5*inch, topMargin=0.5*inch, bottomMargin=0.5*inch).build(content)
print(f'Created {file_path}')
