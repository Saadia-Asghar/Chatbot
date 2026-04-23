-- Healthcare Resource Optimization System
-- 3NF-normalized schema. Table and column names follow Phase 1 spec exactly.

PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS OrganRequests;
DROP TABLE IF EXISTS InventoryTable;
DROP TABLE IF EXISTS PatientsTable;
DROP TABLE IF EXISTS DonorsTable;
DROP TABLE IF EXISTS HospitalsTable;

CREATE TABLE HospitalsTable (
    HospitalID          INTEGER PRIMARY KEY AUTOINCREMENT,
    Name                TEXT    NOT NULL,
    Location            TEXT    NOT NULL,
    AverageWeeklyUsage  REAL    NOT NULL CHECK (AverageWeeklyUsage >= 0)
);

CREATE TABLE InventoryTable (
    InventoryID  INTEGER PRIMARY KEY AUTOINCREMENT,
    HospitalID   INTEGER NOT NULL,
    BloodType    TEXT    NOT NULL,
    CurrentUnits INTEGER NOT NULL CHECK (CurrentUnits >= 0),
    LastUpdated  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (HospitalID) REFERENCES HospitalsTable(HospitalID),
    UNIQUE (HospitalID, BloodType)
);

CREATE TABLE PatientsTable (
    PatientID         INTEGER PRIMARY KEY AUTOINCREMENT,
    HospitalID        INTEGER NOT NULL,
    Name              TEXT    NOT NULL,
    Condition         TEXT    NOT NULL,
    HemoglobinLevel   REAL    NOT NULL,
    SurgeryScheduled  INTEGER NOT NULL CHECK (SurgeryScheduled IN (0, 1)),
    RiskScore         INTEGER NOT NULL CHECK (RiskScore BETWEEN 0 AND 10),
    FOREIGN KEY (HospitalID) REFERENCES HospitalsTable(HospitalID)
);

CREATE TABLE DonorsTable (
    DonorID           INTEGER PRIMARY KEY AUTOINCREMENT,
    Name              TEXT    NOT NULL,
    BloodType         TEXT    NOT NULL,
    EligibilityStatus TEXT    NOT NULL CHECK (EligibilityStatus IN ('Eligible', 'Deferred', 'Ineligible')),
    Location          TEXT    NOT NULL
);

-- Kept from prior phase for the transplant-priority intent.
CREATE TABLE OrganRequests (
    RequestID    INTEGER PRIMARY KEY AUTOINCREMENT,
    PatientID    INTEGER NOT NULL,
    OrganType    TEXT    NOT NULL,
    UrgencyScore INTEGER NOT NULL CHECK (UrgencyScore BETWEEN 0 AND 10),
    WaitTime     INTEGER NOT NULL CHECK (WaitTime >= 0),
    FOREIGN KEY (PatientID) REFERENCES PatientsTable(PatientID)
);

-- ---------------------------------------------------------------
-- Test data
-- Hospital 1 ("City General") is deliberately stocked low compared to its
-- weekly usage so the "Explain Why" feature has something to report.
-- ---------------------------------------------------------------

INSERT INTO HospitalsTable (HospitalID, Name, Location, AverageWeeklyUsage) VALUES
    (1, 'City General',         'Mumbai', 40),
    (2, 'Green Valley Medical', 'Pune',   25);

-- Hospital 1 is deliberately stocked below its average weekly usage (34 < 40)
-- so the "Explain Why" feature triggers the at-risk branch.
INSERT INTO InventoryTable (HospitalID, BloodType, CurrentUnits) VALUES
    (1, 'O-',  2),
    (1, 'O+',  8),
    (1, 'A+',  5),
    (1, 'A-',  4),
    (1, 'B+',  9),
    (1, 'AB+', 6),
    (2, 'O+',  30),
    (2, 'A+',  25);

INSERT INTO PatientsTable (HospitalID, Name, Condition, HemoglobinLevel, SurgeryScheduled, RiskScore) VALUES
    (1, 'Asha Patel',   'Anemia',          7.5, 1, 9),
    (1, 'Rohit Sharma', 'Post-surgery',   10.2, 0, 6),
    (1, 'Meera Iyer',   'Kidney failure',  8.1, 1, 9),
    (1, 'Sanjay Gupta', 'Liver cirrhosis', 9.0, 0, 8),
    (2, 'Priya Nair',   'Thalassemia',     6.8, 1, 10);

INSERT INTO DonorsTable (Name, BloodType, EligibilityStatus, Location) VALUES
    ('Ravi Menon',  'O-',  'Eligible',   'Mumbai'),
    ('Kiran Das',   'O+',  'Eligible',   'Mumbai'),
    ('Ananya Roy',  'A-',  'Deferred',   'Pune'),
    ('Vikas Singh', 'B+',  'Eligible',   'Mumbai'),
    ('Neha Kapoor', 'AB+', 'Ineligible', 'Pune');

INSERT INTO OrganRequests (PatientID, OrganType, UrgencyScore, WaitTime) VALUES
    (3, 'Kidney', 9, 120),
    (4, 'Liver',  8,  60),
    (1, 'Kidney', 7,  30);
