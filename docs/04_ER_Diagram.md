# 04. ER Diagram

**Status:** Complete for Step 2 (MySQL Database Architecture phase)

## 1. Scope

This diagram covers all 21 entities implemented in `database/02_tables.sql`.
Two tables — `case_investigators` and `case_persons` — are **associative
(junction) entities** materializing many-to-many relationships between
`cases`↔`users` and `cases`↔`persons` respectively. They are drawn as full
entities (not plain lines) because they carry their own attributes
(`role_in_case`, `person_role`, timestamps).

## 2. Mermaid ER Diagram

```mermaid
erDiagram
    ROLES {
        smallint role_id PK
        varchar role_name UK
    }
    DEPARTMENTS {
        smallint department_id PK
        varchar department_name UK
        varchar department_code UK
    }
    LOCATIONS {
        int location_id PK
        varchar location_name
        enum location_type
        varchar city
    }
    CASE_TYPES {
        smallint case_type_id PK
        varchar type_name UK
    }
    USERS {
        bigint user_id PK
        varchar badge_number UK
        varchar username UK
        varchar email UK
        smallint role_id FK
        smallint department_id FK
    }
    CASES {
        bigint case_id PK
        varchar case_number UK
        smallint case_type_id FK
        int jurisdiction_location_id FK
        bigint created_by FK
        enum status
    }
    CASE_INVESTIGATORS {
        bigint case_id PK_FK
        bigint user_id PK_FK
        enum role_in_case
    }
    PERSONS {
        bigint person_id PK
        varchar national_id_number UK
        varchar first_name
        varchar last_name
    }
    CASE_PERSONS {
        bigint case_id PK_FK
        bigint person_id PK_FK
        enum person_role PK
    }
    DEVICE_TYPES {
        smallint device_type_id PK
        varchar type_name UK
    }
    DEVICES {
        bigint device_id PK
        bigint case_id FK
        smallint device_type_id FK
        bigint owner_person_id FK
        int seized_location_id FK
        int current_location_id FK
        varchar serial_number
    }
    EVIDENCE_TYPES {
        smallint evidence_type_id PK
        varchar type_name UK
    }
    EVIDENCE {
        bigint evidence_id PK
        varchar evidence_number UK
        bigint case_id FK
        bigint device_id FK
        smallint evidence_type_id FK
        bigint collected_by FK
        int storage_location_id FK
    }
    EVIDENCE_HASHES {
        bigint hash_id PK
        bigint evidence_id FK
        enum hash_algorithm
        varchar hash_value
        bigint computed_by FK
    }
    CHAIN_OF_CUSTODY {
        bigint custody_id PK
        bigint evidence_id FK
        bigint transferred_from FK
        bigint transferred_to FK
        int location_id FK
        enum custody_action
    }
    FORENSIC_TOOLS {
        int tool_id PK
        varchar tool_name
        varchar version
    }
    EVIDENCE_EXAMINATIONS {
        bigint examination_id PK
        bigint evidence_id FK
        int tool_id FK
        bigint examiner_id FK
    }
    FORENSIC_REPORTS {
        bigint report_id PK
        varchar report_number UK
        bigint case_id FK
        bigint prepared_by FK
        bigint reviewed_by FK
    }
    REPORT_VERSIONS {
        bigint version_id PK
        bigint report_id FK
        smallint version_number
        bigint created_by FK
    }
    CASE_TIMELINE {
        bigint timeline_id PK
        bigint case_id FK
        bigint recorded_by FK
        enum event_type
    }
    AUDIT_LOGS {
        bigint audit_id PK
        bigint user_id FK
        varchar table_name
        enum action_type
    }

    ROLES ||--o{ USERS : "has"
    DEPARTMENTS ||--o{ USERS : "has"
    CASE_TYPES ||--o{ CASES : "categorizes"
    LOCATIONS ||--o{ CASES : "jurisdiction of"
    USERS ||--o{ CASES : "opens"
    CASES ||--o{ CASE_INVESTIGATORS : "is assigned via"
    USERS ||--o{ CASE_INVESTIGATORS : "is assigned via"
    CASES ||--o{ CASE_PERSONS : "links via"
    PERSONS ||--o{ CASE_PERSONS : "links via"
    CASES ||--o{ DEVICES : "has seized"
    DEVICE_TYPES ||--o{ DEVICES : "categorizes"
    PERSONS ||--o{ DEVICES : "owns"
    LOCATIONS ||--o{ DEVICES : "stores"
    CASES ||--o{ EVIDENCE : "contains"
    DEVICES ||--o{ EVIDENCE : "yields"
    EVIDENCE_TYPES ||--o{ EVIDENCE : "categorizes"
    USERS ||--o{ EVIDENCE : "collects"
    LOCATIONS ||--o{ EVIDENCE : "stores"
    EVIDENCE ||--o{ EVIDENCE_HASHES : "is verified by"
    USERS ||--o{ EVIDENCE_HASHES : "computes"
    EVIDENCE ||--o{ CHAIN_OF_CUSTODY : "is tracked by"
    USERS ||--o{ CHAIN_OF_CUSTODY : "transfers"
    LOCATIONS ||--o{ CHAIN_OF_CUSTODY : "occurs at"
    EVIDENCE ||--o{ EVIDENCE_EXAMINATIONS : "undergoes"
    FORENSIC_TOOLS ||--o{ EVIDENCE_EXAMINATIONS : "is used in"
    USERS ||--o{ EVIDENCE_EXAMINATIONS : "performs"
    CASES ||--o{ FORENSIC_REPORTS : "produces"
    USERS ||--o{ FORENSIC_REPORTS : "prepares / reviews"
    FORENSIC_REPORTS ||--o{ REPORT_VERSIONS : "has"
    USERS ||--o{ REPORT_VERSIONS : "authors"
    CASES ||--o{ CASE_TIMELINE : "logs"
    USERS ||--o{ CASE_TIMELINE : "records"
    USERS ||--o{ AUDIT_LOGS : "performs"
```

## 3. Cardinality Legend

| Symbol | Meaning |
|---|---|
| `\|\|--o{` | One (mandatory) to zero-or-many |
| `PK` | Primary key |
| `PK_FK` | Column is part of a composite primary key **and** a foreign key |
| `FK` | Foreign key (references another entity's PK) |
| `UK` | Column carries a UNIQUE constraint (candidate key) |

## 4. Relationships Requiring a Nullable FK (optional participation)

Mermaid's crow's-foot notation above always shows the "many" side as
mandatory-parent for simplicity; the following FKs are actually **nullable**
(optional participation), meaning the child row can legitimately exist
without that particular parent:

| Table.Column | Why nullable |
|---|---|
| `cases.jurisdiction_location_id` | Jurisdiction may not be finalized when a case is opened |
| `devices.owner_person_id` | Device owner may be unknown at seizure time |
| `devices.serial_number` | Some devices have no visible/readable serial |
| `devices.seized_location_id` / `current_location_id` | Location may not yet be logged |
| `evidence.device_id` | Evidence is not always device-derived (e.g. a physical document) |
| `evidence.storage_location_id` | Storage location may be pending assignment |
| `chain_of_custody.transferred_from` | NULL only on the very first ("collected") custody entry |
| `forensic_reports.reviewed_by` | A report may still be in `draft`, unreviewed |
| `evidence_examinations.completed_at` | Examination may still be `in_progress` |
| `audit_logs.user_id` | Some audit rows are system/trigger-generated, not user-initiated |

## 5. Many-to-Many Relationships and Their Junction Tables

| Relationship | Junction Table | Extra Attributes Carried |
|---|---|---|
| `cases` ↔ `users` (investigator assignment) | `case_investigators` | `role_in_case`, `assigned_at`, `unassigned_at` |
| `cases` ↔ `persons` (persons of interest) | `case_persons` | `person_role`, `notes`, `linked_at` |

Every many-to-many relationship in the requirement list has a dedicated
junction table with a composite primary key — no comma-separated ID lists
and no multivalued columns appear anywhere in the schema.

## 6. Root-to-Leaf Lifecycle Path

```
cases → devices → evidence → evidence_hashes
                           → chain_of_custody
                           → evidence_examinations
      → forensic_reports → report_versions
      → case_timeline
users → audit_logs
```

This mirrors the project's central principle:
**Case → Person → Device → Evidence → Hash → Chain of Custody →
Examination → Report → Audit Trail.**
