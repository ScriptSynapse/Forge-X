# 06. Normalization

**Status:** Complete for Step 2 (MySQL Database Architecture phase)

This document proves that every relation in `database/02_tables.sql`
satisfies 1NF, 2NF, and 3NF, and separately documents the one place a
deliberate, justified denormalization decision was made.

## 1. First Normal Form (1NF)

**Rule:** every attribute holds a single atomic value; no repeating
groups; no multivalued attributes; every row is uniquely identifiable.

**How FORGE-X satisfies this:**

- **No comma-separated / multi-valued columns anywhere.** The most
  tempting place to violate this would have been "which investigators
  are on this case" or "which roles does this person have in this
  case." Both are pulled out into their own relations
  (`case_investigators`, `case_persons`) instead of being stored as a
  CSV string or a list inside a single `cases` row.
- **No repeating groups.** For example, `evidence_hashes` is a separate
  table with one row per (evidence, algorithm) pair, instead of adding
  `md5_hash`, `sha1_hash`, `sha256_hash`, `sha512_hash` columns to
  `evidence` — which would have been a classic 1NF violation (a
  repeating group of "hash slots") and would also make it impossible to
  cleanly add a new algorithm later without an `ALTER TABLE`.
- **Every table has a primary key** (surrogate or composite), so every
  row is uniquely addressable — a 1NF requirement.
- **JSON columns are the one nuance:** `audit_logs.old_values` /
  `new_values` are `JSON`, which technically stores a compound value.
  This is intentional and standard practice for a generic audit table
  (see §4, Denormalization) — the *column* still holds a single atomic
  JSON document per row; MySQL's native JSON type validates and indexes
  it, so this does not create the classic 1NF problems (no reliable
  ability to query/update individual sub-fields with plain SQL) that a
  raw delimited string would.

## 2. Second Normal Form (2NF)

**Rule:** must already be in 1NF, and every non-key attribute must be
**fully** functionally dependent on the **whole** primary key — i.e. no
partial dependency on only part of a composite key.

2NF is only a meaningful question for tables with a **composite**
primary key. In this schema that is exactly two tables:

### `case_investigators` — PK (`case_id`, `user_id`)

| Attribute | Depends on |
|---|---|
| `role_in_case` | the *pairing* of this case and this user — the same user has a different role on a different case, and the same case has different roles for different users. Not derivable from `case_id` alone or `user_id` alone. |
| `assigned_at`, `unassigned_at` | the specific assignment event, i.e. the full (case, user) pair |

No column depends on `case_id` alone or `user_id` alone → **no partial
dependency → 2NF holds.**

### `case_persons` — PK (`case_id`, `person_id`, `person_role`)

| Attribute | Depends on |
|---|---|
| `notes` | this specific (case, person, role) triple — the same person can be both a *witness* and a *device owner* in the same case, each with different notes |
| `linked_at` | the specific linking event for that (case, person, role) triple |

No column depends on any strict subset of the three key columns →
**2NF holds.**

Every other table in the schema uses a **single-column surrogate
primary key**, so 2NF is automatically satisfied (a single-column key
cannot have a "partial" dependency by definition).

## 3. Third Normal Form (3NF)

**Rule:** must already be in 2NF, and no non-key attribute may be
transitively dependent on the primary key through another non-key
attribute (i.e. no non-key attribute determines another non-key
attribute).

This is where most real-world schema mistakes happen — usually by
"caching" a lookup value directly on the child row. FORGE-X avoids this
throughout:

| Potential transitive dependency | How it's avoided |
|---|---|
| `users.department_id → department_name` | `users` stores only `department_id` (FK). `department_name` lives solely in `departments`. Looking it up requires a `JOIN`, not a duplicated column. |
| `users.role_id → role_name` | Same pattern — `roles.role_name` is not duplicated into `users`. |
| `cases.case_type_id → type_name` | `cases` stores only `case_type_id`. |
| `devices.device_type_id → type_name` | Same pattern. |
| `evidence.evidence_type_id → type_name` | Same pattern. |
| `evidence_examinations.tool_id → tool_name`/`vendor` | `evidence_examinations` stores only `tool_id`; tool metadata lives only in `forensic_tools`. |
| `*.location_id → location_name/city/...` | Every table that references a location (`cases`, `devices` ×2, `evidence`, `chain_of_custody`) stores only the FK, never a copied address/city. |
| `evidence.case_id` and `devices.case_id` both existing | This is **not** a transitive-dependency violation: `evidence.case_id` is not derived from `evidence.device_id → devices.case_id`; it is stored directly because an evidence item can exist *without* a device (`device_id` is nullable — e.g. a physical document). If `case_id` were dropped from `evidence` and only reachable via `device_id`, device-less evidence would have no case at all. Storing both is required, not redundant. |

Because every non-key attribute in every table describes **only** the
entity named by that table's primary key — never a fact about a
different entity reachable through a FK — **no table has a transitive
dependency, and 3NF holds across the schema.**

### Worked example: `evidence`

```
evidence(evidence_id PK, evidence_number, case_id FK, device_id FK,
         evidence_type_id FK, description, file_path, file_size_bytes,
         acquisition_method, collected_by FK, collected_at,
         storage_location_id FK, integrity_status, ...)
```

Every non-key column here (`evidence_number`, `description`,
`file_path`, `file_size_bytes`, `acquisition_method`, `collected_at`,
`integrity_status`) is a fact **about this specific evidence item**,
not about the case, device, type, collector, or storage location it
references. Those related facts stay in `cases`, `devices`,
`evidence_types`, `users`, and `locations` respectively, reachable only
by `JOIN`. That is precisely the 3NF requirement.

## 4. Legitimate Denormalization

Only one deliberate denormalization decision was made, and it is
isolated to a single table:

### `case_timeline.event_description` (and `related_table` / `related_record_id`)

`case_timeline` stores a short, human-readable, pre-written description
of each lifecycle event (e.g. *"Evidence EVD-2026-000456 collected by
J. Doe"*) rather than requiring the UI to reconstruct that sentence on
every page load by joining across `evidence`, `chain_of_custody`,
`evidence_examinations`, `forensic_reports`, and `users` and re-deriving
which of those five event sources fired.

This is an accepted, standard **event-log / audit-narrative pattern**,
not a violation of 3NF, for two reasons:

1. `event_description` is not *copied* from another table's column — it
   is a distinct fact (*"this human-readable sentence was shown to
   users at this point in time"*) that would not exist without the
   `case_timeline` row itself. There is no single source-of-truth
   column it duplicates.
2. `related_table` / `related_record_id` are an intentionally
   **polymorphic, non-FK-enforced** pointer (by design — a true FK
   can't reference "one of five possible tables"). This trade-off is
   explicit: the schema gives up strict referential integrity on that
   one pointer in exchange for a single, simple timeline table instead
   of five separate timeline tables or a complex table-per-relationship
   design. Application code, not the database, is responsible for
   keeping `related_table`/`related_record_id` meaningful.

No other denormalization exists anywhere in the schema — every lookup
value (role, department, case type, device type, evidence type,
location, tool) is referenced by FK only, never copied.

## 5. Summary

| Normal Form | Status | Basis |
|---|---|---|
| 1NF | ✅ Satisfied | Atomic columns, no repeating groups, PK on every table |
| 2NF | ✅ Satisfied | Only 2 composite-PK tables exist; both fully key-dependent |
| 3NF | ✅ Satisfied | No non-key column anywhere describes a different entity than its own table's PK |
| Denormalization | 1 deliberate instance | `case_timeline`, justified above — an event log, not duplicated data |
