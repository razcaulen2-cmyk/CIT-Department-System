import unittest
from unittest.mock import patch

from app_factory import create_app


class PaymentsCursor:
    def __init__(self, transactions=None):
        self.query = ""
        self.params = ()
        self.fetchall_count = 0
        self.transactions = transactions or []

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
        return self.transactions

    def close(self):
        pass


class PaymentsConnection:
    def __init__(self, transactions=None):
        self.test_cursor = PaymentsCursor(transactions)

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
        self.assertEqual(self.connection.test_cursor.params, ("%Gabriel%",) * 12)
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
            ("%Gabriel%",) * 12 + (
                "2026-2027",
                12,
                "2026-2027",
                "2nd Semester",
            ),
        )

    def test_combined_payment_modal_separates_account_amounts_and_payment_types(self):
        response = self.get_payments("/payments")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('value="Funds + Fines">Funds + Fines</option>', html)
        self.assertIn('id="fundsPaymentType"', html)
        self.assertIn('id="finesPaymentType"', html)
        self.assertIn('id="fundsAmount"', html)
        self.assertIn('id="finesAmount"', html)
        self.assertIn('data-receipt-field="transactionDetails"', html        )

    def test_adjustment_history_label_opens_remarks(self):
        self.connection = PaymentsConnection([{
            "id": 91,
            "student_id": "000123",
            "firstname": "Test",
            "lastname": "Student",
            "transaction_type": "Adjustment",
            "payment_type": "Funds",
            "amount": 20,
            "academic_year": "2026-2027",
            "semester": "2nd Semester",
            "transaction_date": None,
            "reversible": 0,
            "adjustment_direction": "Decrease",
            "adjustment_remarks": "Already paid before system launch.",
        }])
        response = self.get_payments("/payments")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('data-bs-target="#adjustmentRemarksModal"', html)
        self.assertIn('data-adjustment-remarks="Already paid before system launch."', html)
        self.assertIn("Funds", html)
        self.assertIn("Decrease", html)
        self.assertIn('id="adjustmentRemarksContent"', html)


if __name__ == "__main__":
    unittest.main()
