import unittest
from decimal import Decimal
from unittest.mock import patch

from flask import Flask

import routes.admin as admin_module
from models import event_model


class FakeCursor:
    def __init__(
        self,
        existing_fine=None,
        dictionary=False,
        allocated_paid=Decimal("0.00"),
        manual_adjustment=Decimal("0.00"),
        duplicate_fines=False,
    ):
        self.existing_fine = existing_fine
        self.dictionary = dictionary
        self.allocated_paid = allocated_paid
        self.manual_adjustment = manual_adjustment
        self.duplicate_fines = duplicate_fines
        self.queries = []

    def execute(self, query, params=None):
        self.queries.append((query, params))
        if hasattr(self, "connection"):
            self.connection.queries_executed += 1

    def fetchone(self):
        query = self.queries[-1][0]
        if "GROUP BY fine_type" in query and self.duplicate_fines:
            return ("Absent",)
        if "FROM fines" in query and "SELECT fine_id, amount, assessed_amount" in query:
            return self.existing_fine
        if "SUM(amount_paid)" in query:
            return (self.allocated_paid,)
        if "SUM(amount_delta)" in query:
            return (self.manual_adjustment,)
        if "FROM students WHERE id=%s" in query and "FOR UPDATE" in query:
            return (1, "000123")
        return None

    def fetchall(self):
        query = self.queries[-1][0]
        if "FROM fines" in query and "SELECT fine_id, amount, assessed_amount" in query:
            if self.existing_fine is None:
                return []
            if self.duplicate_fines:
                return [self.existing_fine, self.existing_fine]
            return [self.existing_fine]
        return []

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
    def test_resync_skips_legacy_duplicate_fines(self):
        cursor = FakeCursor(
            (17, Decimal("50.00"), Decimal("100.00")),
            duplicate_fines=True,
        )
        connection = FakeConnection([cursor])

        with patch.object(event_model, "get_db_connection", return_value=connection):
            event_model.create_or_update_fine(1, 4, "Absent", 100, "000123")

        self.assertTrue(connection.rolled_back)
        self.assertTrue(connection.closed)
        self.assertFalse(any(
            query.startswith(("UPDATE fines", "INSERT INTO fines"))
            for query, _ in cursor.queries
        ))

    def test_removal_skips_legacy_duplicate_fines(self):
        cursor = FakeCursor(duplicate_fines=True)
        connection = FakeConnection([cursor])

        with patch.object(event_model, "get_db_connection", return_value=connection):
            event_model.remove_event_fine(1, 4, "Absent")

        self.assertTrue(connection.rolled_back)
        self.assertTrue(connection.closed)
        self.assertFalse(any(query.startswith("DELETE FROM fines") for query, _ in cursor.queries))

    def test_resync_preserves_paid_part_of_fine(self):
        cursor = FakeCursor((17, Decimal("50.00"), Decimal("100.00")))
        connection = FakeConnection([cursor])

        with patch.object(event_model, "get_db_connection", return_value=connection):
            event_model.create_or_update_fine(1, 4, "Absent", 100, "000123")

        self.assertEqual(
            cursor.queries[-1][1],
            (Decimal("50.00"), Decimal("100.00"), 4, 17),
        )
        self.assertTrue(any("FOR UPDATE" in query for query, _ in cursor.queries))

    def test_resync_applies_new_assessment_without_reopening_paid_amount(self):
        cursor = FakeCursor((17, Decimal("50.00"), Decimal("100.00")))
        connection = FakeConnection([cursor])

        with patch.object(event_model, "get_db_connection", return_value=connection):
            event_model.create_or_update_fine(1, 4, "Absent", 120, "000123")

        self.assertEqual(
            cursor.queries[-1][1],
            (Decimal("70.00"), Decimal("120.00"), 4, 17),
        )

    def test_recreated_fine_uses_payment_allocation(self):
        cursor = FakeCursor(allocated_paid=Decimal("25.00"))
        connection = FakeConnection([cursor])

        with patch.object(event_model, "get_db_connection", return_value=connection):
            event_model.create_or_update_fine(1, 4, "Absent", 25, "000123")

        self.assertIn("INSERT INTO fines", cursor.queries[-1][0])
        self.assertEqual(
            cursor.queries[-1][1],
            (1, "000123", 4, "Absent", Decimal("0.00"), Decimal("25.00"), 4),
        )

    def test_resync_preserves_balance_adjustment(self):
        cursor = FakeCursor(
            (17, Decimal("50.00"), Decimal("100.00")),
            manual_adjustment=Decimal("10.00"),
        )
        connection = FakeConnection([cursor])

        with patch.object(event_model, "get_db_connection", return_value=connection):
            event_model.create_or_update_fine(1, 4, "Absent", 120, "000123")

        self.assertEqual(
            cursor.queries[-1][1],
            (Decimal("80.00"), Decimal("130.00"), 4, 17),
        )


class StudentIdRemappingTests(unittest.TestCase):
    def test_remapping_changes_only_the_student_identifier(self):
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
        with patch.object(admin_module, "get_db_connection", return_value=connection):
            response = client.post("/map-rfid/1", data={"student_id": "000456"})

        self.assertEqual(response.status_code, 302)
        self.assertTrue(connection.committed)
        self.assertTrue(connection.transaction_started)
        student_update = [
            params
            for query, params in write_cursor.queries
            if query.startswith("UPDATE students")
        ]
        self.assertEqual(student_update, [("000456", 1)])
        self.assertFalse(any(
            query.startswith(("UPDATE student_funds", "UPDATE fines", "UPDATE transactions"))
            for query, _ in write_cursor.queries
        ))


if __name__ == "__main__":
    unittest.main()
