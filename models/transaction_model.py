import re


def ensure_transaction_adjustments(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS transaction_adjustments (
            adjustment_id INT AUTO_INCREMENT PRIMARY KEY,
            transaction_id INT NOT NULL,
            student_id VARCHAR(32) NOT NULL,
            account_type VARCHAR(16) NOT NULL,
            amount_delta DECIMAL(10, 2) NOT NULL,
            remarks TEXT NOT NULL,
            balance_row_id INT NULL,
            event_id INT NULL,
            fine_type VARCHAR(50) NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_adjustments_transaction (transaction_id),
            INDEX idx_adjustments_student_account (student_id, account_type),
            INDEX idx_adjustments_balance_row (balance_row_id),
            INDEX idx_adjustments_fine_identity (student_id, event_id, fine_type)
        ) ENGINE=InnoDB
        """
    )


def ensure_adjustment_transaction_support(cursor):
    cursor.execute(
        """
        SELECT COLUMN_NAME, DATA_TYPE, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA=DATABASE()
            AND TABLE_NAME='transactions'
            AND COLUMN_NAME IN ('transaction_type', 'payment_type')
        """
    )
    columns = {
        row["COLUMN_NAME"]: row
        for row in cursor.fetchall()
    }

    required_values = {
        "transaction_type": ("Adjustment",),
        "payment_type": ("Funds", "Fines"),
    }
    for column_name, additions in required_values.items():
        column = columns.get(column_name)
        if not column or column["DATA_TYPE"].lower() != "enum":
            continue

        values = re.findall(r"'((?:[^']|'')*)'", column["COLUMN_TYPE"])
        decoded_values = [value.replace("''", "'") for value in values]
        if all(value in decoded_values for value in additions):
            continue

        for value in additions:
            if value not in decoded_values:
                decoded_values.append(value)
        enum_values = ", ".join(
            "'" + value.replace("'", "''") + "'"
            for value in decoded_values
        )
        nullability = "NULL" if column["IS_NULLABLE"] == "YES" else "NOT NULL"
        default = column["COLUMN_DEFAULT"]
        default_clause = ""
        if default is not None:
            escaped_default = str(default).replace("'", "''")
            default_clause = f" DEFAULT '{escaped_default}'"
        cursor.execute(
            f"""
            ALTER TABLE transactions
            MODIFY COLUMN {column_name} ENUM({enum_values}) {nullability}{default_clause}
            """
        )
