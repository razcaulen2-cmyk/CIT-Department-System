import unittest
from unittest.mock import patch

from app_factory import create_app


class SemesterCursor:
    def execute(self, query):
        self.query = query

    def fetchall(self):
        return [
            {
                "id": 7,
                "academic_year": "2026-2027",
                "semester": "1st Semester",
                "fund_amount": 75,
                "is_active": True,
            },
            {
                "id": 6,
                "academic_year": "2025-2026",
                "semester": "2nd Semester",
                "fund_amount": 60,
                "is_active": False,
            },
        ]

    def close(self):
        pass


class SemesterConnection:
    def cursor(self, dictionary=False):
        return SemesterCursor()

    def close(self):
        pass


class EventsSemesterFilterTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session["admin"] = True

        self.events = [
            {
                "id": 10,
                "name": "Active semester event",
                "semester_id": 7,
                "academic_year": "2026-2027",
                "semester_name": "1st Semester",
            },
            {
                "id": 9,
                "name": "Past semester event",
                "semester_id": 6,
                "academic_year": "2025-2026",
                "semester_name": "2nd Semester",
            },
        ]

    def get_events_page(self, path):
        with patch("routes.events.get_db_connection", return_value=SemesterConnection()):
            with patch("routes.events.event_model.get_all_events", return_value=self.events):
                return self.client.get(path)

    def test_events_page_defaults_to_active_semester(self):
        response = self.get_events_page("/events")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Active semester event", html)
        self.assertNotIn("Past semester event", html)

    def test_events_page_can_filter_to_a_past_semester(self):
        response = self.get_events_page("/events?semester_id=6")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Past semester event", html)
        self.assertNotIn("Active semester event", html)


if __name__ == "__main__":
    unittest.main()
