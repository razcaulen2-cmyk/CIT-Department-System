import unittest

from models.transaction_model import ensure_adjustment_transaction_support


class TransactionSchemaCursor:
    def __init__(self, columns):
        self.columns = columns
        self.queries = []

    def execute(self, query, params=None):
        self.queries.append((query, params))

    def fetchall(self):
        return self.columns


class TransactionSchemaMigrationTests(unittest.TestCase):
    def test_expands_legacy_transaction_enums_without_removing_existing_values(self):
        cursor = TransactionSchemaCursor([
            {
                "COLUMN_NAME": "transaction_type",
                "DATA_TYPE": "enum",
                "COLUMN_TYPE": "enum('Funds','Fines')",
                "IS_NULLABLE": "NO",
                "COLUMN_DEFAULT": None,
            },
            {
                "COLUMN_NAME": "payment_type",
                "DATA_TYPE": "enum",
                "COLUMN_TYPE": "enum('Partial','Full')",
                "IS_NULLABLE": "NO",
                "COLUMN_DEFAULT": None,
            },
        ])

        ensure_adjustment_transaction_support(cursor)

        alters = [query for query, _ in cursor.queries if "ALTER TABLE transactions" in query]
        self.assertEqual(len(alters), 2)
        self.assertIn("ENUM('Funds', 'Fines', 'Adjustment') NOT NULL", alters[0])
        self.assertIn("ENUM('Partial', 'Full', 'Funds', 'Fines') NOT NULL", alters[1])

    def test_does_not_alter_columns_that_already_support_adjustments(self):
        cursor = TransactionSchemaCursor([
            {
                "COLUMN_NAME": "transaction_type",
                "DATA_TYPE": "enum",
                "COLUMN_TYPE": "enum('Funds','Fines','Adjustment')",
                "IS_NULLABLE": "NO",
                "COLUMN_DEFAULT": None,
            },
            {
                "COLUMN_NAME": "payment_type",
                "DATA_TYPE": "enum",
                "COLUMN_TYPE": "enum('Partial','Full','Funds','Fines')",
                "IS_NULLABLE": "NO",
                "COLUMN_DEFAULT": None,
            },
        ])

        ensure_adjustment_transaction_support(cursor)

        self.assertEqual(len(cursor.queries), 1)


if __name__ == "__main__":
    unittest.main()
