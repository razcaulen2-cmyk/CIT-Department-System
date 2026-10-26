# CIT-Department-System
A department fines and funds tracker for the CIT department

## Database setup

1. Copy `.env.example` to `.env` and set the Flask and MySQL values.
2. Run `database/schema.sql` against MySQL to create the database and all tables used by the application.

The schema creates an empty database. Add an administrator and application data through your normal setup process; no demo or production records are included.

### Office LAN access on Windows

The application listens on all network interfaces on port `5000`. On the office desktop, set up the project, its `.env` file, database, and `venv` first. To start it automatically when the current Windows user signs in, run this from the project folder in PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\install_autostart.ps1
```

This adds a shortcut to the current Windows user's Startup folder. The tracker starts when that user signs in. On the desktop, open `http://127.0.0.1:5000`; from other office computers on the same LAN, open `http://<desktop-IPv4-address>:5000` (for example, `http://192.168.50.16:5000`). Run `ipconfig` on the desktop to find its current IPv4 address. Ask the network administrator to reserve that address for the desktop in DHCP so the office URL does not change.

Windows Firewall may block connections from other computers. In an elevated PowerShell window on the desktop, allow TCP port 5000 only from the local subnet on a Domain or Private network profile:

```powershell
New-NetFirewallRule -DisplayName "CIT Department System (Office LAN)" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 5000 -Profile Domain,Private -RemoteAddress LocalSubnet
```

Keep the desktop powered on and signed in while staff use the system. This HTTP setup is intended only for a trusted office LAN, not direct internet access. To remove the startup shortcut, run `powershell -ExecutionPolicy Bypass -File .\install_autostart.ps1 -Uninstall`. Remove the firewall rule when office LAN access is no longer needed with `Remove-NetFirewallRule -DisplayName "CIT Department System (Office LAN)"`.

### Running without internet

Bootstrap, Bootstrap Icons (including their font files), and Chart.js are stored under `static/vendor`, so the application pages do not need public CDNs or an internet connection to load their UI. Keep the office desktop's Python environment and MySQL database installed locally; browsers on other office computers connect only to the desktop over the office LAN, and the application connects to MySQL on the desktop. Internet access is not required for normal operation after setup, but the desktop and client computers must remain connected to the same LAN.

### Existing database: semester enrollment migration

Before deploying the semester-based backend changes, take and verify a full database backup, then ensure exactly one semester is marked active. Run `.\\venv\\Scripts\\python.exe tools\\migrate_semester_schema.py --dry-run` to inspect the target database, followed by `.\\venv\\Scripts\\python.exe tools\\migrate_semester_schema.py` to create and verify table-level safety copies and apply the idempotent schema migration. The migration supports the legacy `school_terms.term_id` primary key and stops if there is not exactly one active semester. It adds semester links and enrollment records for all existing students in the active semester. It links existing events, attendance, funds, fines, and transactions to their semester; it deliberately does not create additional fund charges for those existing students.

Deploy the application code only after the migration completes successfully. New semester enrollments receive that semester's configured fund charge; changing a semester's amount safely reprices those tracked charges while retaining payments already made. Legacy fund balances are carried forward unchanged and are not repriced, because the previous schema does not retain enough assessment/payment detail to change them safely. Dropping a student changes only their enrollment status; existing balances and history are retained.

Each `school_terms` row represents one semester and stores its academic year and semester name together; the `(academic_year, semester)` pair is unique. Events reference that row through `semester_id`, and attendance filters use the linked academic year and semester rather than deriving an academic year from the event date. Semester choices such as `1st Semester`, `2nd Semester`, and `Summer Class` can therefore coexist within the same academic year.

Creating an academic year from Academic Terms creates its `1st Semester`, `2nd Semester`, and `Summer Class` rows together, with dates and fund amounts configured independently for each. If the new year is made active, exactly one of those semesters must be selected as the active semester; creating a year without activating it leaves the current active semester unchanged.

### Database backup and restore

Administrators can download a full MySQL backup from **Upload CSV → Backup Database**. A copy is also retained on the server in `Documents/Department System Backups` (or the folder configured with `DATABASE_BACKUP_DIR`). The host must have the MySQL `mysqldump` and `mysql` command-line clients available on `PATH` or in the standard MySQL Server `bin` folder. Treat these files as sensitive student and financial records.

**Restore Database** replaces all current tables and data with the selected `.sql` snapshot. It requires typing `RESTORE`, accepts a MySQL dump identifying the configured database, and first creates a verified safety backup of the current database in the same backup folder. If the selected dump fails, the app attempts to restore that safety copy and reports the safety-backup location. If both restore and automatic recovery fail, stop using the app and use the retained safety dump for manual recovery. Perform restores when other users are not using the system. Restore requires database credentials with privileges to drop and recreate database objects.
