# CIT-Department-System
A department fines and funds tracker for the CIT department

## Database setup

1. Copy `.env.example` to `.env` and set the Flask and MySQL values.
2. Run `database/schema.sql` against MySQL to create the database and all tables used by the application.

The schema creates an empty database. Add an administrator and application data through your normal setup process; no demo or production records are included.

### Existing database: semester enrollment migration

Before deploying the semester-based backend changes, take and verify a full database backup, then ensure exactly one semester is marked active. Run `.\\venv\\Scripts\\python.exe tools\\migrate_semester_schema.py --dry-run` to inspect the target database, followed by `.\\venv\\Scripts\\python.exe tools\\migrate_semester_schema.py` to create and verify table-level safety copies and apply the idempotent schema migration. The migration supports the legacy `school_terms.term_id` primary key and stops if there is not exactly one active semester. It adds semester links and enrollment records for all existing students in the active semester. It links existing events, attendance, funds, fines, and transactions to their semester; it deliberately does not create additional fund charges for those existing students.

Deploy the application code only after the migration completes successfully. New semester enrollments receive that semester's configured fund charge; changing a semester's amount safely reprices those tracked charges while retaining payments already made. Legacy fund balances are carried forward unchanged and are not repriced, because the previous schema does not retain enough assessment/payment detail to change them safely. Dropping a student changes only their enrollment status; existing balances and history are retained.

Each `school_terms` row represents one semester and stores its academic year and semester name together; the `(academic_year, semester)` pair is unique. Events reference that row through `semester_id`, and attendance filters use the linked academic year and semester rather than deriving an academic year from the event date. Semester choices such as `1st Semester`, `2nd Semester`, and `Summer Class` can therefore coexist within the same academic year.

Creating an academic year from Academic Terms creates its `1st Semester`, `2nd Semester`, and `Summer Class` rows together, with dates and fund amounts configured independently for each. If the new year is made active, exactly one of those semesters must be selected as the active semester; creating a year without activating it leaves the current active semester unchanged.
