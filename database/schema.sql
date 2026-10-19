CREATE DATABASE IF NOT EXISTS department_system
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;
USE department_system;

CREATE TABLE IF NOT EXISTS admins (
    admin_id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(80) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS students (
    id INT AUTO_INCREMENT PRIMARY KEY,
    student_id VARCHAR(32) NULL UNIQUE,
    firstname VARCHAR(100) NOT NULL,
    lastname VARCHAR(100) NOT NULL,
    course VARCHAR(50) NOT NULL,
    year_level VARCHAR(20) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'Active',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_students_name (lastname, firstname),
    INDEX idx_students_status (status)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS school_terms (
    id INT AUTO_INCREMENT PRIMARY KEY,
    academic_year VARCHAR(20) NOT NULL,
    semester VARCHAR(20) NOT NULL,
    start_date DATE NULL,
    end_date DATE NULL,
    fund_amount DECIMAL(10, 2) NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE KEY uq_school_term (academic_year, semester)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS system_settings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    academic_year VARCHAR(20) NULL,
    semester VARCHAR(20) NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS events (
    event_id INT AUTO_INCREMENT PRIMARY KEY,
    semester_id INT NULL,
    event_name VARCHAR(150) NOT NULL,
    event_date DATE NOT NULL,
    login_time TIME NULL,
    logout_time TIME NULL,
    login_cutoff_time TIME NULL,
    logout_cutoff_time TIME NULL,
    grace_period INT NULL DEFAULT 0,
    absent_fine DECIMAL(10, 2) NOT NULL DEFAULT 0,
    late_fine DECIMAL(10, 2) NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_events_date (event_date),
    INDEX idx_events_semester (semester_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS student_funds (
    id INT AUTO_INCREMENT PRIMARY KEY,
    student_id VARCHAR(32) NOT NULL,
    semester_id INT NULL,
    fund_id INT NULL,
    amount_due DECIMAL(10, 2) NOT NULL DEFAULT 0,
    assessed_amount DECIMAL(10, 2) NULL,
    paid_amount DECIMAL(10, 2) NOT NULL DEFAULT 0,
    is_semester_fund BOOLEAN NOT NULL DEFAULT FALSE,
    description VARCHAR(255) NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_student_funds_student (student_id),
    INDEX idx_student_funds_semester (semester_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS fines (
    fine_id INT AUTO_INCREMENT PRIMARY KEY,
    student_id VARCHAR(32) NOT NULL,
    semester_id INT NULL,
    event_id INT NULL,
    fine_type VARCHAR(50) NULL,
    amount DECIMAL(10, 2) NOT NULL DEFAULT 0,
    assessed_amount DECIMAL(10, 2) NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_fine (student_id, event_id, fine_type),
    INDEX idx_fines_student (student_id),
    INDEX idx_fines_event (event_id),
    INDEX idx_fines_semester (semester_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS attendance (
    id INT AUTO_INCREMENT PRIMARY KEY,
    event_id INT NOT NULL,
    semester_id INT NULL,
    student_id INT NOT NULL,
    status VARCHAR(32) NOT NULL,
    timestamp DATETIME NOT NULL,
    INDEX idx_attendance_event (event_id),
    INDEX idx_attendance_student (student_id),
    INDEX idx_attendance_semester (semester_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS semester_enrollments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    semester_id INT NOT NULL,
    student_id INT NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'enrolled',
    enrolled_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dropped_at TIMESTAMP NULL,
    UNIQUE KEY uq_semester_enrollment (semester_id, student_id),
    INDEX idx_semester_enrollments_student (student_id),
    INDEX idx_semester_enrollments_status (semester_id, status)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS transactions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    student_id VARCHAR(32) NOT NULL,
    semester_id INT NULL,
    transaction_type VARCHAR(30) NOT NULL,
    payment_type VARCHAR(30) NOT NULL,
    amount DECIMAL(10, 2) NOT NULL,
    academic_year VARCHAR(20) NOT NULL,
    semester VARCHAR(20) NOT NULL,
    created_by VARCHAR(80) NOT NULL,
    transaction_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_transactions_student (student_id),
    INDEX idx_transactions_date (transaction_date),
    INDEX idx_transactions_semester (semester_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS transaction_balance_snapshots (
    transaction_id INT PRIMARY KEY,
    transaction_type VARCHAR(16) NOT NULL,
    snapshot JSON NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS fine_payment_allocations (
    allocation_id INT AUTO_INCREMENT PRIMARY KEY,
    transaction_id INT NOT NULL,
    source_fine_id INT NOT NULL,
    student_id VARCHAR(32) NOT NULL,
    event_id INT NOT NULL,
    fine_type VARCHAR(50) NOT NULL,
    amount_paid DECIMAL(10, 2) NOT NULL,
    UNIQUE KEY uq_fine_payment_source (transaction_id, source_fine_id),
    INDEX idx_fine_payment_identity (student_id, event_id, fine_type)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS exemption_lists (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    year_level VARCHAR(32) NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS exemption_list_students (
    list_id INT NOT NULL,
    student_id INT NOT NULL,
    PRIMARY KEY (list_id, student_id),
    INDEX idx_exemption_list_students_student (student_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS event_exemptions (
    event_id INT NOT NULL,
    student_id INT NOT NULL,
    PRIMARY KEY (event_id, student_id),
    INDEX idx_event_exemptions_student (student_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS paper_attendance (
    event_id INT NOT NULL,
    semester_id INT NULL,
    student_id INT NOT NULL,
    status VARCHAR(16) NOT NULL,
    recorded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (event_id, student_id),
    INDEX idx_paper_attendance_student (student_id),
    INDEX idx_paper_attendance_semester (semester_id)
) ENGINE=InnoDB;
