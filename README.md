# CIT-Dept-System
A department fines and funds tracker for the CIT department

## Database setup

1. Copy `.env.example` to `.env` and set the Flask and MySQL values.
2. Run `database/schema.sql` against MySQL.
3. Run `database/seed.sql` only for synthetic demo records.

The seed creates the demo admin `admin` with password `ChangeMe123!`. Change or remove this account before using the system with real data. The seed contains no production student records.
