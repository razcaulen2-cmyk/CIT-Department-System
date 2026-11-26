import unittest

from tools.migrate_student_keys import (
    FINANCIAL_TABLES,
    drop_legacy_student_id_foreign_keys,
)


class MigrationCursor:
    def __init__(self, foreign_keys):
        self.foreign_keys = foreign_keys
        self.queries = []

    def execute(self, query, params=None):
        self.queries.append((query, params))

    def fetchall(self):
        return self.foreign_keys


class DropLegacyStudentIdForeignKeysTests(unittest.TestCase):
    def test_drops_legacy_student_id_foreign_key(self):
        cursor = MigrationCursor([("transactions", "transactions_ibfk_1")])

        drop_legacy_student_id_foreign_keys(cursor)

        self.assertIn(
            (
                "ALTER TABLE `transactions` DROP FOREIGN KEY `transactions_ibfk_1`",
                None,
            ),
            cursor.queries,
        )
        self.assertEqual(cursor.queries[0][1], FINANCIAL_TABLES)

    def test_does_not_drop_constraints_when_none_reference_student_id(self):
        cursor = MigrationCursor([])

        drop_legacy_student_id_foreign_keys(cursor)

        self.assertEqual(len(cursor.queries), 1)


if __name__ == "__main__":
    unittest.main()
