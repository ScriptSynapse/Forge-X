# 05. Relational Schema

**Status:** Complete for Step 2 (MySQL Database Architecture phase)
**Source of truth:** `database/02_tables.sql` (this document is a readable
mirror of that file — if they ever disagree, the SQL file wins)

## 1. Notation

Standard relational-schema (Codd) notation is used below:

```
table_name(column PK, column FK->other_table.column, column UK, column NOT NULL, ...)
```

- `PK` = primary key (composite PKs list all participating columns)
- `FK->table.column` = foreign key reference
- `UK` = participates in a UNIQUE constraint (candidate key)
- Columns not marked `NULL` are `NOT NULL`
- Default values and CHECKs are called out in prose beneath each schema line

## 2. Full Relational Schema (21 Relations)

### Reference / lookup relations

```
roles(role_id PK, role_name UK, role_description NULL, created_at)

departments(department_id PK, department_name UK, department_code UK, created_at)

locations(location_id PK, location_name, location_type, address_line NULL,
          city NULL, state NULL, country, postal_code NULL, created_at)
    UNIQUE(location_name, city)

case_types(case_type_id PK, type_name UK, type_description NULL, created_at)

device_types(device_type_id PK, type_name UK, type_description NULL)

evidence_types(evidence_type_id PK, type_name UK, type_description NULL)

forensic_tools(tool_id PK, tool_name, vendor NULL, version NULL, license_type, created_at)
    UNIQUE(tool_name, version)
```

### Actor / subject relations

```
users(user_id PK, badge_number UK, username UK, email UK, password_hash,
      full_name, role_id FK->roles.role_id, department_id FK->departments.department_id,
      phone_number NULL, is_active, last_login_at NULL, created_at, updated_at)
    CHECK (email LIKE '%_@_%.__%')
    CHECK (is_active IN (0,1))

persons(person_id PK, first_name, last_name, date_of_birth NULL,
        national_id_number UK NULL, gender, phone_number NULL, email NULL,
        address NULL, created_at, updated_at)
```

### Case relations

```
cases(case_id PK, case_number UK, case_title,
      case_type_id FK->case_types.case_type_id,
      status, priority,
      jurisdiction_location_id FK->locations.location_id NULL,
      description NULL, opened_at, closed_at NULL,
      created_by FK->users.user_id, created_at, updated_at)
    CHECK (closed_at IS NULL OR closed_at >= opened_at)

case_investigators(case_id PK FK->cases.case_id,
                    user_id PK FK->users.user_id,
                    role_in_case, assigned_at, unassigned_at NULL)
    CHECK (unassigned_at IS NULL OR unassigned_at >= assigned_at)

case_persons(case_id PK FK->cases.case_id,
             person_id PK FK->persons.person_id,
             person_role PK,
             notes NULL, linked_at)
```

### Device / evidence relations

```
devices(device_id PK, case_id FK->cases.case_id,
        device_type_id FK->device_types.device_type_id,
        owner_person_id FK->persons.person_id NULL,
        serial_number NULL, make NULL, model NULL, imei_number NULL,
        storage_capacity_gb NULL,
        seized_at NULL, seized_location_id FK->locations.location_id NULL,
        current_location_id FK->locations.location_id NULL,
        device_status, created_at, updated_at)
    CHECK (storage_capacity_gb IS NULL OR storage_capacity_gb >= 0)

evidence(evidence_id PK, evidence_number UK,
         case_id FK->cases.case_id,
         device_id FK->devices.device_id NULL,
         evidence_type_id FK->evidence_types.evidence_type_id,
         description, file_path NULL, file_size_bytes NULL,
         acquisition_method, collected_by FK->users.user_id, collected_at,
         storage_location_id FK->locations.location_id NULL,
         integrity_status, created_at, updated_at)
    CHECK (file_size_bytes IS NULL OR file_size_bytes >= 0)

evidence_hashes(hash_id PK, evidence_id FK->evidence.evidence_id,
                hash_algorithm, hash_value, computed_by FK->users.user_id,
                computed_at, is_original)
    UNIQUE(evidence_id, hash_algorithm, hash_value, computed_at)  -- widened in Step 5, see 07_procedures.sql
    CHECK (CHAR_LENGTH(hash_value) >= 32)
    CHECK (is_original IN (0,1))

chain_of_custody(custody_id PK, evidence_id FK->evidence.evidence_id,
                  transferred_from FK->users.user_id NULL,
                  transferred_to FK->users.user_id,
                  custody_action, location_id FK->locations.location_id,
                  custody_timestamp, remarks NULL, signature_hash NULL)
    CHECK (transferred_from IS NULL OR transferred_from <> transferred_to)

evidence_examinations(examination_id PK, evidence_id FK->evidence.evidence_id,
                       tool_id FK->forensic_tools.tool_id,
                       examiner_id FK->users.user_id,
                       examination_type, started_at, completed_at NULL,
                       findings_summary NULL, examination_status, created_at)
    CHECK (completed_at IS NULL OR completed_at >= started_at)
```

### Reporting relations

```
forensic_reports(report_id PK, case_id FK->cases.case_id,
                  report_number UK, title,
                  prepared_by FK->users.user_id,
                  reviewed_by FK->users.user_id NULL,
                  report_status, created_at, finalized_at NULL)
    CHECK (reviewed_by IS NULL OR reviewed_by <> prepared_by)

report_versions(version_id PK, report_id FK->forensic_reports.report_id,
                 version_number, file_path, content_hash NULL,
                 change_summary NULL, created_by FK->users.user_id, created_at)
    UNIQUE(report_id, version_number)
    CHECK (version_number >= 1)
```

### Timeline / audit relations

```
case_timeline(timeline_id PK, case_id FK->cases.case_id, event_type,
              event_description, related_table NULL, related_record_id NULL,
              event_timestamp, recorded_by FK->users.user_id)

audit_logs(audit_id PK, user_id FK->users.user_id NULL, table_name,
           record_id, action_type, old_values NULL, new_values NULL,
           action_timestamp, ip_address NULL)
```

## 3. Constraint Summary (quick-reference table)

| Table | PK | Composite Key? | Candidate Key(s) / UNIQUE | Notable CHECK |
|---|---|---|---|---|
| roles | role_id | No | role_name | — |
| departments | department_id | No | department_name, department_code | — |
| locations | location_id | No | (location_name, city) | — |
| case_types | case_type_id | No | type_name | — |
| device_types | device_type_id | No | type_name | — |
| evidence_types | evidence_type_id | No | type_name | — |
| forensic_tools | tool_id | No | (tool_name, version) | — |
| users | user_id | No | badge_number, username, email | email format, is_active in (0,1) |
| persons | person_id | No | national_id_number | — |
| cases | case_id | No | case_number | closed_at ≥ opened_at |
| **case_investigators** | (case_id, user_id) | **Yes** | — | unassigned_at ≥ assigned_at |
| **case_persons** | (case_id, person_id, person_role) | **Yes** | — | — |
| devices | device_id | No | — | storage_capacity_gb ≥ 0 |
| evidence | evidence_id | No | evidence_number | file_size_bytes ≥ 0 |
| evidence_hashes | hash_id | No | (evidence_id, hash_algorithm, hash_value, computed_at) | hash length ≥ 32 |
| chain_of_custody | custody_id | No | — | transferred_from ≠ transferred_to |
| evidence_examinations | examination_id | No | — | completed_at ≥ started_at |
| forensic_reports | report_id | No | report_number | reviewed_by ≠ prepared_by |
| report_versions | version_id | No | (report_id, version_number) | version_number ≥ 1 |
| case_timeline | timeline_id | No | — | — |
| audit_logs | audit_id | No | — | — |

Two genuinely **composite primary keys** exist (`case_investigators`,
`case_persons`) — both are pure junction tables where the natural key
really is the combination of foreign keys (plus, for `case_persons`,
the role, since one person can legitimately hold more than one role on
the same case). Every other table uses a single-column surrogate
`BIGINT UNSIGNED` / `INT UNSIGNED` / `SMALLINT UNSIGNED` primary key,
with the real-world business identifier (e.g. `case_number`,
`evidence_number`, `badge_number`) enforced separately as a candidate
key via `UNIQUE`.

## 4. Why Surrogate Keys + Separate Business Keys

Every entity that has a natural, human-meaningful identifier
(`case_number`, `evidence_number`, `report_number`, `badge_number`,
`username`, `email`, `national_id_number`) still gets a surrogate
`AUTO_INCREMENT` primary key. This is a deliberate design choice, not
redundancy:

- Surrogate keys never change, so every foreign key in the schema stays
  stable even if a business identifier format is revised later.
- The business identifier is preserved as its true role — a **candidate
  key** — via a `UNIQUE` constraint, not silently dropped.
- Joins across 5–6 tables deep (e.g. `evidence → chain_of_custody →
  users`) stay cheap: `BIGINT UNSIGNED` joins are faster than
  `VARCHAR` joins.

## 5. Data Type Justification

| Choice | Where used | Why |
|---|---|---|
| `BIGINT UNSIGNED` | Surrogate PK/FK on high-volume tables (`users`, `cases`, `evidence`, `chain_of_custody`, `audit_logs`, ...) | Evidence/audit tables can grow very large over years of case history; unsigned avoids wasting a bit on negative values that can never occur |
| `SMALLINT UNSIGNED` / `INT UNSIGNED` | Low-cardinality lookup tables (`roles`, `case_types`, `device_types`) and mid-cardinality ones (`locations`, `forensic_tools`) | Right-sized for the expected row count — no need to pay 8 bytes for a table that will hold a few dozen rows |
| `DATETIME` | Every timestamp column | Required by the brief; stores calendar date+time without timezone conversion surprises, paired with `SET time_zone='+00:00'` at the session level |
| `DECIMAL(10,2)` | `devices.storage_capacity_gb` | Exact numeric precision — a `FLOAT`/`DOUBLE` could introduce rounding error when reporting device capacity in a forensic document |
| `ENUM(...)` | Controlled-vocabulary status/type columns not listed as their own required entity (e.g. `cases.status`, `devices.device_status`, `evidence.acquisition_method`) | Enforces a closed set of values at the storage engine level without needing an extra lookup table for every single status field |
| `JSON` | `audit_logs.old_values` / `new_values` | Row snapshots have a different shape per source table; JSON lets one audit table serve all 20 other tables without 20 sets of nullable columns |
| `CHAR(60)` | `users.password_hash` | bcrypt hashes are always exactly 60 characters — fixed-length `CHAR` is both correct and marginally faster than `VARCHAR` here |
| `VARCHAR(n)` | Free-text identifiers/names with a sensible upper bound | Used everywhere else, with `n` sized to the realistic maximum for that field rather than a blanket `VARCHAR(255)` |

## 6. Relationship List (all FKs, at a glance)

1. `roles` (1) → `users` (N)
2. `departments` (1) → `users` (N)
3. `case_types` (1) → `cases` (N)
4. `locations` (1) → `cases` (N) — jurisdiction, optional
5. `users` (1) → `cases` (N) — created_by
6. `cases` (1) → `case_investigators` (N) / `users` (1) → `case_investigators` (N) — resolves cases↔users M:N
7. `cases` (1) → `case_persons` (N) / `persons` (1) → `case_persons` (N) — resolves cases↔persons M:N
8. `cases` (1) → `devices` (N)
9. `device_types` (1) → `devices` (N)
10. `persons` (1) → `devices` (N) — owner, optional
11. `locations` (1) → `devices` (N) — seized location, optional
12. `locations` (1) → `devices` (N) — current location, optional
13. `cases` (1) → `evidence` (N)
14. `devices` (1) → `evidence` (N) — optional
15. `evidence_types` (1) → `evidence` (N)
16. `users` (1) → `evidence` (N) — collected_by
17. `locations` (1) → `evidence` (N) — storage, optional
18. `evidence` (1) → `evidence_hashes` (N)
19. `users` (1) → `evidence_hashes` (N) — computed_by
20. `evidence` (1) → `chain_of_custody` (N)
21. `users` (1) → `chain_of_custody` (N) — transferred_from (optional) / transferred_to
22. `locations` (1) → `chain_of_custody` (N)
23. `evidence` (1) → `evidence_examinations` (N)
24. `forensic_tools` (1) → `evidence_examinations` (N)
25. `users` (1) → `evidence_examinations` (N) — examiner_id
26. `cases` (1) → `forensic_reports` (N)
27. `users` (1) → `forensic_reports` (N) — prepared_by / reviewed_by (optional)
28. `forensic_reports` (1) → `report_versions` (N)
29. `users` (1) → `report_versions` (N) — created_by
30. `cases` (1) → `case_timeline` (N)
31. `users` (1) → `case_timeline` (N) — recorded_by
32. `users` (1) → `audit_logs` (N) — optional
