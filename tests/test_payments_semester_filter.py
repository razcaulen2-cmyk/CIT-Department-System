import unittest
from unittest.mock import patch

from app_factory import create_app


class PaymentsCursor:
    def __init__(self):
        self.query = ""
        self.params = ()
        self.fetchall_count = 0

    def execute(self, query, params=None):
        self.query = query
        self.params = params or ()

    def fetchall(self):
        self.fetchall_count += 1
        if self.fetchall_count == 1:
            return [
                {"id": 11, "academic_year": "2026-2027", "semester": "1st Semester"},
                {"id": 12, "academic_year": "2026-2027", "semester": "2nd Semester"},
                {"id": 13, "academic_year": "2025-2026", "semester": "Summer Class"},
            ]
        return []

    def close(self):
        pass


class PaymentsConnection:
    def __init__(self):
        self.test_cursor = PaymentsCursor()

    def cursor(self, dictionary=False):
        return self.test_cursor

    def close(self):
        pass


class PaymentsSemesterFilterTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session["admin"] = True
        self.connection = PaymentsConnection()

    def get_payments(self, path):
        with patch("routes.admin.get_db_connection", return_value=self.connection):
            with patch("routes.admin.ensure_transaction_balance_snapshots"):
                return self.client.get(path)

    def test_transactions_filter_by_academic_year_and_semester(self):
        response = self.get_payments(
            "/payments?academic_year=2026-2027&semester_id=12"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("t.academic_year=%s", self.connection.test_cursor.query)
        self.assertIn("t.semester_id=%s", self.connection.test_cursor.query)
        self.assertEqual(
            self.connection.test_cursor.params,
            ("2026-2027", 12, "2026-2027", "2nd Semester"),
        )

    def test_invalid_semester_is_ignored_and_year_filter_is_kept(self):
        response = self.get_payments(
            "/payments?academic_year=2026-2027&semester_id=13"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("t.academic_year=%s", self.connection.test_cursor.query)
        self.assertNotIn("t.semester_id=%s", self.connection.test_cursor.query)
        self.assertEqual(self.connection.test_cursor.params, ("2026-2027",))

    def test_transactions_search_matches_transaction_details(self):
        response = self.get_payments("/payments?search=Gabriel")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'id="transactionSearch"', response.data)
        self.assertIn(b'value="Gabriel"', response.data)
        self.assertIn("CONCAT(s.firstname, ' ', s.lastname) LIKE %s", self.connection.test_cursor.query)
        self.assertIn("t.payment_type LIKE %s", self.connection.test_cursor.query)
        self.assertIn("CAST(t.amount AS CHAR) LIKE %s", self.connection.test_cursor.query)
        self.assertEqual(self.connection.test_cursor.params, ("%Gabriel%",) * 11)
        self.assertLess(
            self.connection.test_cursor.query.index("CONCAT(s.firstname"),
            self.connection.test_cursor.query.index("LIMIT 50"),
        )

    def test_transactions_search_combines_with_existing_filters(self):
        response = self.get_payments(
            "/payments?search=Gabriel&academic_year=2026-2027&semester_id=12"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("t.academic_year=%s", self.connection.test_cursor.query)
        self.assertIn("t.semester_id=%s", self.connection.test_cursor.query)
        self.assertEqual(
            self.connection.test_cursor.params,
            ("%Gabriel%",) * 11 + (
                "2026-2027",
                12,
                "2026-2027",
                "2nd Semester",
            ),
        )


if __name__ == "__main__":
    unittest.main()
