USE department_system;

-- Demo credentials only. Change this password before using the system.
INSERT INTO admins (username, password)
VALUES (
    'admin',
    'scrypt:32768:8:1$YpABaiKutUz2wpqz$ca040ced777db99cd6603cce843b2516b5c02805577e6cc5c334ac8837f900db8ece304035d788e416de52e2cf0a4d39894b91035cc387db221d3bc55d4e6f54'
)
ON DUPLICATE KEY UPDATE username = VALUES(username);

-- Synthetic demo records; no production student data is included.
INSERT INTO school_terms (academic_year, semester, start_date, end_date, is_active)
VALUES ('2025-2026', '1st', '2025-08-01', '2025-12-20', TRUE)
ON DUPLICATE KEY UPDATE is_active = VALUES(is_active);

INSERT INTO students (student_id, firstname, lastname, course, year_level, status)
VALUES
    ('DEMO-0001', 'ALEX', 'SANTOS', 'BSIS', '1st Year', 'Active'),
    ('DEMO-0002', 'JAMIE', 'REYES', 'BSCS', '2nd Year', 'Active')
ON DUPLICATE KEY UPDATE status = VALUES(status);

INSERT INTO events (
    event_name, event_date, login_time, logout_time,
    login_cutoff_time, logout_cutoff_time, grace_period,
    absent_fine, late_fine
)
VALUES (
    'Demo Department Assembly', '2025-10-15', '08:00:00', '17:00:00',
    '08:15:00', '17:15:00', 10, 100.00, 25.00
);

INSERT INTO student_funds (student_id, amount_due, description)
VALUES
    ('DEMO-0001', 500.00, 'Demo department fund'),
    ('DEMO-0002', 500.00, 'Demo department fund');

INSERT INTO fines (student_id, event_id, fine_type, amount)
SELECT 'DEMO-0002', event_id, 'late', 25.00
FROM events
WHERE event_name = 'Demo Department Assembly'
  AND event_date = '2025-10-15'
LIMIT 1;
