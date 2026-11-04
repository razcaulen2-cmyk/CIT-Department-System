import unittest
from decimal import Decimal
from unittest.mock import patch

import mysql.connector

from app_factory import create_app


class AcademicTermEditCursor:
    def __init__(self, fail_on_query=None):
        self.executions = []
        self.fail_on_query = fail_on_query
        self.closed = False

    def execute(self, query, params=None):
        self.executions.append((query, params))
        if self.fail_on_query and self.fail_on_query in query:
            raise mysql.connector.Error("Database update failed.")

    def fetchone(self):
        query = self.executions[-1][0]
        if "SELECT id FROM school_terms WHERE id=%s" in query:
            return (2,)
        return None

    def fetchall(self):
        return []

    def close(self):
        self.closed = True


class AcademicTermEditConnection:
    def __init__(self, fail_on_query=None):
        self.test_cursor = AcademicTermEditCursor(fail_on_query)
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


class AcademicTermEditTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session["admin"] = True

    @staticmethod
    def form_data(**overrides):
        form = {
            "academic_year": "2026-2027",
            "semester": "1st Semester",
            "start_date": "2026-08-01",
            "end_date": "2026-12-15",
            "fund_amount": "125.50",
            "is_active": "on",
        }
        form.update(overrides)
        return form

    def test_edit_active_term_updates_transactions_and_reprices_funds(self):
        connection = AcademicTermEditConnection()
        with patch("routes.admin.get_db_connection", return_value=connection):
            response = self.client.post(
                "/edit-academic-term/2",
                data=self.form_data(),
            )

        executions = connection.test_cursor.executions
        term_update = next(
            params for query, params in executions
            if "UPDATE school_terms" in query and "SET academic_year=" in query
        )
        transaction_update = next(
            params for query, params in executions
            if "UPDATE transactions" in query
        )
        repricing_query = next(
            query for query, _ in executions
            if "FROM student_funds" in query and "FOR UPDATE" in query
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(term_update, (
            "2026-2027",
            "1st Semester",
            "2026-08-01",
            "2026-12-15",
            Decimal("125.50"),
            True,
            "2",
        ))
        self.assertEqual(transaction_update, ("2026-2027", "1st Semester", "2"))
        self.assertTrue(repricing_query)
        self.assertTrue(connection.committed)
        self.assertFalse(connection.rolled_back)
        self.assertTrue(connection.test_cursor.closed)
        self.assertTrue(connection.closed)

    def test_database_error_rolls_back_and_redirects_with_flash(self):
        connection = AcademicTermEditConnection(fail_on_query="UPDATE transactions")
        with patch("routes.admin.get_db_connection", return_value=connection):
            response = self.client.post(
                "/edit-academic-term/2",
                data=self.form_data(fund_amount="200.00"),
            )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(connection.committed)
        self.assertTrue(connection.rolled_back)
        self.assertTrue(connection.closed)
        with self.client.session_transaction() as session:
            flashes = session.get("_flashes", [])
        self.assertTrue(any("Unable to save the academic term" in message for _, message in flashes))

    def test_invalid_fund_amount_does_not_open_database_connection(self):
        with patch("routes.admin.get_db_connection") as get_connection:
            response = self.client.post(
                "/edit-academic-term/2",
                data=self.form_data(fund_amount="-10"),
            )

        self.assertEqual(response.status_code, 302)
        get_connection.assert_not_called()


if __name__ == "__main__":
    unittest.main()
