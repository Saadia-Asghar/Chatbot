-- =====================================================================
-- DonorBridge — Healthcare Resource Optimization System
-- Schema follows the DonorBridge ERD
--   (https://github.com/shajiaalianwar55/DonorBridge)
-- 3NF, SQLite-compatible. Snake_case names matching the ERD exactly.
-- =====================================================================

PRAGMA foreign_keys = ON;

-- Drop in reverse-dependency order
DROP TABLE IF EXISTS QUERY_EXECUTION_LOG;
DROP TABLE IF EXISTS SQL_TEMPLATE;
DROP TABLE IF EXISTS INTENT_DETECTION;
DROP TABLE IF EXISTS CHAT_MESSAGE;
DROP TABLE IF EXISTS CHAT_SESSION;
DROP TABLE IF EXISTS TRANSPLANT;
DROP TABLE IF EXISTS MATCH_CANDIDATE;
DROP TABLE IF EXISTS ORGAN_OFFER;
DROP TABLE IF EXISTS BLOOD_INVENTORY;
DROP TABLE IF EXISTS BLOOD_UNIT;
DROP TABLE IF EXISTS BLOOD_DONATION;
DROP TABLE IF EXISTS ORGAN_REQUEST_DETAILS;
DROP TABLE IF EXISTS BLOOD_REQUEST_DETAILS;
DROP TABLE IF EXISTS REQUEST;
DROP TABLE IF EXISTS MEDICAL_RECORD;
DROP TABLE IF EXISTS PATIENT;
DROP TABLE IF EXISTS DONOR;
DROP TABLE IF EXISTS HOSPITAL;

-- =====================================================================
-- Core entities
-- =====================================================================

CREATE TABLE HOSPITAL (
    hospital_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    location      TEXT    NOT NULL,
    contact       TEXT
);

CREATE TABLE PATIENT (
    patient_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    hospital_id   INTEGER NOT NULL,
    full_name     TEXT    NOT NULL,
    age           INTEGER NOT NULL CHECK (age >= 0),
    gender        TEXT    NOT NULL CHECK (gender IN ('M','F','O')),
    blood_group   TEXT    NOT NULL,
    contact_info  TEXT,
    risk_score    REAL    NOT NULL DEFAULT 0 CHECK (risk_score BETWEEN 0 AND 10),
    created_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (hospital_id) REFERENCES HOSPITAL(hospital_id)
);

CREATE TABLE MEDICAL_RECORD (
    record_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id       INTEGER NOT NULL,
    diagnosis        TEXT    NOT NULL,
    severity_level   TEXT    NOT NULL CHECK (severity_level IN ('Mild','Moderate','Severe','Critical')),
    stage            TEXT,
    hemoglobin_level REAL    NOT NULL,
    updated_at       TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES PATIENT(patient_id)
);

CREATE TABLE DONOR (
    donor_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    hospital_id         INTEGER NOT NULL,
    full_name           TEXT    NOT NULL,
    age                 INTEGER NOT NULL CHECK (age BETWEEN 0 AND 120),
    blood_group         TEXT    NOT NULL,
    donor_type          TEXT    NOT NULL CHECK (donor_type IN ('Blood','Organ','Both')),
    contact_info        TEXT,
    availability_status TEXT    NOT NULL CHECK (availability_status IN ('Available','Unavailable')),
    eligibility_status  TEXT    NOT NULL CHECK (eligibility_status IN ('Eligible','Deferred','Ineligible')),
    last_donation_date  TEXT,
    FOREIGN KEY (hospital_id) REFERENCES HOSPITAL(hospital_id)
);

-- =====================================================================
-- Requests + subtype tables (one-to-one with REQUEST.request_id)
-- =====================================================================

CREATE TABLE REQUEST (
    request_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id    INTEGER NOT NULL,
    hospital_id   INTEGER NOT NULL,
    request_type  TEXT    NOT NULL CHECK (request_type IN ('Blood','Organ')),
    urgency_level INTEGER NOT NULL CHECK (urgency_level BETWEEN 1 AND 10),
    status        TEXT    NOT NULL CHECK (status IN ('Pending','Matched','Fulfilled','Cancelled')),
    request_date  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id)  REFERENCES PATIENT(patient_id),
    FOREIGN KEY (hospital_id) REFERENCES HOSPITAL(hospital_id)
);

CREATE TABLE BLOOD_REQUEST_DETAILS (
    request_id           INTEGER PRIMARY KEY,
    blood_group_required TEXT    NOT NULL,
    units_required       INTEGER NOT NULL CHECK (units_required > 0),
    required_by          TEXT    NOT NULL,
    FOREIGN KEY (request_id) REFERENCES REQUEST(request_id) ON DELETE CASCADE
);

CREATE TABLE ORGAN_REQUEST_DETAILS (
    request_id           INTEGER PRIMARY KEY,
    organ_type_required  TEXT    NOT NULL,
    max_wait_time_days   REAL    NOT NULL CHECK (max_wait_time_days >= 0),
    hla_notes            TEXT,
    FOREIGN KEY (request_id) REFERENCES REQUEST(request_id) ON DELETE CASCADE
);

-- =====================================================================
-- Donations / units / inventory / organ offers
-- =====================================================================

CREATE TABLE BLOOD_DONATION (
    blood_donation_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    donor_id            INTEGER NOT NULL,
    donation_date       TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    quantity_donated_ml INTEGER NOT NULL CHECK (quantity_donated_ml > 0),
    outcome             TEXT    NOT NULL CHECK (outcome IN ('Successful','Discarded','InProgress')),
    FOREIGN KEY (donor_id) REFERENCES DONOR(donor_id)
);

CREATE TABLE BLOOD_UNIT (
    blood_unit_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    blood_donation_id INTEGER NOT NULL,
    blood_group       TEXT    NOT NULL,
    volume_ml         INTEGER NOT NULL CHECK (volume_ml > 0),
    expiry_date       TEXT    NOT NULL,
    unit_status       TEXT    NOT NULL CHECK (unit_status IN ('Available','Reserved','Used','Expired')),
    FOREIGN KEY (blood_donation_id) REFERENCES BLOOD_DONATION(blood_donation_id)
);

CREATE TABLE BLOOD_INVENTORY (
    inventory_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    hospital_id               INTEGER NOT NULL,
    blood_group               TEXT    NOT NULL,
    available_units_summary   INTEGER NOT NULL CHECK (available_units_summary >= 0),
    last_updated              TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (hospital_id, blood_group),
    FOREIGN KEY (hospital_id) REFERENCES HOSPITAL(hospital_id)
);

CREATE TABLE ORGAN_OFFER (
    organ_offer_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    donor_id            INTEGER NOT NULL,
    organ_type          TEXT    NOT NULL,
    availability_status TEXT    NOT NULL CHECK (availability_status IN ('Available','Reserved','Used')),
    retrieval_date      TEXT,
    medical_clearance   TEXT    NOT NULL CHECK (medical_clearance IN ('Cleared','Pending','Rejected')),
    FOREIGN KEY (donor_id) REFERENCES DONOR(donor_id)
);

-- =====================================================================
-- Match + transplant
-- =====================================================================

CREATE TABLE MATCH_CANDIDATE (
    match_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id          INTEGER NOT NULL,
    match_type          TEXT    NOT NULL CHECK (match_type IN ('Blood','Organ')),
    blood_unit_id       INTEGER,
    organ_offer_id      INTEGER,
    compatibility_score REAL    NOT NULL CHECK (compatibility_score BETWEEN 0 AND 1),
    priority_level      TEXT    NOT NULL CHECK (priority_level IN ('Low','Medium','High','Critical')),
    match_status        TEXT    NOT NULL CHECK (match_status IN ('Proposed','Accepted','Rejected','Completed')),
    match_date          TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (request_id)     REFERENCES REQUEST(request_id),
    FOREIGN KEY (blood_unit_id)  REFERENCES BLOOD_UNIT(blood_unit_id),
    FOREIGN KEY (organ_offer_id) REFERENCES ORGAN_OFFER(organ_offer_id),
    CHECK (
        (match_type = 'Blood' AND blood_unit_id  IS NOT NULL AND organ_offer_id IS NULL) OR
        (match_type = 'Organ' AND organ_offer_id IS NOT NULL AND blood_unit_id  IS NULL)
    )
);

CREATE TABLE TRANSPLANT (
    transplant_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id         INTEGER NOT NULL UNIQUE,
    transplant_date  TEXT    NOT NULL,
    surgeon_name     TEXT    NOT NULL,
    outcome          TEXT    NOT NULL CHECK (outcome IN ('Successful','Failed','InProgress')),
    FOREIGN KEY (match_id) REFERENCES MATCH_CANDIDATE(match_id)
);

-- =====================================================================
-- Chatbot subsystem (this is what the chatbot writes to)
-- =====================================================================

CREATE TABLE CHAT_SESSION (
    chat_session_id INTEGER PRIMARY KEY AUTOINCREMENT,
    hospital_id     INTEGER NOT NULL,
    user_role       TEXT    NOT NULL CHECK (user_role IN ('Doctor','Nurse','Admin','Coordinator')),
    started_at      TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (hospital_id) REFERENCES HOSPITAL(hospital_id)
);

CREATE TABLE CHAT_MESSAGE (
    message_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_session_id INTEGER NOT NULL,
    sender_type     TEXT    NOT NULL CHECK (sender_type IN ('User','Bot')),
    message_text    TEXT    NOT NULL,
    created_at      TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (chat_session_id) REFERENCES CHAT_SESSION(chat_session_id)
);

CREATE TABLE INTENT_DETECTION (
    intent_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id       INTEGER NOT NULL,
    intent_code      TEXT    NOT NULL,
    confidence_score REAL    NOT NULL DEFAULT 1.0,
    detected_at      TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (message_id) REFERENCES CHAT_MESSAGE(message_id)
);

CREATE TABLE SQL_TEMPLATE (
    template_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    intent_code     TEXT    NOT NULL,
    sql_text        TEXT    NOT NULL,
    allowed_params  TEXT    NOT NULL,
    active_flag     INTEGER NOT NULL DEFAULT 1 CHECK (active_flag IN (0,1))
);

CREATE TABLE QUERY_EXECUTION_LOG (
    execution_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    intent_id        INTEGER NOT NULL,
    template_id      INTEGER NOT NULL,
    param_json       TEXT    NOT NULL,
    execution_status TEXT    NOT NULL CHECK (execution_status IN ('OK','Error','Empty')),
    rows_returned    INTEGER NOT NULL DEFAULT 0,
    executed_at      TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (intent_id)   REFERENCES INTENT_DETECTION(intent_id),
    FOREIGN KEY (template_id) REFERENCES SQL_TEMPLATE(template_id)
);

-- =====================================================================
-- SEED DATA
-- City General (id 1) is intentionally low on supply / has pending
-- requests so the EXPLAIN_ALERT intent has something to report.
-- =====================================================================

INSERT INTO HOSPITAL (hospital_id, name, location, contact) VALUES
    (1, 'City General Hospital',  'Mumbai',    '+91-22-1111-1111'),
    (2, 'Green Valley Medical',   'Pune',      '+91-20-2222-2222'),
    (3, 'Sunrise Care Center',    'Bengaluru', '+91-80-3333-3333');

INSERT INTO PATIENT (patient_id, hospital_id, full_name, age, gender, blood_group, contact_info, risk_score) VALUES
    (1, 1, 'Asha Patel',     34, 'F', 'O-',  'asha@example.com',   9.0),
    (2, 1, 'Rohit Sharma',   52, 'M', 'A+',  'rohit@example.com',  6.0),
    (3, 1, 'Meera Iyer',     45, 'F', 'B+',  'meera@example.com',  9.5),
    (4, 1, 'Sanjay Gupta',   60, 'M', 'AB+', 'sanjay@example.com', 8.0),
    (5, 2, 'Priya Nair',     12, 'F', 'O+',  'priya@example.com',  10.0),
    (6, 2, 'Arjun Verma',    29, 'M', 'B-',  'arjun@example.com',  4.0),
    (7, 3, 'Kavya Reddy',    38, 'F', 'A-',  'kavya@example.com',  7.5);

INSERT INTO MEDICAL_RECORD (patient_id, diagnosis, severity_level, stage, hemoglobin_level) VALUES
    (1, 'Severe Anemia',           'Severe',   'II',   7.5),
    (2, 'Post-surgery recovery',   'Moderate', NULL,  10.2),
    (3, 'Chronic kidney failure',  'Critical', 'V',    8.1),
    (4, 'Liver cirrhosis',         'Severe',   'C',    9.0),
    (5, 'Beta-thalassemia major',  'Critical', NULL,   6.8),
    (6, 'Mild iron deficiency',    'Mild',     NULL,  11.5),
    (7, 'Aplastic anemia',         'Severe',   NULL,   8.3);

INSERT INTO DONOR (donor_id, hospital_id, full_name, age, blood_group, donor_type, contact_info, availability_status, eligibility_status, last_donation_date) VALUES
    (1, 1, 'Ravi Menon',   28, 'O-',  'Blood', 'ravi@example.com',   'Available',   'Eligible',   '2026-01-15'),
    (2, 1, 'Kiran Das',    34, 'O+',  'Both',  'kiran@example.com',  'Available',   'Eligible',   '2026-02-10'),
    (3, 2, 'Ananya Roy',   41, 'A-',  'Blood', 'ananya@example.com', 'Unavailable', 'Deferred',   '2025-12-05'),
    (4, 1, 'Vikas Singh',  30, 'B+',  'Blood', 'vikas@example.com',  'Available',   'Eligible',   '2026-03-01'),
    (5, 2, 'Neha Kapoor',  47, 'AB+', 'Organ', 'neha@example.com',   'Available',   'Ineligible', NULL),
    (6, 3, 'Imran Khan',   33, 'B-',  'Both',  'imran@example.com',  'Available',   'Eligible',   '2026-02-20'),
    (7, 3, 'Sara Pillai',  26, 'A+',  'Blood', 'sara@example.com',   'Available',   'Eligible',   '2026-03-12');

-- Requests
INSERT INTO REQUEST (request_id, patient_id, hospital_id, request_type, urgency_level, status, request_date) VALUES
    (1, 1, 1, 'Blood', 9, 'Pending',   '2026-04-20 09:00:00'),
    (2, 3, 1, 'Organ', 9, 'Matched',   '2026-04-15 10:00:00'),
    (3, 4, 1, 'Organ', 8, 'Pending',   '2026-04-22 12:00:00'),
    (4, 5, 2, 'Blood', 10,'Pending',   '2026-04-23 08:30:00'),
    (5, 7, 3, 'Blood', 7, 'Pending',   '2026-04-21 14:00:00');

INSERT INTO BLOOD_REQUEST_DETAILS (request_id, blood_group_required, units_required, required_by) VALUES
    (1, 'O-', 4, '2026-04-25'),
    (4, 'O+', 6, '2026-04-24'),
    (5, 'A-', 2, '2026-04-28');

INSERT INTO ORGAN_REQUEST_DETAILS (request_id, organ_type_required, max_wait_time_days, hla_notes) VALUES
    (2, 'Kidney', 30,  'HLA-A2, HLA-B7 preferred'),
    (3, 'Liver',  60,  'Blood-group compatible only');

-- Blood donations + units
INSERT INTO BLOOD_DONATION (blood_donation_id, donor_id, donation_date, quantity_donated_ml, outcome) VALUES
    (1, 1, '2026-01-15', 450, 'Successful'),
    (2, 2, '2026-02-10', 450, 'Successful'),
    (3, 4, '2026-03-01', 450, 'Successful'),
    (4, 6, '2026-02-20', 450, 'Successful'),
    (5, 7, '2026-03-12', 450, 'Successful');

INSERT INTO BLOOD_UNIT (blood_unit_id, blood_donation_id, blood_group, volume_ml, expiry_date, unit_status) VALUES
    (1, 1, 'O-',  450, '2026-05-15', 'Available'),
    (2, 2, 'O+',  450, '2026-06-10', 'Available'),
    (3, 3, 'B+',  450, '2026-07-01', 'Available'),
    (4, 4, 'B-',  450, '2026-06-20', 'Available'),
    (5, 5, 'A+',  450, '2026-07-12', 'Available');

-- Inventory snapshots per hospital. Hospital 1 is short of O- relative to demand.
INSERT INTO BLOOD_INVENTORY (hospital_id, blood_group, available_units_summary) VALUES
    (1, 'O-',  2),
    (1, 'O+',  8),
    (1, 'A+',  5),
    (1, 'A-',  4),
    (1, 'B+',  9),
    (1, 'AB+', 6),
    (2, 'O+',  30),
    (2, 'A+',  25),
    (2, 'B-',  12),
    (3, 'A-',  3),
    (3, 'O+',  18);

-- Organ offers
INSERT INTO ORGAN_OFFER (organ_offer_id, donor_id, organ_type, availability_status, retrieval_date, medical_clearance) VALUES
    (1, 5, 'Kidney', 'Available', '2026-04-18', 'Cleared'),
    (2, 2, 'Liver',  'Reserved',  '2026-04-19', 'Cleared'),
    (3, 6, 'Kidney', 'Available', NULL,         'Pending');

-- Match candidates
INSERT INTO MATCH_CANDIDATE (match_id, request_id, match_type, blood_unit_id, organ_offer_id, compatibility_score, priority_level, match_status) VALUES
    (1, 1, 'Blood', 1,    NULL, 0.98, 'Critical', 'Proposed'),
    (2, 2, 'Organ', NULL, 1,    0.91, 'High',     'Accepted'),
    (3, 4, 'Blood', 2,    NULL, 0.95, 'Critical', 'Proposed'),
    (4, 5, 'Blood', 5,    NULL, 0.80, 'Medium',   'Proposed'),
    (5, 3, 'Organ', NULL, 2,    0.85, 'High',     'Proposed');

-- Transplant (only for the accepted match)
INSERT INTO TRANSPLANT (match_id, transplant_date, surgeon_name, outcome) VALUES
    (2, '2026-04-25', 'Dr. R. Mehta', 'InProgress');

-- Pre-register the SQL templates the chatbot uses (matches INTENT_TO_SQL).
-- Kept for ERD compliance + auditability.
INSERT INTO SQL_TEMPLATE (intent_code, sql_text, allowed_params, active_flag) VALUES
    ('CHECK_INVENTORY_ALL',
        'SELECT bi.blood_group, bi.available_units_summary, h.name FROM BLOOD_INVENTORY bi JOIN HOSPITAL h ON h.hospital_id = bi.hospital_id WHERE bi.hospital_id = ? ORDER BY bi.blood_group LIMIT 10',
        'hospital_id', 1),
    ('CHECK_INVENTORY_BY_TYPE',
        'SELECT bi.blood_group, bi.available_units_summary, h.name FROM BLOOD_INVENTORY bi JOIN HOSPITAL h ON h.hospital_id = bi.hospital_id WHERE bi.hospital_id = ? AND bi.blood_group = ? LIMIT 10',
        'hospital_id, blood_group', 1),
    ('CHECK_INVENTORY_BY_FAMILY',
        'SELECT bi.blood_group, bi.available_units_summary, h.name FROM BLOOD_INVENTORY bi JOIN HOSPITAL h ON h.hospital_id = bi.hospital_id WHERE bi.hospital_id = ? AND bi.blood_group IN (?, ?) ORDER BY bi.blood_group LIMIT 10',
        'hospital_id, blood_group_positive, blood_group_negative', 1),
    ('LIST_HOSPITALS',
        'SELECT hospital_id, name, location, COALESCE(contact, '''') FROM HOSPITAL ORDER BY hospital_id LIMIT 10',
        '(none)', 1),
    ('LIST_PATIENTS',
        'SELECT p.full_name, p.age, p.gender, p.blood_group, p.risk_score FROM PATIENT p WHERE p.hospital_id = ? ORDER BY p.risk_score DESC, p.full_name ASC LIMIT 10',
        'hospital_id', 1),
    ('GET_DONATIONS',
        'SELECT bd.blood_donation_id, d.full_name, d.blood_group, bd.donation_date, bd.quantity_donated_ml, bd.outcome FROM BLOOD_DONATION bd JOIN DONOR d ON d.donor_id = bd.donor_id WHERE d.hospital_id = ? ORDER BY date(bd.donation_date) DESC LIMIT 10',
        'hospital_id', 1),
    ('GET_HIGH_RISK_PATIENTS',
        'SELECT p.full_name, mr.diagnosis, mr.hemoglobin_level, p.risk_score, mr.severity_level FROM PATIENT p LEFT JOIN MEDICAL_RECORD mr ON mr.patient_id = p.patient_id WHERE p.hospital_id = ? AND p.risk_score > ? ORDER BY p.risk_score DESC LIMIT 10',
        'hospital_id, risk_threshold', 1),
    ('GET_TRANSPLANT_PRIORITY',
        'SELECT p.full_name, ord.organ_type_required, r.urgency_level, ord.max_wait_time_days, r.status FROM REQUEST r JOIN ORGAN_REQUEST_DETAILS ord ON ord.request_id = r.request_id JOIN PATIENT p ON p.patient_id = r.patient_id WHERE r.hospital_id = ? ORDER BY r.urgency_level DESC, ord.max_wait_time_days ASC LIMIT 10',
        'hospital_id', 1),
    ('GET_DONORS',
        'SELECT full_name, blood_group, eligibility_status, availability_status, donor_type FROM DONOR WHERE hospital_id = ? AND eligibility_status = ''Eligible'' AND availability_status = ''Available'' ORDER BY blood_group LIMIT 10',
        'hospital_id', 1),
    ('GET_PENDING_REQUESTS',
        'SELECT r.request_id, r.request_type, p.full_name, r.urgency_level, r.status FROM REQUEST r JOIN PATIENT p ON p.patient_id = r.patient_id WHERE r.hospital_id = ? AND r.status = ''Pending'' ORDER BY r.urgency_level DESC LIMIT 10',
        'hospital_id', 1),
    ('GET_EXPIRING_UNITS',
        'SELECT bu.blood_group, bu.volume_ml, bu.expiry_date, bu.unit_status FROM BLOOD_UNIT bu WHERE bu.unit_status = ''Available'' ORDER BY date(bu.expiry_date) ASC LIMIT 10',
        '(none)', 1),
    ('GET_MATCH_CANDIDATES',
        'SELECT mc.match_id, mc.match_type, mc.compatibility_score, mc.priority_level, mc.match_status, p.full_name FROM MATCH_CANDIDATE mc JOIN REQUEST r ON r.request_id = mc.request_id JOIN PATIENT p ON p.patient_id = r.patient_id WHERE r.hospital_id = ? ORDER BY mc.compatibility_score DESC LIMIT 10',
        'hospital_id', 1),
    ('GET_TRANSPLANT_HISTORY',
        'SELECT t.transplant_id, t.transplant_date, t.surgeon_name, t.outcome, p.full_name, ord.organ_type_required FROM TRANSPLANT t JOIN MATCH_CANDIDATE mc ON mc.match_id = t.match_id JOIN REQUEST r ON r.request_id = mc.request_id JOIN PATIENT p ON p.patient_id = r.patient_id JOIN ORGAN_REQUEST_DETAILS ord ON ord.request_id = r.request_id WHERE r.hospital_id = ? ORDER BY date(t.transplant_date) DESC LIMIT 10',
        'hospital_id', 1),
    ('EXPLAIN_ALERT_INVENTORY',
        'SELECT blood_group, available_units_summary FROM BLOOD_INVENTORY WHERE hospital_id = ? ORDER BY available_units_summary ASC LIMIT 10',
        'hospital_id', 1),
    ('EXPLAIN_ALERT_PENDING',
        'SELECT brd.blood_group_required, SUM(brd.units_required) FROM REQUEST r JOIN BLOOD_REQUEST_DETAILS brd ON brd.request_id = r.request_id WHERE r.hospital_id = ? AND r.status = ''Pending'' GROUP BY brd.blood_group_required',
        'hospital_id', 1),
    ('EXPLAIN_ALERT_HOSPITAL',
        'SELECT name FROM HOSPITAL WHERE hospital_id = ?',
        'hospital_id', 1);
