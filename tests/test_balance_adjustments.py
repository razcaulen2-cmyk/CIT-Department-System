import unittest
from decimal import Decimal
from unittest.mock import patch

from app_factory import create_app
from flask import render_template


class FakeAdjustmentCursor:
    def __init__(self, account_type="Funds", balance_rows=None):
        self.account_type = account_type
        self.balance_rows = balance_rows or []
        self.queries = []
        self.lastrowid = 0

    def execute(self, query, params=None):
        self.queries.append((query, params))
        if "INSERT INTO transactions" in query:
            self.lastrowid = 91
        elif "INSERT INTO student_funds" in query:
            self.lastrowid = 207

    def fetchone(self):
        query = self.queries[-1][0]
        if "FROM students" in query:
            return {
                "id": 1,
                "student_id": "000123",
                "firstname": "Test",
                "lastname": "Student",
            }
        if "FROM school_terms" in query:
            return {"id": 4, "academic_year": "2026-2027", "semester": "2nd Semester"}
        return None

    def fetchall(self):
        if "INFORMATION_SCHEMA.COLUMNS" in self.queries[-1][0]:
            return []
        return self.balance_rows

    def close(self):
        pass


class FakeAdjustmentConnection:
    def __init__(self, cursor):
        self.test_cursor = cursor
        self.transaction_started = False
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self, dictionary=False):
        return self.test_cursor

    def start_transaction(self):
        self.transaction_started = True
        self.rolled_back = False

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


class BalanceAdjustmentTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session["admin"] = True

    def post_adjustment(self, cursor, **overrides):
        connection = FakeAdjustmentConnection(cursor)
        payload = {
            "student_id": "000123",
            "semester_id": 4,
            "account_type": "Funds",
            "direction": "decrease",
            "amount": "20.00",
            "remarks": "Already paid before system launch.",
        }
        payload.update(overrides)
        with patch("routes.admin.get_db_connection", return_value=connection):
            with patch("routes.admin.event_model.ensure_fine_assessment_column"):
                response = self.client.post("/api/adjust-balance", json=payload)
        return response, connection

    def test_decrease_adjusts_funds_and_records_remarks_and_signed_delta(self):
        cursor = FakeAdjustmentCursor(balance_rows=[{
            "id": 17,
            "amount_due": Decimal("75.00"),
            "assessed_amount": Decimal("75.00"),
            "paid_amount": Decimal("0.00"),
            "is_semester_fund": True,
        }])
        response, connection = self.post_adjustment(cursor)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["transaction_id"], 91)
        update = next(
            (params for query, params in cursor.queries if "UPDATE student_funds" in query),
            None,
        )
        self.assertEqual(update, (Decimal("55.00"), Decimal("55.00"), 17, "000123"))
        adjustment = next(
            params for query, params in cursor.queries
            if "INSERT INTO transaction_adjustments" in query
        )
        self.assertEqual(adjustment, (
            91, "000123", "Funds", Decimal("-20.00"),
            "Already paid before system launch.", 17, None, None,
        ))
        self.assertTrue(connection.committed)
        self.assertFalse(connection.rolled_back)

    def test_increase_creates_funds_row_when_semester_has_no_fund_row(self):
        cursor = FakeAdjustmentCursor(balance_rows=[])
        response, connection = self.post_adjustment(
            cursor,
            direction="increase",
            amount="45.00",
            remarks="Additional department fund assessed.",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(any("INSERT INTO student_funds" in query for query, _ in cursor.queries))
        adjustment = next(
            params for query, params in cursor.queries
            if "INSERT INTO transaction_adjustments" in query
        )
        self.assertEqual(adjustment[3], Decimal("45.00"))
        self.assertEqual(adjustment[5], 207)
        self.assertTrue(connection.committed)

    def test_fine_adjustment_updates_assessment_without_recording_collection(self):
        cursor = FakeAdjustmentCursor("Fines", [{
            "fine_id": 31,
            "event_id": 8,
            "fine_type": "Absent",
            "amount": Decimal("50.00"),
            "assessed_amount": Decimal("100.00"),
        }])
        response, connection = self.post_adjustment(
            cursor,
            account_type="Fines",
            direction="increase",
            amount="10.00",
            remarks="Corrected fine assessment.",
        )

        self.assertEqual(response.status_code, 200)
        update = next(
            params for query, params in cursor.queries if "UPDATE fines" in query
        )
        self.assertEqual(update, (Decimal("60.00"), Decimal("110.00"), 31, "000123"))
        adjustment = next(
            params for query, params in cursor.queries
            if "INSERT INTO transaction_adjustments" in query
        )
        self.assertEqual(adjustment[3], Decimal("10.00"))
        self.assertEqual(adjustment[6:], (8, "Absent"))
        transaction = next(
            params for query, params in cursor.queries
            if "INSERT INTO transactions" in query
        )
        self.assertEqual(transaction[2], "Fines")
        self.assertIn("'Adjustment'", next(
            query for query, _ in cursor.queries if "INSERT INTO transactions" in query
        ))
        self.assertTrue(connection.committed)

    def test_adjustment_cannot_reduce_balance_below_zero(self):
        cursor = FakeAdjustmentCursor(balance_rows=[{
            "id": 17,
            "amount_due": Decimal("10.00"),
            "assessed_amount": Decimal("10.00"),
            "paid_amount": Decimal("0.00"),
            "is_semester_fund": True,
        }])
        response, connection = self.post_adjustment(cursor, amount="20.00")

        self.assertEqual(response.status_code, 400)
        self.assertIn("outstanding funds balance", response.get_json()["error"])
        self.assertTrue(connection.rolled_back)
        self.assertFalse(connection.committed)
        self.assertFalse(any("INSERT INTO transactions" in query for query, _ in cursor.queries))

    def test_adjustment_requires_remarks(self):
        cursor = FakeAdjustmentCursor()
        response, connection = self.post_adjustment(cursor, remarks="   ")

        self.assertEqual(response.status_code, 400)
        self.assertIn("Remarks are required", response.get_json()["error"])
        self.assertFalse(connection.transaction_started)

    def test_finance_attendance_modal_includes_adjustment_controls(self):
        with self.app.test_request_context("/finance"):
            html = render_template(
                "admin/finance.html",
                students=[],
                terms=[{
                    "id": 4,
                    "academic_year": "2026-2027",
                    "semester": "2nd Semester",
                }],
                selected_semester_id="4",
                year_levels=[],
                courses=[],
            )

        self.assertIn('id="openBalanceAdjustment"', html)
        self.assertIn('id="balanceAdjustmentModal"', html)
        self.assertIn('id="adjustmentAccount"', html)
        self.assertIn('id="adjustmentDirection"', html)
        self.assertIn('id="adjustmentRemarks"', html)


if __name__ == "__main__":
    unittest.main()
