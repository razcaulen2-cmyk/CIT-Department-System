import unittest
from decimal import Decimal
from unittest.mock import patch

from models import event_model, semester_model


class EnrollmentCursor:
    def __init__(self, fund_amount=Decimal("0.00"), rowcount=1):
        self.fund_amount = fund_amount
        self.rowcount = rowcount
        self.insert_rowcount = rowcount
        self.queries = []

    def execute(self, query, params=None):
        self.queries.append((query, params))
        if query.startswith("INSERT IGNORE"):
            self.rowcount = self.insert_rowcount

    def fetchone(self):
        return (self.fund_amount,)


class SemesterEnrollmentTests(unittest.TestCase):
    def test_existing_enrollment_does_not_create_duplicate_fee(self):
        cursor = EnrollmentCursor(Decimal("75.00"), rowcount=0)

        enrolled = semester_model.enroll_student(cursor, 3, 12, "0012")

        self.assertFalse(enrolled)
        self.assertEqual(len(cursor.queries), 1)

    def test_new_enrollment_charges_the_semester_fund(self):
        cursor = EnrollmentCursor(Decimal("75.00"))

        enrolled = semester_model.enroll_student(cursor, 3, 12, "0012")

        self.assertTrue(enrolled)
        self.assertIn("INSERT INTO student_funds", cursor.queries[-1][0])
        self.assertEqual(
            cursor.queries[-1][1],
            ("0012", 3, Decimal("75.00"), Decimal("75.00")),
        )

    def test_legacy_enrollment_can_skip_fund_charge(self):
        cursor = EnrollmentCursor(Decimal("75.00"))

        enrolled = semester_model.enroll_student(
            cursor,
            3,
            12,
            "0012",
            charge_fund=False,
        )

        self.assertTrue(enrolled)
        self.assertEqual(len(cursor.queries), 1)

    def test_fund_reprice_preserves_amount_already_paid(self):
        class RepriceCursor:
            def __init__(self):
                self.queries = []

            def execute(self, query, params=None):
                self.queries.append((query, params))

            def fetchall(self):
                return [(91, "0012", Decimal("60.00"))]

        cursor = RepriceCursor()
        semester_model.reprice_semester_funds(cursor, 3, Decimal("120.00"))

        self.assertEqual(
            cursor.queries[-1][1],
            (Decimal("60.00"), Decimal("120.00"), 91),
        )


class EventSemesterEligibilityTests(unittest.TestCase):
    def test_fine_sync_skips_event_when_semester_has_no_active_enrollments(self):
        event = {"id": 4, "semester_id": 3}
        with patch.object(semester_model, "get_enrolled_student_ids", return_value=set()):
            with patch.object(event_model, "ensure_fine_assessment_column") as ensure_fines:
                with patch.object(event_model.student_model, "get_all_students") as get_students:
                    event_model.sync_fines_for_event(event)

        ensure_fines.assert_not_called()
        get_students.assert_not_called()

    def test_fine_sync_only_assesses_students_still_enrolled_in_event_semester(self):
        event = {
            "id": 4,
            "semester_id": 3,
            "absent_fine": 25,
            "late_fine": 10,
        }
        students = [
            {"id": 12, "student_id": "0012"},
            {"id": 13, "student_id": "0013"},
        ]
        with patch.object(semester_model, "get_enrolled_student_ids", return_value={12}):
            with patch.object(event_model, "ensure_fine_assessment_column"):
                with patch.object(event_model, "ensure_fine_payment_allocations"):
                    with patch.object(event_model.student_model, "get_all_students", return_value=students):
                        with patch.object(event_model, "get_event_exemption_ids", return_value=set()):
                            with patch.object(event_model, "get_paper_attendance_for_event", return_value={}):
                                with patch.object(event_model, "is_event_closed", return_value=True):
                                    with patch.object(event_model.attendance_model, "get_attendance_by_event", return_value=[]):
                                        with patch.object(event_model, "create_or_update_fine") as assess_fine:
                                            with patch.object(event_model, "remove_event_fine") as remove_fine:
                                                event_model.sync_fines_for_event(event)

        assess_fine.assert_called_once_with("0012", 4, "Absent", 25.0)
        remove_fine.assert_not_called()


if __name__ == "__main__":
    unittest.main()
