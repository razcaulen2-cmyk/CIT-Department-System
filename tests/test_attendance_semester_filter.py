import unittest
from unittest.mock import patch

from app_factory import create_app


class TermsCursor:
    def execute(self, query):
        self.query = query

    def fetchall(self):
        return [
            {"academic_year": "2026-2027", "semester": "1st Semester"},
            {"academic_year": "2026-2027", "semester": "2nd Semester"},
            {"academic_year": "2026-2027", "semester": "Summer"},
            {"academic_year": "2027-2028", "semester": "1st Semester"},
        ]

    def close(self):
        pass


class TermsConnection:
    def cursor(self, dictionary=False):
        return TermsCursor()

    def close(self):
        pass


class AttendanceSemesterFilterTests(unittest.TestCase):
    def test_attendance_filter_uses_semester_linked_to_selected_academic_year(self):
        app = create_app()
        client = app.test_client()
        events = [
            {
                "id": 1,
                "name": "First semester event",
                "date": "2027-02-10",
                "academic_year": "2026-2027",
                "semester_name": "1st Semester",
            },
            {
                "id": 2,
                "name": "Second semester event",
                "date": "2026-08-10",
                "academic_year": "2026-2027",
                "semester_name": "2nd Semester",
            },
            {
                "id": 3,
                "name": "Other year event",
                "date": "2026-08-12",
                "academic_year": "2027-2028",
                "semester_name": "1st Semester",
            },
        ]

        with client.session_transaction() as session:
            session["admin"] = True
        with patch("routes.events.student_model.get_all_students", return_value=[]):
            with patch("routes.events.event_model.get_all_events", return_value=events):
                with patch("routes.events.get_db_connection", return_value=TermsConnection()):
                    response = client.get(
                        "/attendance?academic_year=2026-2027&semester=2nd%20Semester"
                    )

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Second semester event", html)
        self.assertNotIn("First semester event", html)
        self.assertNotIn("Other year event", html)


if __name__ == "__main__":
    unittest.main()
