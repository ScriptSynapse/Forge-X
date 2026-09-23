-- =====================================================================
-- FORGE-X : Forensic Operations, Records, Governance & Evidence Exchange
-- File   : 02_tables.sql
-- Purpose: Complete relational schema — 21 tables covering the full
--          evidence lifecycle: Case -> Person -> Device -> Evidence ->
--          Hash -> Chain of Custody -> Examination -> Report -> Audit.
-- Engine : MySQL 8.0+ (InnoDB, utf8mb4)
-- Depends: 01_create_database.sql must be run first.
--
-- NAMING CONVENTION
--   snake_case everywhere. Every surrogate PK is <singular_noun>_id.
--   Every FK column is named identically to the PK it references
--   (e.g. cases.case_type_id -> case_types.case_type_id) so joins are
--   self-documenting.
--
-- TABLE ORDER
--   Tables are created in strict dependency order (no forward
--   references): lookup/reference tables first, then entities that
--   depend on them, then junction tables, then evidence-lifecycle
--   tables, then reporting/audit tables. This order is also a valid
--   topological sort of the foreign-key graph, so this script runs
--   top-to-bottom with no deferred constraint issues.
--
-- DELETE POLICY (forensic integrity rule applied consistently)
--   Core evidentiary tables (cases, devices, evidence, evidence_hashes,
--   chain_of_custody, evidence_examinations, forensic_reports,
--   report_versions, case_timeline) are protected with ON DELETE RESTRICT
--   everywhere a deletion could sever a chain-of-custody, hash, exam, or
--   reporting trail — including evidence's own "weak entity" children.
--   Concretely: you cannot delete an evidence row while it still has
--   hash records, custody history, or examinations attached; you must
--   not be able to lose a custody trail as a side effect of deleting
--   something else. Records are never meant to be hard-deleted in this
--   system — status/enum columns model lifecycle state instead (e.g.
--   devices.device_status = 'disposed'). ON DELETE CASCADE is reserved
--   for pure junction rows only (case_investigators, case_persons),
--   which are meaningless without their case and safe to remove
--   automatically — and only because a case can itself only be deleted
--   once it has zero devices/evidence/reports/timeline rows (RESTRICT
--   everywhere else already guarantees that).
-- =====================================================================

USE forge_x;

-- Defensive: ensures THIS session sends/receives utf8mb4 regardless of
-- how the client was invoked (protects against a classic gotcha: running
-- `mysql -u root < this_file.sql` without --default-character-set=utf8mb4
-- silently corrupts any non-ASCII literal in this file via latin1
-- misinterpretation at write time -- discovered and fixed during Step 6
-- backend integration testing).
SET NAMES utf8mb4;

-- =====================================================================
-- 1. roles  — lookup table of system/investigative roles
-- =====================================================================
CREATE TABLE roles (
    role_id           SMALLINT UNSIGNED NOT NULL AUTO_INCREMENT,
    role_name         VARCHAR(50)       NOT NULL,
    role_description  VARCHAR(255)      NULL,
    created_at        DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (role_id),
    CONSTRAINT uq_roles_role_name UNIQUE (role_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='System roles (e.g. Administrator, Lead Investigator, Forensic Analyst, Auditor)';

-- =====================================================================
-- 2. departments — lookup table of organizational departments/units
-- =====================================================================
CREATE TABLE departments (
    department_id     SMALLINT UNSIGNED NOT NULL AUTO_INCREMENT,
    department_name   VARCHAR(100)      NOT NULL,
    department_code   VARCHAR(20)       NOT NULL,
    created_at        DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (department_id),
    CONSTRAINT uq_departments_name UNIQUE (department_name),
    CONSTRAINT uq_departments_code UNIQUE (department_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Organizational departments/units a user belongs to (e.g. Cyber Crime Cell, Digital Forensics Lab)';

-- =====================================================================
-- 3. locations — physical locations: evidence lockers, labs, sites, etc.
-- =====================================================================
CREATE TABLE locations (
    location_id       INT UNSIGNED NOT NULL AUTO_INCREMENT,
    location_name     VARCHAR(150) NOT NULL,
    location_type     ENUM('evidence_locker','lab','storage_facility','field_site','court','other')
                                    NOT NULL DEFAULT 'other',
    address_line      VARCHAR(255) NULL,
    city              VARCHAR(100) NULL,
    state             VARCHAR(100) NULL,
    country           VARCHAR(100) NOT NULL DEFAULT 'India',
    postal_code       VARCHAR(20)  NULL,
    created_at        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (location_id),
    CONSTRAINT uq_locations_name_city UNIQUE (location_name, city)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Physical locations used for jurisdiction, seizure, storage, and custody transfer';

-- =====================================================================
-- 4. case_types — lookup table of forensic case categories
-- =====================================================================
CREATE TABLE case_types (
    case_type_id      SMALLINT UNSIGNED NOT NULL AUTO_INCREMENT,
    type_name         VARCHAR(100)      NOT NULL,
    type_description  VARCHAR(255)      NULL,
    created_at        DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (case_type_id),
    CONSTRAINT uq_case_types_name UNIQUE (type_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Case category lookup (e.g. Cybercrime, Data Breach, Fraud, Malware Incident, IP Theft)';

-- =====================================================================
-- 5. users — system users (investigators, analysts, admins, auditors)
-- =====================================================================
CREATE TABLE users (
    user_id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    badge_number      VARCHAR(30)     NOT NULL,
    username          VARCHAR(50)     NOT NULL,
    email             VARCHAR(150)    NOT NULL,
    password_hash     CHAR(60)        NOT NULL COMMENT 'bcrypt hash, fixed 60 chars',
    full_name         VARCHAR(150)    NOT NULL,
    role_id           SMALLINT UNSIGNED NOT NULL,
    department_id     SMALLINT UNSIGNED NOT NULL,
    phone_number      VARCHAR(20)     NULL,
    is_active         TINYINT(1)      NOT NULL DEFAULT 1,
    last_login_at     DATETIME        NULL,
    created_at        DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id),
    CONSTRAINT uq_users_badge_number UNIQUE (badge_number),
    CONSTRAINT uq_users_username     UNIQUE (username),
    CONSTRAINT uq_users_email        UNIQUE (email),
    CONSTRAINT fk_users_role
        FOREIGN KEY (role_id) REFERENCES roles (role_id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_users_department
        FOREIGN KEY (department_id) REFERENCES departments (department_id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_users_email_format CHECK (email LIKE '%_@_%.__%'),
    CONSTRAINT chk_users_is_active CHECK (is_active IN (0,1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='System users: investigators, forensic analysts, supervisors, auditors, admins';

-- =====================================================================
-- 6. cases — the root forensic case file
-- =====================================================================
CREATE TABLE cases (
    case_id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    case_number              VARCHAR(40)     NOT NULL COMMENT 'Human-readable business key, e.g. FX-2026-000123',
    case_title                VARCHAR(200)    NOT NULL,
    case_type_id                SMALLINT UNSIGNED NOT NULL,
    status                        ENUM('open','under_investigation','pending_review','closed','archived','cold')
                                                  NOT NULL DEFAULT 'open',
    priority                       ENUM('low','medium','high','critical') NOT NULL DEFAULT 'medium',
    jurisdiction_location_id         INT UNSIGNED NULL,
    description                        TEXT      NULL,
    opened_at                            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    closed_at                              DATETIME NULL,
    created_by                               BIGINT UNSIGNED NOT NULL,
    created_at                                 DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at                                   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (case_id),
    CONSTRAINT uq_cases_case_number UNIQUE (case_number),
    CONSTRAINT fk_cases_case_type
        FOREIGN KEY (case_type_id) REFERENCES case_types (case_type_id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_cases_jurisdiction_location
        FOREIGN KEY (jurisdiction_location_id) REFERENCES locations (location_id)
        ON DELETE SET NULL ON UPDATE RESTRICT,
    CONSTRAINT fk_cases_created_by
        FOREIGN KEY (created_by) REFERENCES users (user_id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_cases_closed_after_opened
        CHECK (closed_at IS NULL OR closed_at >= opened_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Root forensic case file - every device/evidence/report chains back to a case';

-- =====================================================================
-- 7. case_investigators — M:N junction: cases <-> users
-- =====================================================================
CREATE TABLE case_investigators (
    case_id           BIGINT UNSIGNED NOT NULL,
    user_id           BIGINT UNSIGNED NOT NULL,
    role_in_case      ENUM('lead_investigator','co_investigator','forensic_analyst','supervisor','consultant')
                                       NOT NULL DEFAULT 'co_investigator',
    assigned_at       DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    unassigned_at     DATETIME        NULL,
    PRIMARY KEY (case_id, user_id),
    CONSTRAINT fk_case_investigators_case
        FOREIGN KEY (case_id) REFERENCES cases (case_id)
        ON DELETE CASCADE ON UPDATE RESTRICT,
    CONSTRAINT fk_case_investigators_user
        FOREIGN KEY (user_id) REFERENCES users (user_id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_case_investigators_unassign_after_assign
        CHECK (unassigned_at IS NULL OR unassigned_at >= assigned_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Junction table resolving the many-to-many assignment of investigators/analysts to cases';

-- =====================================================================
-- 8. persons — suspects, victims, witnesses, owners, etc.
-- =====================================================================
CREATE TABLE persons (
    person_id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    first_name          VARCHAR(100)    NOT NULL,
    last_name           VARCHAR(100)    NOT NULL,
    date_of_birth       DATE            NULL,
    national_id_number  VARCHAR(50)     NULL COMMENT 'e.g. Aadhaar/passport number, when known',
    gender               ENUM('male','female','other','unknown') NOT NULL DEFAULT 'unknown',
    phone_number           VARCHAR(20)  NULL,
    email                     VARCHAR(150) NULL,
    address                     TEXT       NULL,
    created_at                    DATETIME  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at                      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (person_id),
    CONSTRAINT uq_persons_national_id UNIQUE (national_id_number)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Natural persons connected to one or more cases (suspects, victims, witnesses, owners)';

-- =====================================================================
-- 9. case_persons — M:N junction: cases <-> persons (with role in case)
-- =====================================================================
CREATE TABLE case_persons (
    case_id       BIGINT UNSIGNED NOT NULL,
    person_id     BIGINT UNSIGNED NOT NULL,
    person_role   ENUM('suspect','victim','witness','complainant','person_of_interest','owner')
                                   NOT NULL,
    notes         VARCHAR(500)    NULL,
    linked_at     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (case_id, person_id, person_role),
    CONSTRAINT fk_case_persons_case
        FOREIGN KEY (case_id) REFERENCES cases (case_id)
        ON DELETE CASCADE ON UPDATE RESTRICT,
    CONSTRAINT fk_case_persons_person
        FOREIGN KEY (person_id) REFERENCES persons (person_id)
        ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Junction table linking persons to cases; composite PK allows one person to hold multiple distinct roles in the same case';

-- =====================================================================
-- 10. device_types — lookup table of seized-device categories
-- =====================================================================
CREATE TABLE device_types (
    device_type_id    SMALLINT UNSIGNED NOT NULL AUTO_INCREMENT,
    type_name         VARCHAR(100)      NOT NULL,
    type_description  VARCHAR(255)      NULL,
    PRIMARY KEY (device_type_id),
    CONSTRAINT uq_device_types_name UNIQUE (type_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Device category lookup (e.g. Smartphone, Laptop, HDD, USB Drive, Server, IoT Device)';

-- =====================================================================
-- 11. devices — physical devices seized under a case
-- =====================================================================
CREATE TABLE devices (
    device_id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    case_id                  BIGINT UNSIGNED NOT NULL,
    device_type_id             SMALLINT UNSIGNED NOT NULL,
    owner_person_id               BIGINT UNSIGNED NULL,
    serial_number                   VARCHAR(100) NULL,
    make                               VARCHAR(100) NULL,
    model                                VARCHAR(100) NULL,
    imei_number                           VARCHAR(20)  NULL,
    storage_capacity_gb                     DECIMAL(10,2) NULL COMMENT 'Numeric precision required for exact capacity reporting',
    seized_at                                 DATETIME     NULL,
    seized_location_id                          INT UNSIGNED NULL,
    current_location_id                           INT UNSIGNED NULL,
    device_status                                   ENUM('seized','in_lab','under_examination','returned','disposed','archived')
                                                              NOT NULL DEFAULT 'seized',
    created_at                                        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at                                          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (device_id),
    CONSTRAINT fk_devices_case
        FOREIGN KEY (case_id) REFERENCES cases (case_id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_devices_device_type
        FOREIGN KEY (device_type_id) REFERENCES device_types (device_type_id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_devices_owner_person
        FOREIGN KEY (owner_person_id) REFERENCES persons (person_id)
        ON DELETE SET NULL ON UPDATE RESTRICT,
    CONSTRAINT fk_devices_seized_location
        FOREIGN KEY (seized_location_id) REFERENCES locations (location_id)
        ON DELETE SET NULL ON UPDATE RESTRICT,
    CONSTRAINT fk_devices_current_location
        FOREIGN KEY (current_location_id) REFERENCES locations (location_id)
        ON DELETE SET NULL ON UPDATE RESTRICT,
    CONSTRAINT chk_devices_storage_capacity_nonneg
        CHECK (storage_capacity_gb IS NULL OR storage_capacity_gb >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Physical devices seized as part of a case (source of digital evidence)';

-- =====================================================================
-- 12. evidence_types — lookup table of evidence item categories
-- =====================================================================
CREATE TABLE evidence_types (
    evidence_type_id  SMALLINT UNSIGNED NOT NULL AUTO_INCREMENT,
    type_name         VARCHAR(100)      NOT NULL,
    type_description  VARCHAR(255)      NULL,
    PRIMARY KEY (evidence_type_id),
    CONSTRAINT uq_evidence_types_name UNIQUE (type_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Evidence category lookup (e.g. Disk Image, Memory Dump, Log File, Photograph, Document, Network Capture)';

-- =====================================================================
-- 13. evidence — individual evidence items collected within a case
-- =====================================================================
CREATE TABLE evidence (
    evidence_id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    evidence_number             VARCHAR(50)     NOT NULL COMMENT 'Human-readable business key, e.g. EVD-2026-000456',
    case_id                       BIGINT UNSIGNED NOT NULL,
    device_id                       BIGINT UNSIGNED NULL COMMENT 'NULL when evidence is not device-derived (e.g. a physical document)',
    evidence_type_id                  SMALLINT UNSIGNED NOT NULL,
    description                         TEXT NOT NULL,
    file_path                             VARCHAR(500) NULL COMMENT 'Path/URI to the stored digital copy, if applicable',
    file_size_bytes                         BIGINT UNSIGNED NULL,
    acquisition_method                        ENUM('physical_seizure','logical_extraction','physical_extraction',
                                                     'network_capture','cloud_extraction','manual_documentation')
                                                             NOT NULL,
    collected_by                                BIGINT UNSIGNED NOT NULL,
    collected_at                                  DATETIME NOT NULL,
    storage_location_id                             INT UNSIGNED NULL,
    integrity_status                                  ENUM('intact','compromised','under_verification')
                                                             NOT NULL DEFAULT 'intact',
    created_at                                          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at                                            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (evidence_id),
    CONSTRAINT uq_evidence_number UNIQUE (evidence_number),
    CONSTRAINT fk_evidence_case
        FOREIGN KEY (case_id) REFERENCES cases (case_id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_evidence_device
        FOREIGN KEY (device_id) REFERENCES devices (device_id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_evidence_evidence_type
        FOREIGN KEY (evidence_type_id) REFERENCES evidence_types (evidence_type_id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_evidence_collected_by
        FOREIGN KEY (collected_by) REFERENCES users (user_id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_evidence_storage_location
        FOREIGN KEY (storage_location_id) REFERENCES locations (location_id)
        ON DELETE SET NULL ON UPDATE RESTRICT,
    CONSTRAINT chk_evidence_file_size_nonneg
        CHECK (file_size_bytes IS NULL OR file_size_bytes >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Individual evidence items collected within a case, optionally sourced from a device';

-- =====================================================================
-- 14. evidence_hashes — cryptographic integrity hashes for evidence
-- =====================================================================
CREATE TABLE evidence_hashes (
    hash_id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    evidence_id           BIGINT UNSIGNED NOT NULL,
    hash_algorithm           ENUM('MD5','SHA1','SHA256','SHA512') NOT NULL,
    hash_value                  VARCHAR(128) NOT NULL,
    computed_by                   BIGINT UNSIGNED NOT NULL,
    computed_at                     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_original                       TINYINT(1) NOT NULL DEFAULT 1
                                       COMMENT '1 = hash captured at acquisition time, 0 = later re-verification',
    PRIMARY KEY (hash_id),
    CONSTRAINT uq_evidence_hashes_value UNIQUE (evidence_id, hash_algorithm, hash_value, computed_at),
    CONSTRAINT fk_evidence_hashes_evidence
        FOREIGN KEY (evidence_id) REFERENCES evidence (evidence_id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_evidence_hashes_computed_by
        FOREIGN KEY (computed_by) REFERENCES users (user_id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_evidence_hashes_length
        CHECK (CHAR_LENGTH(hash_value) >= 32),
    CONSTRAINT chk_evidence_hashes_is_original
        CHECK (is_original IN (0,1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Cryptographic hash values (MD5/SHA1/SHA256/SHA512) proving evidence integrity over time';

-- =====================================================================
-- 15. chain_of_custody — full custodial transfer history of evidence
-- =====================================================================
CREATE TABLE chain_of_custody (
    custody_id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    evidence_id              BIGINT UNSIGNED NOT NULL,
    transferred_from            BIGINT UNSIGNED NULL COMMENT 'NULL on the first (collection) entry',
    transferred_to                 BIGINT UNSIGNED NOT NULL,
    custody_action                    ENUM('collected','transferred','received','analyzed','returned','stored','disposed')
                                                    NOT NULL,
    location_id                          INT UNSIGNED NOT NULL,
    custody_timestamp                       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    remarks                                    VARCHAR(500) NULL,
    signature_hash                                VARCHAR(128) NULL COMMENT 'Digital signature/hash confirming the custody record itself',
    PRIMARY KEY (custody_id),
    CONSTRAINT fk_custody_evidence
        FOREIGN KEY (evidence_id) REFERENCES evidence (evidence_id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_custody_transferred_from
        FOREIGN KEY (transferred_from) REFERENCES users (user_id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_custody_transferred_to
        FOREIGN KEY (transferred_to) REFERENCES users (user_id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_custody_location
        FOREIGN KEY (location_id) REFERENCES locations (location_id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_custody_from_ne_to
        CHECK (transferred_from IS NULL OR transferred_from <> transferred_to)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Immutable, append-only chain-of-custody ledger for every evidence item';

-- =====================================================================
-- 16. forensic_tools — lookup table of forensic software/hardware tools
-- =====================================================================
CREATE TABLE forensic_tools (
    tool_id           INT UNSIGNED NOT NULL AUTO_INCREMENT,
    tool_name         VARCHAR(100)     NOT NULL,
    vendor            VARCHAR(100)     NULL,
    version           VARCHAR(30)      NULL,
    license_type      ENUM('open_source','commercial','government_licensed') NOT NULL DEFAULT 'commercial',
    created_at        DATETIME         NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tool_id),
    CONSTRAINT uq_forensic_tools_name_version UNIQUE (tool_name, version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Forensic tools used during examinations (e.g. Autopsy, EnCase, FTK, Wireshark, Volatility)';

-- =====================================================================
-- 17. evidence_examinations — forensic examinations performed on evidence
-- =====================================================================
CREATE TABLE evidence_examinations (
    examination_id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    evidence_id               BIGINT UNSIGNED NOT NULL,
    tool_id                      INT UNSIGNED NOT NULL,
    examiner_id                     BIGINT UNSIGNED NOT NULL,
    examination_type                   ENUM('static_analysis','dynamic_analysis','data_recovery','malware_analysis',
                                              'network_analysis','file_carving','timeline_analysis','other')
                                                        NOT NULL,
    started_at                            DATETIME NOT NULL,
    completed_at                             DATETIME NULL,
    findings_summary                            TEXT NULL,
    examination_status                            ENUM('scheduled','in_progress','completed','peer_reviewed')
                                                        NOT NULL DEFAULT 'scheduled',
    created_at                                      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (examination_id),
    CONSTRAINT fk_examinations_evidence
        FOREIGN KEY (evidence_id) REFERENCES evidence (evidence_id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_examinations_tool
        FOREIGN KEY (tool_id) REFERENCES forensic_tools (tool_id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_examinations_examiner
        FOREIGN KEY (examiner_id) REFERENCES users (user_id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_examinations_completed_after_started
        CHECK (completed_at IS NULL OR completed_at >= started_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Forensic examinations performed on an evidence item using a specific tool';

-- =====================================================================
-- 18. forensic_reports — official case reports
-- =====================================================================
CREATE TABLE forensic_reports (
    report_id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    case_id                 BIGINT UNSIGNED NOT NULL,
    report_number              VARCHAR(50) NOT NULL,
    title                         VARCHAR(200) NOT NULL,
    prepared_by                     BIGINT UNSIGNED NOT NULL,
    reviewed_by                        BIGINT UNSIGNED NULL,
    report_status                         ENUM('draft','submitted','under_review','approved','finalized')
                                                        NOT NULL DEFAULT 'draft',
    created_at                              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finalized_at                               DATETIME NULL,
    PRIMARY KEY (report_id),
    CONSTRAINT uq_forensic_reports_number UNIQUE (report_number),
    CONSTRAINT fk_reports_case
        FOREIGN KEY (case_id) REFERENCES cases (case_id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_reports_prepared_by
        FOREIGN KEY (prepared_by) REFERENCES users (user_id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    -- RESTRICT (not SET NULL) because reviewed_by participates in
    -- chk_reports_reviewer_ne_author below — MySQL 8.0 forbids an
    -- automatic referential action on a CHECK-constrained column.
    CONSTRAINT fk_reports_reviewed_by
        FOREIGN KEY (reviewed_by) REFERENCES users (user_id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_reports_reviewer_ne_author
        CHECK (reviewed_by IS NULL OR reviewed_by <> prepared_by)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Official forensic report filed for a case (may go through multiple versions)';

-- =====================================================================
-- 19. report_versions — version history of each forensic report
-- =====================================================================
CREATE TABLE report_versions (
    version_id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    report_id              BIGINT UNSIGNED NOT NULL,
    version_number             SMALLINT UNSIGNED NOT NULL,
    file_path                     VARCHAR(500) NOT NULL,
    content_hash                     VARCHAR(128) NULL,
    change_summary                      VARCHAR(500) NULL,
    created_by                             BIGINT UNSIGNED NOT NULL,
    created_at                                DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (version_id),
    CONSTRAINT uq_report_versions_report_version UNIQUE (report_id, version_number),
    CONSTRAINT fk_report_versions_report
        FOREIGN KEY (report_id) REFERENCES forensic_reports (report_id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_report_versions_created_by
        FOREIGN KEY (created_by) REFERENCES users (user_id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_report_versions_number_positive
        CHECK (version_number >= 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Immutable version history for each forensic report (supports revision tracking)';

-- =====================================================================
-- 20. case_timeline — chronological event log for a case
-- =====================================================================
CREATE TABLE case_timeline (
    timeline_id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    case_id                  BIGINT UNSIGNED NOT NULL,
    event_type                  ENUM('case_opened','evidence_collected','custody_transfer','examination_started',
                                      'examination_completed','report_filed','status_change','case_closed','other')
                                              NOT NULL,
    event_description              VARCHAR(500) NOT NULL,
    related_table                     VARCHAR(50) NULL
                                              COMMENT 'Optional pointer name (e.g. evidence, forensic_reports) - not FK-enforced (polymorphic reference)',
    related_record_id                    BIGINT UNSIGNED NULL,
    event_timestamp                         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    recorded_by                                BIGINT UNSIGNED NOT NULL,
    PRIMARY KEY (timeline_id),
    CONSTRAINT fk_timeline_case
        FOREIGN KEY (case_id) REFERENCES cases (case_id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_timeline_recorded_by
        FOREIGN KEY (recorded_by) REFERENCES users (user_id)
        ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Chronological, human-readable event log for a case, aggregating key lifecycle events';

-- =====================================================================
-- 21. audit_logs — system-wide audit trail (who changed what, when)
-- =====================================================================
CREATE TABLE audit_logs (
    audit_id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id                  BIGINT UNSIGNED NULL COMMENT 'NULL for system/trigger-generated entries',
    table_name                  VARCHAR(64) NOT NULL,
    record_id                      BIGINT UNSIGNED NOT NULL,
    action_type                       ENUM('INSERT','UPDATE','DELETE') NOT NULL,
    old_values                           JSON NULL,
    new_values                              JSON NULL,
    action_timestamp                           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ip_address                                    VARCHAR(45) NULL COMMENT 'IPv4 or IPv6',
    PRIMARY KEY (audit_id),
    CONSTRAINT fk_audit_logs_user
        FOREIGN KEY (user_id) REFERENCES users (user_id)
        ON DELETE SET NULL ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='System-wide audit trail; populated primarily by triggers (see 08_triggers.sql in a later phase)';

SELECT 'All 21 FORGE-X tables created successfully.' AS status;
