import unittest
from decimal import Decimal
from unittest.mock import patch

from app_factory import create_app


class AcademicYearCursor:
    def __init__(self, existing_year=False):
        self.existing_year = existing_year
        self.executions = []
        self.closed = False

    def execute(self, query, params=None):
        self.executions.append((query, params))

    def fetchone(self):
        return (1,) if self.existing_year else None

    def close(self):
        self.closed = True


class AcademicYearConnection:
    def __init__(self, existing_year=False):
        self.test_cursor = AcademicYearCursor(existing_year)
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self):
        return self.test_cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


class AcademicYearCreationTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session["admin"] = True

    @staticmethod
    def form_data(**overrides):
        form = {
            "academic_year": "2027-2028",
            "first_start_date": "2027-08-01",
            "first_end_date": "2027-12-15",
            "first_fund_amount": "75.00",
            "second_start_date": "2028-01-10",
            "second_end_date": "2028-05-20",
            "second_fund_amount": "90.00",
            "summer_start_date": "2028-06-01",
            "summer_end_date": "2028-07-15",
            "summer_fund_amount": "50.00",
        }
        form.update(overrides)
        return form

    def test_creation_inserts_three_semesters_and_activates_only_selected(self):
        connection = AcademicYearConnection()
        with patch("routes.admin.get_db_connection", return_value=connection):
            response = self.client.post(
                "/add-academic-term",
                data=self.form_data(is_active="on", active_semester="2nd Semester"),
            )

        inserts = [
            params
            for query, params in connection.test_cursor.executions
            if "INSERT INTO school_terms" in query
        ]
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(inserts), 3)
        self.assertEqual([values[1] for values in inserts], [
            "1st Semester",
            "2nd Semester",
            "Summer Class",
        ])
        self.assertEqual([values[4] for values in inserts], [
            Decimal("75.00"),
            Decimal("90.00"),
            Decimal("50.00"),
        ])
        self.assertEqual([values[5] for values in inserts], [False, True, False])
        self.assertTrue(connection.committed)
        self.assertTrue(connection.closed)

    def test_active_year_requires_a_semester_choice(self):
        with patch("routes.admin.get_db_connection") as get_connection:
            response = self.client.post(
                "/add-academic-term",
                data=self.form_data(is_active="on"),
            )

        self.assertEqual(response.status_code, 302)
        get_connection.assert_not_called()

    def test_existing_academic_year_is_not_duplicated(self):
        connection = AcademicYearConnection(existing_year=True)
        with patch("routes.admin.get_db_connection", return_value=connection):
            response = self.client.post(
                "/add-academic-term",
                data=self.form_data(),
            )

        inserts = [
            query for query, _ in connection.test_cursor.executions
            if "INSERT INTO school_terms" in query
        ]
        self.assertEqual(response.status_code, 302)
        self.assertEqual(inserts, [])
        self.assertFalse(connection.committed)
        self.assertTrue(connection.closed)


if __name__ == "__main__":
    unittest.main()
