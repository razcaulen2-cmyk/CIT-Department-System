import unittest
from datetime import datetime
from decimal import Decimal
from unittest.mock import patch

from app_factory import create_app
from models import event_model


class FakePaymentCursor:
    def __init__(self, fail_fines=False):
        self.fail_fines = fail_fines
        self.queries = []
        self.lastrowid = 0

    def execute(self, query, params=None):
        self.queries.append((query, params))
        if "INSERT INTO transactions" in query:
            self.lastrowid += 1

    def fetchone(self):
        query = self.queries[-1][0]
        if "FROM students WHERE student_id" in query:
            return {
                "id": 1,
                "student_id": "000123",
                "firstname": "Test",
                "lastname": "Student",
            }
        if "FROM school_terms" in query:
            return {"id": 7, "academic_year": "2026-2027", "semester": "2nd Semester"}
        if "SELECT transaction_date" in query:
            return {"transaction_date": datetime(2026, 11, 4, 10, 30)}
        return None

    def fetchall(self):
        query = self.queries[-1][0]
        if "FROM student_funds" in query:
            return [{"id": 11, "amount_due": Decimal("100.00"), "paid_amount": Decimal("0.00")}]
        if "FROM fines" in query:
            amount = Decimal("10.00") if self.fail_fines else Decimal("25.00")
            return [{
                "fine_id": 22,
                "event_id": 3,
                "fine_type": "Absent",
                "amount": amount,
            }]
        return []

    def close(self):
        pass


class FakePaymentConnection:
    def __init__(self, cursor):
        self.payment_cursor = cursor
        self.committed = False
        self.rolled_back = False
        self.closed = False
        self.transaction_started = False

    def cursor(self, dictionary=False):
        return self.payment_cursor

    def start_transaction(self):
        self.transaction_started = True

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


class CombinedPaymentTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session["admin"] = True

    def post_combined_payment(self, cursor, funds_amount="40.00", fines_amount="25.00"):
        connection = FakePaymentConnection(cursor)
        payload = {
            "student_id": "000123",
            "transaction_type": "Funds + Fines",
            "semester_id": 7,
            "components": [
                {"transaction_type": "Funds", "payment_type": "Partial", "amount": funds_amount},
                {"transaction_type": "Fines", "payment_type": "Full", "amount": fines_amount},
            ],
        }
        with patch("routes.admin.get_db_connection", return_value=connection):
            with patch.object(event_model, "ensure_fine_assessment_column"):
                with patch.object(event_model, "ensure_fine_payment_allocations"):
                    response = self.client.post("/api/process-payment", json=payload)
        return response, connection

    def test_combined_payment_records_both_accounts_and_snapshots_atomically(self):
        cursor = FakePaymentCursor()
        response, connection = self.post_combined_payment(cursor)

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(
            [(item["transaction_type"], item["payment_type"], item["amount"]) for item in payload["transactions"]],
            [("Funds", "Partial", "40.00"), ("Fines", "Full", "25.00")],
        )
        self.assertEqual(payload["transaction_no"], payload["transactions"][0]["transaction_no"])
        transaction_inserts = [
            params for query, params in cursor.queries if "INSERT INTO transactions" in query
        ]
        self.assertEqual([params[2] for params in transaction_inserts], ["Funds", "Fines"])
        self.assertEqual(
            sum("INSERT INTO transaction_balance_snapshots" in query for query, _ in cursor.queries),
            2,
        )
        self.assertTrue(connection.transaction_started)
        self.assertTrue(connection.committed)
        self.assertFalse(connection.rolled_back)
        self.assertTrue(connection.closed)

    def test_combined_payment_rolls_back_if_second_account_fails_validation(self):
        cursor = FakePaymentCursor(fail_fines=True)
        response, connection = self.post_combined_payment(cursor, fines_amount="25.00")

        self.assertEqual(response.status_code, 400)
        self.assertIn("Fines payment exceeds", response.get_json()["error"])
        self.assertTrue(connection.rolled_back)
        self.assertFalse(connection.committed)

    def test_existing_single_account_request_still_records_one_transaction(self):
        cursor = FakePaymentCursor()
        connection = FakePaymentConnection(cursor)
        with patch("routes.admin.get_db_connection", return_value=connection):
            response = self.client.post(
                "/api/process-payment",
                json={
                    "student_id": "000123",
                    "transaction_type": "Funds",
                    "payment_type": "Partial",
                    "amount": "40.00",
                    "semester_id": 7,
                },
            )

        self.assertEqual(response.status_code, 200)
        transactions = response.get_json()["transactions"]
        self.assertEqual(len(transactions), 1)
        self.assertEqual(transactions[0]["transaction_type"], "Funds")
        self.assertTrue(connection.committed)


if __name__ == "__main__":
    unittest.main()
