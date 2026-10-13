import unittest
from decimal import Decimal
from unittest.mock import patch

from flask import Flask

import routes.admin as admin_module
from models import event_model


class FakeCursor:
    def __init__(self, existing_fine=None, dictionary=False, allocated_paid=Decimal("0.00")):
        self.existing_fine = existing_fine
        self.dictionary = dictionary
        self.allocated_paid = allocated_paid
        self.queries = []

    def execute(self, query, params=None):
        self.queries.append((query, params))
        if hasattr(self, "connection"):
            self.connection.queries_executed += 1

    def fetchone(self):
        query = self.queries[-1][0]
        if "FROM fines" in query and "SELECT fine_id, amount, assessed_amount" in query:
            return self.existing_fine
        if "SUM(amount_paid)" in query:
            return (self.allocated_paid,)
        if "FROM students WHERE id=%s" in query and "FOR UPDATE" in query:
            return (1, "000123")
        return None

    def close(self):
        pass


class FakeConnection:
    def __init__(self, cursors):
        self.cursors = iter(cursors)
        self.committed = False
        self.rolled_back = False
        self.closed = False
        self.queries_executed = 0
        self.transaction_started = False

    def cursor(self, dictionary=False):
        cursor = next(self.cursors)
        cursor.connection = self
        return cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def start_transaction(self):
        if self.queries_executed:
            raise RuntimeError("Cannot start transaction after a query has run")
        if self.transaction_started:
            raise RuntimeError("Transaction already started")
        self.transaction_started = True

    def close(self):
        self.closed = True


class FineAssessmentTests(unittest.TestCase):
    def test_resync_preserves_paid_part_of_fine(self):
        cursor = FakeCursor((17, Decimal("50.00"), Decimal("100.00")))
        connection = FakeConnection([cursor])

        with patch.object(event_model, "get_db_connection", return_value=connection):
            event_model.create_or_update_fine("000123", 4, "Absent", 100)

        self.assertEqual(
            cursor.queries[-1][1],
            (Decimal("50.00"), Decimal("100.00"), 17),
        )
        self.assertIn("FOR UPDATE", cursor.queries[0][0])

    def test_resync_applies_new_assessment_without_reopening_paid_amount(self):
        cursor = FakeCursor((17, Decimal("50.00"), Decimal("100.00")))
        connection = FakeConnection([cursor])

        with patch.object(event_model, "get_db_connection", return_value=connection):
            event_model.create_or_update_fine("000123", 4, "Absent", 120)

        self.assertEqual(
            cursor.queries[-1][1],
            (Decimal("70.00"), Decimal("120.00"), 17),
        )

    def test_recreated_fine_uses_payment_allocation(self):
        cursor = FakeCursor(allocated_paid=Decimal("25.00"))
        connection = FakeConnection([cursor])

        with patch.object(event_model, "get_db_connection", return_value=connection):
            event_model.create_or_update_fine("000123", 4, "Absent", 25)

        self.assertIn("INSERT INTO fines", cursor.queries[-1][0])
        self.assertEqual(
            cursor.queries[-1][1],
            ("000123", 4, "Absent", Decimal("0.00"), Decimal("25.00")),
        )


class StudentIdRemappingTests(unittest.TestCase):
    def test_remapping_moves_financial_rows_to_new_student_id(self):
        read_cursor = FakeCursor(dictionary=True)
        read_cursor.fetchone = lambda: {
            "id": 1,
            "student_id": "000123",
            "firstname": "Test",
            "lastname": "Student",
        }
        write_cursor = FakeCursor()
        write_cursor.fetchone = lambda: (1, "000123") if (
            "FOR UPDATE" in write_cursor.queries[-1][0]
        ) else None
        connection = FakeConnection([read_cursor, write_cursor])
        app = Flask(__name__)
        app.secret_key = "test"
        app.register_blueprint(admin_module.admin_bp)
        client = app.test_client()

        with client.session_transaction() as session:
            session["admin"] = 1
        with patch.object(event_model, "ensure_fine_payment_allocations"):
            with patch.object(admin_module, "get_db_connection", return_value=connection):
                response = client.post("/map-rfid/1", data={"student_id": "000456"})

        self.assertEqual(response.status_code, 302)
        self.assertTrue(connection.committed)
        self.assertTrue(connection.transaction_started)
        ledger_updates = [
            (query.split("UPDATE ", 1)[1].split(" SET", 1)[0], params)
            for query, params in write_cursor.queries
            if query.startswith("UPDATE ")
            and "student_id=%s WHERE student_id=%s" in query
        ]
        self.assertEqual(
            ledger_updates,
            [
                ("student_funds", ("000456", "000123")),
                ("fines", ("000456", "000123")),
                ("fine_payment_allocations", ("000456", "000123")),
                ("transactions", ("000456", "000123")),
                ("student_funds", ("000456", "1")),
                ("fines", ("000456", "1")),
                ("fine_payment_allocations", ("000456", "1")),
                ("transactions", ("000456", "1")),
            ],
        )


if __name__ == "__main__":
    unittest.main()
