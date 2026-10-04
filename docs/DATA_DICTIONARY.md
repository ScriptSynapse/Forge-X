# FORGE-X Data Dictionary

Generated from `database/schema.sql` by `tools/make_data_dictionary.py`; do not edit by hand.
22 tables, all InnoDB. Every foreign key is ON DELETE RESTRICT ON UPDATE RESTRICT.

**Key:** PK primary key, FK foreign key, UK unique, NN not null.

## Tables

- [`roles`](#roles)
- [`users`](#users)
- [`user_roles`](#user_roles)
- [`account_requests`](#account_requests)
- [`login_attempts`](#login_attempts)
- [`case_types`](#case_types)
- [`evidence_types`](#evidence_types)
- [`examination_types`](#examination_types)
- [`storage_locations`](#storage_locations)
- [`reference_sequences`](#reference_sequences)
- [`cases`](#cases)
- [`case_investigators`](#case_investigators)
- [`evidence`](#evidence)
- [`evidence_hashes`](#evidence_hashes)
- [`hash_verifications`](#hash_verifications)
- [`chain_of_custody`](#chain_of_custody)
- [`examinations`](#examinations)
- [`examination_evidence`](#examination_evidence)
- [`forensic_reports`](#forensic_reports)
- [`report_versions`](#report_versions)
- [`report_examinations`](#report_examinations)
- [`audit_logs`](#audit_logs)

## roles

The four fixed application roles

| Column | Type | Keys | Null | Notes |
| --- | --- | --- | --- | --- |
| `role_id` | TINYINT UNSIGNED | PK | NN | AUTO_INCREMENT |
| `role_name` | VARCHAR(40) | UK | NN |  |
| `description` | VARCHAR(255) |  | NN |  |

## users

Active and deactivated accounts (never pending applicants)

| Column | Type | Keys | Null | Notes |
| --- | --- | --- | --- | --- |
| `user_id` | INT UNSIGNED | PK | NN | AUTO_INCREMENT |
| `full_name` | VARCHAR(100) |  | NN |  |
| `email` | VARCHAR(254) | UK | NN |  |
| `username` | VARCHAR(30) | UK | NN |  |
| `password_hash` | VARCHAR(255) |  | NN |  |
| `account_status` | ENUM('Active','Deactivated') |  | NN | Default 'Active' |
| `must_change_password` | BOOLEAN |  | NN | Default FALSE |
| `session_version` | INT UNSIGNED |  | NN | Default 0 |
| `created_at` | DATETIME |  | NN | Default CURRENT_TIMESTAMP |
| `updated_at` | DATETIME |  | NN | Default CURRENT_TIMESTAMP; Updated automatically |
| `last_login_at` | DATETIME |  | NULL |  |

**CHECK constraints**

- `chk_users_username`: `username REGEXP '^[A-Za-z0-9._]{3,30}$'`
- `chk_users_email`: `email LIKE '%_@_%._%'`

## user_roles

Users <-> roles (many-to-many)

| Column | Type | Keys | Null | Notes |
| --- | --- | --- | --- | --- |
| `user_role_id` | INT UNSIGNED | PK | NN | AUTO_INCREMENT |
| `user_id` | INT UNSIGNED | FK → `users.user_id`; UK (uq_user_roles) | NN |  |
| `role_id` | TINYINT UNSIGNED | FK → `roles.role_id`; UK (uq_user_roles) | NN |  |
| `assigned_by` | INT UNSIGNED | FK → `users.user_id` | NULL |  |
| `assigned_at` | DATETIME |  | NN | Default CURRENT_TIMESTAMP |

**CHECK constraints**

- `chk_ur_not_self`: `assigned_by IS NULL OR assigned_by <> user_id`

## account_requests

Signup requests awaiting review

| Column | Type | Keys | Null | Notes |
| --- | --- | --- | --- | --- |
| `request_id` | INT UNSIGNED | PK | NN | AUTO_INCREMENT |
| `full_name` | VARCHAR(100) |  | NN |  |
| `email` | VARCHAR(254) |  | NN |  |
| `username` | VARCHAR(30) |  | NN |  |
| `password_hash` | VARCHAR(255) |  | NULL |  |
| `reason` | VARCHAR(500) |  | NULL |  |
| `request_status` | ENUM('Pending','Approved','Rejected') |  | NN | Default 'Pending' |
| `reviewed_by` | INT UNSIGNED | FK → `users.user_id` | NULL |  |
| `reviewed_at` | DATETIME |  | NULL |  |
| `review_note` | VARCHAR(255) |  | NULL |  |
| `created_user_id` | INT UNSIGNED | FK → `users.user_id`; UK | NULL |  |
| `created_at` | DATETIME |  | NN | Default CURRENT_TIMESTAMP |
| `pending_email` | VARCHAR(254) | UK | Generated | Generated (stored): `(IF(request_status = 'Pending', email, NULL))` |
| `pending_username` | VARCHAR(30) | UK | Generated | Generated (stored): `(IF(request_status = 'Pending', username, NULL))` |

**CHECK constraints**

- `chk_ar_username`: `username REGEXP '^[A-Za-z0-9._]{3,30}$'`
- `chk_ar_review`: `(request_status = 'Pending' AND reviewed_by IS NULL AND reviewed_at IS NULL AND password_hash IS NOT NULL) OR (request_status <> 'Pending' AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND password_hash IS NULL)`
- `chk_ar_created`: `(request_status = 'Approved') = (created_user_id IS NOT NULL)`

## login_attempts

Every authentication attempt (never the password)

| Column | Type | Keys | Null | Notes |
| --- | --- | --- | --- | --- |
| `attempt_id` | BIGINT UNSIGNED | PK | NN | AUTO_INCREMENT |
| `username_or_email` | VARCHAR(254) |  | NN |  |
| `user_id` | INT UNSIGNED | FK → `users.user_id` | NULL |  |
| `success` | BOOLEAN |  | NN |  |
| `failure_reason` | ENUM('invalid_credentials','account_inactive','rate_limited') |  | NULL |  |
| `ip_address` | VARCHAR(45) |  | NN |  |
| `user_agent` | VARCHAR(255) |  | NULL |  |
| `attempted_at` | DATETIME(3) |  | NN | Default CURRENT_TIMESTAMP(3) |

**CHECK constraints**

- `chk_la_outcome`: `(success = TRUE AND failure_reason IS NULL AND user_id IS NOT NULL) OR (success = FALSE AND failure_reason IS NOT NULL)`

## case_types

6-8. Lookup tables

| Column | Type | Keys | Null | Notes |
| --- | --- | --- | --- | --- |
| `case_type_id` | SMALLINT UNSIGNED | PK | NN | AUTO_INCREMENT |
| `type_name` | VARCHAR(60) | UK | NN |  |
| `description` | VARCHAR(255) |  | NULL |  |
| `is_active` | BOOLEAN |  | NN | Default TRUE |

## evidence_types

| Column | Type | Keys | Null | Notes |
| --- | --- | --- | --- | --- |
| `evidence_type_id` | SMALLINT UNSIGNED | PK | NN | AUTO_INCREMENT |
| `type_name` | VARCHAR(60) | UK | NN |  |
| `description` | VARCHAR(255) |  | NULL |  |
| `is_active` | BOOLEAN |  | NN | Default TRUE |

## examination_types

| Column | Type | Keys | Null | Notes |
| --- | --- | --- | --- | --- |
| `examination_type_id` | SMALLINT UNSIGNED | PK | NN | AUTO_INCREMENT |
| `type_name` | VARCHAR(80) | UK | NN |  |
| `description` | VARCHAR(255) |  | NULL |  |
| `is_active` | BOOLEAN |  | NN | Default TRUE |

## storage_locations

9. storage_locations

| Column | Type | Keys | Null | Notes |
| --- | --- | --- | --- | --- |
| `location_id` | SMALLINT UNSIGNED | PK | NN | AUTO_INCREMENT |
| `location_name` | VARCHAR(100) | UK | NN |  |
| `location_type` | ENUM('Vault','Evidence Room','Examination Lab','Imaging Bench','Other') |  | NN |  |
| `description` | VARCHAR(255) |  | NULL |  |
| `is_active` | BOOLEAN |  | NN | Default TRUE |

## reference_sequences

Gap-free yearly counters for business codes

| Column | Type | Keys | Null | Notes |
| --- | --- | --- | --- | --- |
| `seq_name` | ENUM('CASE','EVIDENCE','EXAMINATION','REPORT') | PK | NN |  |
| `seq_year` | SMALLINT UNSIGNED | PK | NN |  |
| `last_number` | INT UNSIGNED |  | NN | Default 0 |

## cases

11. cases

| Column | Type | Keys | Null | Notes |
| --- | --- | --- | --- | --- |
| `case_id` | INT UNSIGNED | PK | NN | AUTO_INCREMENT |
| `case_reference` | CHAR(12) | UK | NN |  |
| `title` | VARCHAR(200) |  | NN |  |
| `description` | TEXT |  | NN |  |
| `case_type_id` | SMALLINT UNSIGNED | FK → `case_types.case_type_id` | NN |  |
| `priority` | ENUM('Low','Medium','High','Critical') |  | NN | Default 'Medium' |
| `status` | ENUM('Open','In Progress','On Hold','Closed') |  | NN | Default 'Open' |
| `created_by` | INT UNSIGNED | FK → `users.user_id` | NN |  |
| `created_at` | DATETIME |  | NN | Default CURRENT_TIMESTAMP |
| `updated_at` | DATETIME |  | NN | Default CURRENT_TIMESTAMP; Updated automatically |
| `closed_at` | DATETIME |  | NULL |  |
| `closure_summary` | VARCHAR(1000) |  | NULL |  |

**CHECK constraints**

- `chk_cases_reference`: `case_reference REGEXP '^FX-[0-9]{4}-[0-9]{4}$'`
- `chk_cases_closed`: `(status = 'Closed' AND closed_at IS NOT NULL AND closure_summary IS NOT NULL) OR (status <> 'Closed' AND closed_at IS NULL)`
- `chk_cases_closed_after`: `closed_at IS NULL OR closed_at >= created_at`

## case_investigators

Cases <-> investigators (many-to-many)

| Column | Type | Keys | Null | Notes |
| --- | --- | --- | --- | --- |
| `case_investigator_id` | INT UNSIGNED | PK | NN | AUTO_INCREMENT |
| `case_id` | INT UNSIGNED | FK → `cases.case_id`; UK (uq_ci_case_user) | NN |  |
| `user_id` | INT UNSIGNED | FK → `users.user_id`; UK (uq_ci_case_user) | NN |  |
| `is_lead` | BOOLEAN |  | NN | Default FALSE |
| `assigned_by` | INT UNSIGNED | FK → `users.user_id` | NN |  |
| `assigned_at` | DATETIME |  | NN | Default CURRENT_TIMESTAMP |
| `lead_case_id` | INT UNSIGNED | UK | Generated | Generated (stored): `(IF(is_lead = TRUE, case_id, NULL))` |

## evidence

Metadata only, never the evidence files themselves

| Column | Type | Keys | Null | Notes |
| --- | --- | --- | --- | --- |
| `evidence_id` | INT UNSIGNED | PK | NN | AUTO_INCREMENT |
| `evidence_code` | CHAR(16) | UK | NN |  |
| `case_id` | INT UNSIGNED | FK → `cases.case_id` | NN |  |
| `evidence_type_id` | SMALLINT UNSIGNED | FK → `evidence_types.evidence_type_id` | NN |  |
| `description` | VARCHAR(500) |  | NN |  |
| `source_details` | VARCHAR(255) |  | NULL |  |
| `size_bytes` | BIGINT UNSIGNED |  | NULL |  |
| `collected_at` | DATETIME |  | NN |  |
| `collected_by` | INT UNSIGNED | FK → `users.user_id` | NN |  |
| `collection_site` | VARCHAR(200) |  | NN |  |
| `collection_condition` | VARCHAR(200) |  | NN |  |
| `current_status` | ENUM('In Transit','In Storage','Checked Out','Under Examination','Released','Archived') |  | NN | Default 'In Transit' |
| `current_custodian_id` | INT UNSIGNED | FK → `users.user_id` | NN |  |
| `current_location_id` | SMALLINT UNSIGNED | FK → `storage_locations.location_id` | NULL |  |
| `registered_at` | DATETIME |  | NN | Default CURRENT_TIMESTAMP |
| `updated_at` | DATETIME |  | NN | Default CURRENT_TIMESTAMP; Updated automatically |

**CHECK constraints**

- `chk_ev_code`: `evidence_code REGEXP '^FX-EV-[0-9]{4}-[0-9]{5}$'`
- `chk_ev_dates`: `collected_at <= registered_at`

## evidence_hashes

Recorded reference hashes (append-only)

| Column | Type | Keys | Null | Notes |
| --- | --- | --- | --- | --- |
| `hash_id` | INT UNSIGNED | PK | NN | AUTO_INCREMENT |
| `evidence_id` | INT UNSIGNED | FK → `evidence.evidence_id` | NN |  |
| `algorithm` | ENUM('SHA-256') |  | NN | Default 'SHA-256' |
| `hash_value` | CHAR(64) |  | NN |  |
| `source` | ENUM('Computed','Manual') |  | NN |  |
| `source_notes` | VARCHAR(500) |  | NULL |  |
| `recorded_by` | INT UNSIGNED | FK → `users.user_id` | NN |  |
| `recorded_at` | DATETIME |  | NN | Default CURRENT_TIMESTAMP |
| `supersedes_hash_id` | INT UNSIGNED | FK → `evidence_hashes.hash_id`; UK | NULL |  |
| `correction_reason` | VARCHAR(500) |  | NULL |  |
| `root_evidence_id` | INT UNSIGNED | UK | Generated | Generated (stored): `(IF(supersedes_hash_id IS NULL, evidence_id, NULL))` |

**CHECK constraints**

- `chk_eh_format`: `hash_value REGEXP '^[0-9a-f]{64}$'`
- `chk_eh_manual_notes`: `source = 'Computed' OR source_notes IS NOT NULL`
- `chk_eh_correction`: `(supersedes_hash_id IS NULL) = (correction_reason IS NULL)`

## hash_verifications

Every comparison (append-only)

| Column | Type | Keys | Null | Notes |
| --- | --- | --- | --- | --- |
| `verification_id` | INT UNSIGNED | PK | NN | AUTO_INCREMENT |
| `hash_id` | INT UNSIGNED | FK → `evidence_hashes.hash_id` | NN |  |
| `computed_hash` | CHAR(64) |  | NN |  |
| `result` | ENUM('Verified','Failed') |  | NN | Default 'Failed' |
| `method` | ENUM('Sample file','Manual entry') |  | NN |  |
| `sample_file_name` | VARCHAR(255) |  | NULL |  |
| `sample_size_bytes` | BIGINT UNSIGNED |  | NULL |  |
| `notes` | VARCHAR(500) |  | NULL |  |
| `verified_by` | INT UNSIGNED | FK → `users.user_id` | NN |  |
| `verified_at` | DATETIME |  | NN | Default CURRENT_TIMESTAMP |

**CHECK constraints**

- `chk_hv_format`: `computed_hash REGEXP '^[0-9a-f]{64}$'`
- `chk_hv_method`: `(method = 'Sample file' AND sample_file_name IS NOT NULL) OR (method = 'Manual entry' AND notes IS NOT NULL)`

## chain_of_custody

Every handling event (append-only)

| Column | Type | Keys | Null | Notes |
| --- | --- | --- | --- | --- |
| `custody_id` | INT UNSIGNED | PK | NN | AUTO_INCREMENT |
| `evidence_id` | INT UNSIGNED | FK → `evidence.evidence_id` | NN |  |
| `action` | ENUM |  | NULL |  |
| `from_custodian_id` | INT UNSIGNED | FK → `users.user_id` | NULL |  |
| `to_custodian_id` | INT UNSIGNED | FK → `users.user_id` | NN |  |
| `location_id` | SMALLINT UNSIGNED | FK → `storage_locations.location_id` | NULL |  |
| `location_note` | VARCHAR(200) |  | NULL |  |
| `evidence_condition` | VARCHAR(200) |  | NN |  |
| `seal_number` | VARCHAR(30) |  | NULL |  |
| `reason` | VARCHAR(500) |  | NN |  |
| `occurred_at` | DATETIME |  | NN |  |
| `recorded_by` | INT UNSIGNED | FK → `users.user_id` | NN |  |
| `recorded_at` | DATETIME |  | NN | Default CURRENT_TIMESTAMP |
| `corrects_custody_id` | INT UNSIGNED | FK → `chain_of_custody.custody_id` | NULL |  |

**CHECK constraints**

- `chk_coc_from`: `(action = 'Collected') = (from_custodian_id IS NULL)`
- `chk_coc_location`: `location_id IS NOT NULL OR location_note IS NOT NULL`
- `chk_coc_time`: `occurred_at <= recorded_at`

## examinations

17. examinations

| Column | Type | Keys | Null | Notes |
| --- | --- | --- | --- | --- |
| `examination_id` | INT UNSIGNED | PK | NN | AUTO_INCREMENT |
| `examination_code` | CHAR(12) | UK | NN |  |
| `case_id` | INT UNSIGNED | FK → `cases.case_id` | NN |  |
| `examination_type_id` | SMALLINT UNSIGNED | FK → `examination_types.examination_type_id` | NN |  |
| `examiner_id` | INT UNSIGNED | FK → `users.user_id` | NN |  |
| `status` | ENUM('Pending','In Progress','Completed','Cancelled') |  | NN | Default 'Pending' |
| `due_date` | DATE |  | NULL |  |
| `started_at` | DATETIME |  | NULL |  |
| `completed_at` | DATETIME |  | NULL |  |
| `tools_methods` | TEXT |  | NULL |  |
| `observations` | TEXT |  | NULL |  |
| `findings` | TEXT |  | NULL |  |
| `limitations` | TEXT |  | NULL |  |
| `cancel_reason` | VARCHAR(500) |  | NULL |  |
| `created_at` | DATETIME |  | NN | Default CURRENT_TIMESTAMP |
| `updated_at` | DATETIME |  | NN | Default CURRENT_TIMESTAMP; Updated automatically |

**CHECK constraints**

- `chk_exam_code`: `examination_code REGEXP '^EX-[0-9]{4}-[0-9]{4}$'`
- `chk_exam_state`: `(status = 'Pending' AND started_at IS NULL AND completed_at IS NULL) OR (status = 'In Progress' AND started_at IS NOT NULL AND completed_at IS NULL) OR (status = 'Completed' AND started_at IS NOT NULL AND completed_at IS NOT NULL AND completed_at >= started_at AND tools_methods IS NOT NULL AND findings IS NOT NULL) OR (status = 'Cancelled' AND cancel_reason IS NOT NULL)`

## examination_evidence

Examinations <-> evidence (many-to-many)

| Column | Type | Keys | Null | Notes |
| --- | --- | --- | --- | --- |
| `examination_id` | INT UNSIGNED | PK; FK → `examinations.examination_id` | NN |  |
| `evidence_id` | INT UNSIGNED | PK; FK → `evidence.evidence_id` | NN |  |
| `linked_at` | DATETIME |  | NN | Default CURRENT_TIMESTAMP |

## forensic_reports

Report header and review status

| Column | Type | Keys | Null | Notes |
| --- | --- | --- | --- | --- |
| `report_id` | INT UNSIGNED | PK | NN | AUTO_INCREMENT |
| `report_code` | CHAR(12) | UK | NN |  |
| `case_id` | INT UNSIGNED | FK → `cases.case_id` | NN |  |
| `title` | VARCHAR(200) |  | NN |  |
| `author_id` | INT UNSIGNED | FK → `users.user_id` | NN |  |
| `status` | ENUM('Draft','Under Review','Approved') |  | NN | Default 'Draft' |
| `submitted_at` | DATETIME |  | NULL |  |
| `approved_by` | INT UNSIGNED | FK → `users.user_id` | NULL |  |
| `approved_at` | DATETIME |  | NULL |  |
| `created_at` | DATETIME |  | NN | Default CURRENT_TIMESTAMP |
| `updated_at` | DATETIME |  | NN | Default CURRENT_TIMESTAMP; Updated automatically |

**CHECK constraints**

- `chk_rep_code`: `report_code REGEXP '^RP-[0-9]{4}-[0-9]{4}$'`
- `chk_rep_approval`: `(status = 'Approved' AND approved_by IS NOT NULL AND approved_at IS NOT NULL) OR (status <> 'Approved' AND approved_by IS NULL AND approved_at IS NULL)`
- `chk_rep_submitted`: `status = 'Draft' OR submitted_at IS NOT NULL`
- `chk_rep_independent`: `approved_by IS NULL OR approved_by <> author_id`

## report_versions

Immutable content snapshots (append-only)

| Column | Type | Keys | Null | Notes |
| --- | --- | --- | --- | --- |
| `version_id` | INT UNSIGNED | PK | NN | AUTO_INCREMENT |
| `report_id` | INT UNSIGNED | FK → `forensic_reports.report_id`; UK (uq_rv_report_version) | NN |  |
| `version_no` | SMALLINT UNSIGNED | UK (uq_rv_report_version) | NN |  |
| `methodology` | TEXT |  | NULL |  |
| `observations` | TEXT |  | NULL |  |
| `findings` | TEXT |  | NULL |  |
| `conclusions` | TEXT |  | NULL |  |
| `limitations` | TEXT |  | NULL |  |
| `change_note` | VARCHAR(255) |  | NN |  |
| `created_by` | INT UNSIGNED | FK → `users.user_id` | NN |  |
| `created_at` | DATETIME |  | NN | Default CURRENT_TIMESTAMP |

**CHECK constraints**

- `chk_rv_version`: `version_no >= 1`

## report_examinations

Reports <-> examinations (many-to-many)

| Column | Type | Keys | Null | Notes |
| --- | --- | --- | --- | --- |
| `report_id` | INT UNSIGNED | PK; FK → `forensic_reports.report_id` | NN |  |
| `examination_id` | INT UNSIGNED | PK; FK → `examinations.examination_id` | NN |  |
| `linked_at` | DATETIME |  | NN | Default CURRENT_TIMESTAMP |

## audit_logs

Append-only activity record (no secrets, ever)

| Column | Type | Keys | Null | Notes |
| --- | --- | --- | --- | --- |
| `audit_id` | BIGINT UNSIGNED | PK | NN | AUTO_INCREMENT |
| `user_id` | INT UNSIGNED | FK → `users.user_id` | NULL |  |
| `action` | VARCHAR(50) |  | NN |  |
| `entity_type` | ENUM |  | NULL |  |
| `entity_ref` | VARCHAR(40) |  | NULL |  |
| `outcome` | ENUM('Success','Failure','Denied') |  | NN |  |
| `details` | VARCHAR(500) |  | NULL |  |
| `ip_address` | VARCHAR(45) |  | NULL |  |
| `created_at` | DATETIME(3) |  | NN | Default CURRENT_TIMESTAMP(3) |
