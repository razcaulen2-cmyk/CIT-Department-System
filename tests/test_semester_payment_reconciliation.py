import unittest
from decimal import Decimal
from unittest.mock import patch

from app_factory import create_app


class EnrollmentCursor:
    def __init__(self):
        self.query = ""
        self.params = ()

    def execute(self, query, params=None):
        self.query = query
        self.params = params

    def fetchone(self):
        if "SELECT student_id FROM students" in self.query:
            return ("0012",)
        if "SELECT status FROM semester_enrollments" in self.query:
            return None
        if "SELECT id FROM school_terms" in self.query:
            return (2,)
        return None

    def close(self):
        pass


class EnrollmentConnection:
    def __init__(self):
        self.test_cursor = EnrollmentCursor()
        self.committed = False
        self.closed = False

    def cursor(self):
        return self.test_cursor

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


class SemesterPaymentReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session["admin"] = True

    def test_enrollment_applies_previous_unallocated_fund_transactions(self):
        connection = EnrollmentConnection()
        with patch("routes.admin.get_db_connection", return_value=connection):
            with patch("routes.admin.ensure_transaction_balance_snapshots") as ensure_snapshots:
                with patch("routes.admin.semester_model.enroll_student") as enroll:
                    with patch(
                        "routes.admin.semester_model.apply_unallocated_fund_transactions",
                        return_value=Decimal("300.00"),
                    ) as reconcile:
                        response = self.client.post(
                            "/academic-terms/2/students/12/enroll"
                        )

        self.assertEqual(response.status_code, 302)
        ensure_snapshots.assert_called_once_with(connection.test_cursor)
        enroll.assert_called_once_with(connection.test_cursor, 2, 12, "0012")
        reconcile.assert_called_once_with(connection.test_cursor, 2, "0012")
        self.assertTrue(connection.committed)
        self.assertTrue(connection.closed)
        with self.client.session_transaction() as session:
            flashes = session.get("_flashes", [])
        self.assertTrue(
            any("PHP 300.00 in earlier fund payments was applied." in message for _, message in flashes)
        )


if __name__ == "__main__":
    unittest.main()
