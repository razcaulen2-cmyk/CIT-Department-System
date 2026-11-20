import unittest
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

from app_factory import create_app


class FakeReportCursor:
    def __init__(self, transactions):
        self.transactions = transactions
        self.queries = []

    def execute(self, query, params=None):
        self.queries.append((query, params))

    def fetchone(self):
        return {
            "report_date": date(2026, 10, 22),
            "generated_at": datetime(2026, 10, 22, 9, 19),
        }

    def fetchall(self):
        return self.transactions

    def close(self):
        pass


class FakeReportConnection:
    def __init__(self, transactions):
        self.report_cursor = FakeReportCursor(transactions)

    def cursor(self, dictionary=False):
        return self.report_cursor

    def close(self):
        pass


class TransactionReportTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session["admin"] = True

    @staticmethod
    def transaction(academic_year, semester):
        return {
            "id": 1,
            "student_id": "000123",
            "student_name": "Test Student",
            "transaction_type": "Funds",
            "payment_type": "Full",
            "amount": Decimal("100.00"),
            "academic_year": academic_year,
            "semester": semester,
            "transaction_date": datetime(2026, 10, 22, 9, 0),
        }

    def render_report(self, transactions, query_string="period=overall"):
        connection = FakeReportConnection(transactions)
        with patch("routes.admin.get_db_connection", return_value=connection):
            response = self.client.get(f"/transaction-report?{query_string}")
        return response, connection.report_cursor

    def test_calendar_date_and_academic_term_filters_are_combined(self):
        response, cursor = self.render_report(
            [self.transaction("2026-2027", "1st Semester")],
            "period=overall&calendar_date=2026-10-22&semester_id=7"
            "&transaction_type=Funds",
        )

        self.assertEqual(response.status_code, 200)
        query, params = cursor.queries[-1]
        self.assertIn("t.transaction_date >= %s AND t.transaction_date < %s", query)
        self.assertIn("t.semester_id=%s", query)
        self.assertIn("FROM school_terms st", query)
        self.assertIn("t.transaction_type=%s", query)
        self.assertEqual(
            params,
            (date(2026, 10, 22), date(2026, 10, 23), 7, 7, "Funds"),
        )
        self.assertIn("Calendar date - October 22, 2026", response.get_data(as_text=True))

    def test_invalid_calendar_date_is_rejected(self):
        response, _ = self.render_report(
            [],
            "period=overall&calendar_date=not-a-date",
        )

        self.assertEqual(response.status_code, 400)

    def test_single_semester_is_a_centered_headline_not_a_row_detail(self):
        response, _ = self.render_report([
            self.transaction("2026-2027", "1st Semester"),
            self.transaction("2026-2027", "1st Semester"),
        ])

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn(
            '<h2 class="transaction-report-term-heading mb-0">2026-2027 · 1st Semester</h2>',
            html,
        )
        self.assertEqual(html.count("2026-2027 · 1st Semester"), 1)
        self.assertNotIn("report-row-meta", html)
        self.assertLess(html.index("transaction-report-table-wrap"), html.index("Collection Summary"))
        self.assertLess(html.index("Collection Summary"), html.index("Received By:"))
        self.assertIn("Presented By:", html)

    def test_multiple_semesters_are_identified_as_mixed(self):
        response, _ = self.render_report([
            self.transaction("2026-2027", "1st Semester"),
            self.transaction("2026-2027", "2nd Semester"),
        ])

        self.assertEqual(response.status_code, 200)
        self.assertIn("Multiple Semesters", response.get_data(as_text=True))

    def test_adjustment_is_listed_but_excluded_from_collected_totals_and_count(self):
        adjustment = self.transaction("2026-2027", "1st Semester")
        adjustment.update({
            "id": 2,
            "transaction_type": "Adjustment",
            "payment_type": "Funds",
            "adjustment_direction": "Decrease",
            "amount": Decimal("75.00"),
        })
        response, _ = self.render_report([
            self.transaction("2026-2027", "1st Semester"),
            adjustment,
        ])

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Adjustment", html)
        self.assertIn("Number of transactions</th>\n                    <td>1</td>", html)
        self.assertIn("Total collected</th>\n                    <td>PHP 100.00</td>", html)


if __name__ == "__main__":
    unittest.main()