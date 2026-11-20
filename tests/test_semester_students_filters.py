import unittest
from unittest.mock import patch

from app_factory import create_app


class SemesterStudentsCursor:
    def __init__(self):
        self.query = ""
        self.params = ()
        self.executions = []
        self.student_status = "enrolled"

    def execute(self, query, params=None):
        self.query = query
        self.params = params or ()
        self.executions.append((query, self.params))

    def fetchone(self):
        if "FROM school_terms" in self.query:
            return {
                "id": 2,
                "academic_year": "2026-2027",
                "semester": "2nd Semester",
                "fund_amount": 500,
            }
        return None

    def fetchall(self):
        if "SELECT DISTINCT course" in self.query:
            return [{"course": "BSCS"}, {"course": "BSIS"}]
        if "SELECT DISTINCT year_level" in self.query:
            return [{"year_level": 1}, {"year_level": 4}]
        return [
            {
                "id": 12,
                "student_id": "0012",
                "firstname": "Jane",
                "lastname": "Student",
                "course": "BSCS",
                "year_level": 1,
                "status": self.student_status,
                "enrolled_at": None,
                "dropped_at": None,
            }
        ]

    def close(self):
        pass


class SemesterStudentsConnection:
    def __init__(self):
        self.test_cursor = SemesterStudentsCursor()
        self.closed = False

    def cursor(self, dictionary=False):
        return self.test_cursor

    def close(self):
        self.closed = True


class SemesterStudentsFilterTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session["admin"] = True
        self.connection = SemesterStudentsConnection()

    def get_students(self, query_string=""):
        with patch("routes.admin.get_db_connection", return_value=self.connection):
            return self.client.get(f"/academic-terms/2/students{query_string}")

    def test_search_course_and_year_filters_combine(self):
        response = self.get_students(
            "?search=Jane&course=BSCS&year_level=1"
        )

        self.assertEqual(response.status_code, 200)
        student_query, params = self.connection.test_cursor.executions[-1]
        self.assertIn("CONCAT(s.firstname, ' ', s.lastname) LIKE %s", student_query)
        self.assertIn("s.course=%s", student_query)
        self.assertIn("s.year_level=%s", student_query)
        self.assertEqual(
            params,
            (2, "%Jane%", "%Jane%", "%Jane%", "%Jane%", "BSCS", "1"),
        )
        self.assertIn(b'id="semesterStudentSearch"', response.data)
        self.assertIn(b'class="panel-intro mb-4 d-flex justify-content-between align-items-start"', response.data)
        self.assertIn(b'value="Jane"', response.data)
        self.assertIn(b'value="BSCS" selected', response.data)
        self.assertIn(b'value="1" selected', response.data)
        self.assertTrue(self.connection.closed)

    def test_invalid_course_and_year_filters_are_ignored(self):
        response = self.get_students("?course=INVALID&year_level=9")

        self.assertEqual(response.status_code, 200)
        student_query, params = self.connection.test_cursor.executions[-1]
        self.assertNotIn("s.course=%s", student_query)
        self.assertNotIn("s.year_level=%s", student_query)
        self.assertEqual(params, (2,))

    def test_unfiltered_page_keeps_all_students(self):
        response = self.get_students()

        self.assertEqual(response.status_code, 200)
        student_query, params = self.connection.test_cursor.executions[-1]
        self.assertNotIn("WHERE ", student_query)
        self.assertEqual(params, (2,))
        self.assertIn(b"All courses", response.data)
        self.assertIn(b"All years", response.data)

    def test_dropped_student_can_be_reenrolled_from_the_students_list(self):
        self.connection.test_cursor.student_status = "dropped"

        response = self.get_students()

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            b'action="/academic-terms/2/students/12/enroll"',
            response.data,
        )
        self.assertIn(b">Re-enroll</button>", response.data)
        self.assertNotIn(b"Enrollment retained", response.data)
        self.assertIn(b'data-enrollment-status="non-enrolled"', response.data)

    def test_enrollment_report_modal_offers_both_groups_and_printable_count(self):
        response = self.get_students()

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Report Enrollment", response.data)
        self.assertIn(b'value="enrolled">Enrolled students</option>', response.data)
        self.assertIn(b'value="non-enrolled">Non-enrolled students</option>', response.data)
        self.assertIn(b'id="enrollmentReportPreview"', response.data)
        self.assertIn(b'id="printEnrollmentReportButton"', response.data)
        self.assertIn(b"Student Count: ", response.data)
        self.assertIn(b'class="enrollment-report-toolbar"', response.data)
        self.assertIn(b"className = 'table table-striped table-hover align-middle enrollment-report-table'", response.data)
        self.assertNotIn(b"position: sticky;\n        top: -1rem", response.data)
        self.assertNotIn(b".enrollment-report-table thead th {\n        position: sticky", response.data)
        self.assertNotIn(b"modal-dialog-scrollable", response.data)
        self.assertIn(b"const printWindow = window.open('', '_blank')", response.data)
        self.assertIn(b"color: #000;", response.data)
        self.assertIn(b"printWindow.print()", response.data)


if __name__ == "__main__":
    unittest.main()
