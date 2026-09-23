# 09. API Documentation

**Status:** Complete through Step 7 (Authentication & Role-Based Access Control)
**Base URL:** `http://localhost:4000/api` (configurable via `PORT` in `.env`)
**Database:** the same `forge_x` MySQL database built in Steps 1-5 — this
backend creates no database or schema of its own.

Every endpoint below was tested live against the seeded `forge_x`
database during development (not just written and assumed correct).

## 1. Conventions

### Authentication
All endpoints except `POST /api/auth/login` and `GET /health` require:
```
Authorization: Bearer <JWT>
```
Tokens are issued by `POST /api/auth/login`, carry a unique `jti` claim,
and expire per `JWT_EXPIRES_IN` in `.env` (default 8h). `POST
/api/auth/logout` immediately revokes the presented token's `jti` —
see §3 and §19 for the full mechanism.

### Authorization
This is a resource + action permission system (Step 7), not a flat
per-route role list: see **§19 — Roles & Permissions** for the full
matrix and demo credentials for every role. In short: each of the 6
roles (`ADMIN`, `LEAD_INVESTIGATOR`, `INVESTIGATOR`, `FORENSIC_ANALYST`,
`EVIDENCE_CUSTODIAN`, `VIEWER`) is granted `read` and/or `write` on a
specific set of resources, checked server-side on every request via
`requirePermission(resource, action)` — never trust a hidden button.
`INVESTIGATOR` additionally has a **row-level** restriction: even where
granted `read`/`write` on `cases`/`evidence`/`timeline`, it only applies
to cases they are actually assigned to (`case_investigators`), enforced
by a second middleware layer and by filtering list-endpoint results at
the SQL level, not just blocking direct-ID access. An authenticated
user outside a resource's allowed roles, or an `INVESTIGATOR` outside
their assigned cases, gets `403 Forbidden`. Each endpoint below states
its role restriction.

### Response envelope
- Success: `{ "data": ... }`, list endpoints add `"pagination": { page, pageSize, total, totalPages }`
- Error: `{ "error": { "message": "...", "details"?: [...] } }`

### Pagination (list endpoints)
Query params: `page` (default 1), `pageSize` (default 20, max 100).

### Errors
| HTTP | Meaning | Example cause |
|---|---|---|
| 400 | Bad request / validation failed | Zod schema rejected the body, or a `SIGNAL SQLSTATE '45000'` business-rule error from a stored procedure |
| 401 | Not authenticated | Missing/invalid/expired JWT |
| 403 | Not authorized | Authenticated, but role not permitted |
| 404 | Not found | ID doesn't exist |
| 409 | Conflict | A UNIQUE constraint was violated, or an `ON DELETE RESTRICT` FK blocked the operation |
| 500 | Server error | Unexpected failure (details never leak to the client outside development mode) |

MySQL errors are translated by `src/utils/mysqlErrorMap.ts` — most
importantly, every `SIGNAL SQLSTATE '45000'` message written in
`07_procedures.sql` / `08_triggers.sql` is already plain English and is
passed straight through as the `400` response's `message`, unchanged.

### The `@forgex_actor_id` convention
Every write that should be attributed to the logged-in user goes through
`withActorConnection()` (`src/config/db.ts`), which sets the MySQL
session variable `@forgex_actor_id` for the duration of that request's
database work. Triggers in `08_triggers.sql` read this variable to
attribute automatically-generated `chain_of_custody` and `audit_logs`
rows to the real acting user, not a shared service account.

---

## 2. Auth

### `POST /api/auth/login`
No auth required.

**Body:**
```json
{ "username": "asharma", "password": "ForgeX@Demo2026" }
```
`username` matches `users.username` OR `users.email`.

**Response `200`:**
```json
{
  "data": {
    "token": "eyJhbGciOi...",
    "user": { "userId": 1, "username": "asharma", "roleId": 2, "roleName": "LEAD_INVESTIGATOR", "departmentId": 1, "fullName": "Ananya Sharma" },
    "expiresIn": "8h"
  }
}
```
**Errors:** `401` invalid credentials · `403` account deactivated (`users.is_active = 0`)

### `POST /api/auth/logout`
Auth required. Revokes the presented token's `jti` immediately (see §19)
— the exact same token is rejected with `401` on the very next request,
even though it has not yet reached its `exp`. Idempotent: logging out
an already-logged-out token returns `200` again rather than erroring.

**Response `200`:** `{ "data": { "message": "Logged out successfully. This token is no longer valid." } }`

### `GET /api/auth/me`
Auth required. Returns the caller's own identity, re-checked live against `users`.

---

## 3. Users — ADMIN only

### `GET /api/users`
**Role: ADMIN.** Query: `roleId`, `departmentId`, `isActive` (`0`/`1`), `page`, `pageSize`.

### `GET /api/users/:id`
**Role: ADMIN.**

### `PUT /api/users/:id`
**Role: ADMIN.**
**Body (all optional, at least one required):** `fullName`, `roleId`, `departmentId`, `phoneNumber`, `isActive`
Writes its own `audit_logs` row (no DB trigger watches `users`).

---

## 4. Cases

### `GET /api/cases`
**Role: ADMIN, LEAD_INVESTIGATOR, INVESTIGATOR, VIEWER.** Query: `status`, `priority`, `caseTypeId`, `search`, `page`, `pageSize`.
Built on **`vw_case_summary`** — every count (investigators, persons, devices, evidence, reports) is a live `COUNT(DISTINCT ...)`, never computed in JS.
**Row-level scoping:** for `INVESTIGATOR`, results are silently narrowed at the SQL layer to only cases they are assigned to (`case_investigators`) — this is filtering, not a `403`, since a partial list is the correct response for a list endpoint.

### `GET /api/cases/:id`
**Role: ADMIN, LEAD_INVESTIGATOR, INVESTIGATOR, VIEWER.** Returns the `vw_case_summary` row plus `investigators[]`, `persons[]`, `devices[]`, `evidence[]`, `reports[]`, `recentTimeline[]` (last 20 events), fetched in parallel.
**Row-level scoping:** `INVESTIGATOR` gets `403` for any case they are not assigned to, checked by `middleware/caseAccess.ts` against `case_investigators` before the handler runs.

### `POST /api/cases`
**Role: ADMIN, LEAD_INVESTIGATOR.**
**Body:**
```json
{ "caseNumber": "CASE-2026-006", "caseTitle": "...", "caseTypeId": 1,
  "priority": "medium", "jurisdictionLocationId": 3, "description": "..." }
```
Calls **`sp_create_case()`** — never a raw `INSERT`. Returns `201` with the new case's `vw_case_summary` row.
**Errors:** `400` invalid `caseTypeId`/`created_by` (from the procedure's own validation) · `409` duplicate `caseNumber`

### `PUT /api/cases/:id`
**Role: ADMIN, LEAD_INVESTIGATOR.**
**Body (partial):** `caseTitle`, `priority`, `jurisdictionLocationId`, `description`
Direct `UPDATE` (no procedure covers generic edits); writes its own `audit_logs` row.

### `PATCH /api/cases/:id/status`
**Role: ADMIN, LEAD_INVESTIGATOR.**
**Body:** `{ "status": "closed" }`
- If `status = "closed"` → calls **`sp_close_case()`**, which enforces: no open examinations, at least one `approved`/`finalized` report. Returns the procedure's own success message.
- Any other status → direct `UPDATE`, which `trg_cases_status_change` automatically logs to `case_timeline` as a `[CASE_STATUS_CHANGED]` event.
**Errors:** `400` with the exact `sp_close_case` rejection reason (e.g. *"cannot close - one or more examinations are still scheduled or in progress"*)

---

## 5. Investigators (nested under a case) — ADMIN, LEAD_INVESTIGATOR only

### `GET /api/cases/:caseId/investigators`
**Role: ADMIN, LEAD_INVESTIGATOR.** (`INVESTIGATOR` is not granted the `investigators` resource at all — not even for their own assigned case — per the spec's literal resource list.)

### `POST /api/cases/:caseId/investigators`
**Role: ADMIN, LEAD_INVESTIGATOR.**
**Body:** `{ "userId": 5, "roleInCase": "forensic_analyst" }`
Calls **`sp_assign_investigator()`**. **Errors:** `400` already assigned to this case (from the procedure)

### `DELETE /api/cases/:caseId/investigators/:userId`
**Role: ADMIN, LEAD_INVESTIGATOR.**
Soft-unassigns (`unassigned_at = NOW()`), never deletes the row. `204 No Content`.

---

## 6. Persons

### `GET /api/persons`
**Role: ADMIN, LEAD_INVESTIGATOR, VIEWER.** Query: `search` (matches first/last name or national ID — uses `idx_persons_name`).

### `GET /api/persons/:id`
**Role: ADMIN, LEAD_INVESTIGATOR, VIEWER.** Includes every case this person is linked to.

### `POST /api/persons`
**Role: ADMIN, LEAD_INVESTIGATOR.**
**Body:** `firstName`, `lastName`, `dateOfBirth?`, `nationalIdNumber?`, `gender?`, `phoneNumber?`, `email?`, `address?`

### `POST /api/cases/:caseId/persons`
**Role: ADMIN, LEAD_INVESTIGATOR.**
**Body:** `{ "personId": 3, "personRole": "witness", "notes": "..." }` — links a person to a case (`case_persons`).

---

## 7. Devices

### `GET /api/devices`
**Role: ADMIN, LEAD_INVESTIGATOR, VIEWER.** Query: `caseId`, `serialNumber` (uses `idx_devices_serial_number`), `imei` (uses `idx_devices_imei_number`).

### `GET /api/devices/:id`
**Role: ADMIN, LEAD_INVESTIGATOR, VIEWER.** Includes evidence items sourced from this device.

### `POST /api/devices`
**Role: ADMIN, LEAD_INVESTIGATOR.**
**Body:** `caseId`, `deviceTypeId`, `ownerPersonId?`, `serialNumber?`, `make?`, `model?`, `imeiNumber?`, `storageCapacityGb?`, `seizedLocationId?`

### `PUT /api/devices/:id`
**Role: ADMIN, LEAD_INVESTIGATOR.**
**Body (partial):** `deviceStatus`, `currentLocationId`, `ownerPersonId`

---

## 8. Evidence

### `GET /api/evidence`
**Role: ADMIN, LEAD_INVESTIGATOR, INVESTIGATOR, FORENSIC_ANALYST, EVIDENCE_CUSTODIAN, VIEWER.** Query: `caseId`, `integrityStatus`, `search`. Built on **`vw_evidence_integrity`**.
**Row-level scoping:** `INVESTIGATOR` only sees evidence belonging to their assigned cases.

### `GET /api/evidence/:id`
**Role: same as above, all read-granted roles.** Returns the integrity summary plus `custodyHistory[]`, `hashRecords[]`, `examinations[]`, current custodian — fetched in parallel.
**Row-level scoping:** `INVESTIGATOR` gets `403` for evidence belonging to a case they are not assigned to.

### `POST /api/evidence`
**Role: ADMIN, LEAD_INVESTIGATOR, INVESTIGATOR, FORENSIC_ANALYST.**
**Body:** `evidenceNumber`, `caseId`, `deviceId?`, `evidenceTypeId`, `description`, `acquisitionMethod`, `storageLocationId?`
Calls **`sp_register_evidence()`**, which atomically creates the evidence row (with `current_custodian_id` set to the collector), its first `chain_of_custody` `'collected'` entry, and a timeline event.
**Row-level scoping:** `INVESTIGATOR` gets `403` if `caseId` in the body is not a case they are assigned to (checked inline in the controller, since `caseId` is in the body, not a route param).

### `PUT /api/evidence/:id`
**Role: ADMIN, LEAD_INVESTIGATOR, INVESTIGATOR, FORENSIC_ANALYST.** (Row-scoped for `INVESTIGATOR`, as above.)
**Body (partial):** `description`, `integrityStatus`, `storageLocationId`, `filePath`, `evidenceTypeId`
Direct `UPDATE` — **`trg_evidence_important_changes_audit`** automatically writes the `audit_logs` row; the API does not duplicate that insert.

### `POST /api/evidence/:id/verify`
**Role: ADMIN, LEAD_INVESTIGATOR, FORENSIC_ANALYST.** (Uses the `evidenceHashes` permission; row-scoped for `INVESTIGATOR` if ever granted.)
**Body:** `{ "hashAlgorithm": "SHA256", "freshlyComputedHash": "..." }`
Calls **`sp_verify_evidence()`**, which uses `fn_compare_hash()` as the single source of truth for MATCH/MISMATCH — this endpoint contains no comparison logic of its own. On a mismatch, `integrity_status` is set to `requires_recheck` and an `audit_logs` row is written by the procedure.
**Response:** `{ "data": { "matchResult": "MATCH" | "MISMATCH", "evidence": {...} } }`

### `POST /api/evidence/:id/transfer` — **the flagship endpoint**
**Role: ADMIN, LEAD_INVESTIGATOR, INVESTIGATOR, FORENSIC_ANALYST, EVIDENCE_CUSTODIAN.** This is `EVIDENCE_CUSTODIAN`'s *entire* permission grant — "Evidence custody transfers" — modeled as its own `custodyTransfer` resource in the permission matrix, distinct from general `evidence` write, since a custodian should be able to transfer evidence without being able to edit its description or type.
**Row-level scoping:** `INVESTIGATOR` gets `403` for evidence belonging to a case they are not assigned to.
**Body:**
```json
{ "newCustodianId": 9, "expectedCurrentCustodianId": 2, "locationId": 2, "remarks": "..." }
```
`expectedCurrentCustodianId`, `locationId`, `remarks` are all optional.
Calls **`sp_transfer_evidence()`** directly — this endpoint contains **zero** custody-transfer logic of its own (no manual lock, no manual `chain_of_custody`/`audit_logs` insert). The procedure: locks the row, verifies the evidence exists, verifies the current custodian (and, if `expectedCurrentCustodianId` was supplied, that it still matches — a concurrency guard), verifies the new custodian is a real active user, updates `current_custodian_id` (which cascades a `chain_of_custody` row and an `audit_logs` row via `trg_evidence_custody_audit`), and inserts a `case_timeline` event.
**Errors (all `400`, exact procedure message passed through):**
- `evidence_id does not exist`
- `evidence has no current custodian on record to transfer from`
- `current custodian mismatch - evidence may have been transferred by someone else; refresh and retry`
- `new custodian is the same as the current custodian - nothing to transfer`
- `new custodian user_id does not exist` / `new custodian is not an active user`

---

## 9. Evidence Hashes (nested under evidence)

### `GET /api/evidence/:evidenceId/hashes`
**Role: ADMIN, LEAD_INVESTIGATOR, INVESTIGATOR, FORENSIC_ANALYST, EVIDENCE_CUSTODIAN, VIEWER.** Row-scoped for `INVESTIGATOR`.

### `POST /api/evidence/:evidenceId/hashes`
**Role: ADMIN, LEAD_INVESTIGATOR, FORENSIC_ANALYST.**
**Body:** `{ "hashAlgorithm": "SHA256", "hashValue": "...", "isOriginal"?: true }`
Logs an initial/reference hash at acquisition time. (Re-verifying against an *existing* reference goes through `POST /api/evidence/:id/verify` instead.)

---

## 10. Chain of Custody — **read-only everywhere**

### `GET /api/evidence/:evidenceId/custody`
**Role: every authenticated role has `custody`:read.** Row-scoped for `INVESTIGATOR` via the parent evidence item.
### `GET /api/custody` (system-wide; query `fromDate`, `toDate` — uses `idx_custody_timestamp`)
**Role: every authenticated role.** Not case-scoped (no single case context to check against a system-wide feed).

There is deliberately **no** write endpoint for `chain_of_custody` anywhere
in this API. Every row is created exactly one of two ways: `sp_register_evidence()`'s
initial entry, or `trg_evidence_custody_audit` firing when `sp_transfer_evidence()`
changes the custodian. The custody ledger is never hand-edited.

---

## 11. Examinations — ADMIN, FORENSIC_ANALYST (write); + VIEWER (read)

### `GET /api/examinations`
**Role: ADMIN, FORENSIC_ANALYST, VIEWER.** Query: `evidenceId`, `status`.
Note: `LEAD_INVESTIGATOR`/`INVESTIGATOR` are deliberately not granted this resource directly (neither lists "Examinations" in the spec), but still see examination data embedded in an authorized `GET /api/evidence/:id` response.

### `GET /api/examinations/:id`
**Role: ADMIN, FORENSIC_ANALYST, VIEWER.**

### `POST /api/examinations`
**Role: ADMIN, FORENSIC_ANALYST.**
**Body:** `evidenceId`, `toolId`, `examinationType`, `startedAt?`
Logs an `examination_started` timeline event.

### `PUT /api/examinations/:id`
**Role: ADMIN, FORENSIC_ANALYST.**
**Body (partial):** `examinationStatus`, `findingsSummary`, `completedAt`
Logs an `examination_completed` timeline event when status transitions to `completed`/`peer_reviewed`.

---

## 12. Reports

### `GET /api/reports`
**Role: ADMIN, LEAD_INVESTIGATOR, FORENSIC_ANALYST, VIEWER.** Query: `caseId`, `status`.

### `GET /api/reports/:id`
**Role: ADMIN, LEAD_INVESTIGATOR, FORENSIC_ANALYST, VIEWER.** Includes full `report_versions` history.

### `POST /api/reports`
**Role: ADMIN, LEAD_INVESTIGATOR, FORENSIC_ANALYST.**
**Body:** `caseId`, `reportNumber`, `title`, `filePath`
Atomically creates the report **and** its version 1, plus a `report_filed` timeline event.

### `PATCH /api/reports/:id/status`
**Role: ADMIN, LEAD_INVESTIGATOR, FORENSIC_ANALYST.**
**Body:** `{ "reportStatus": "approved", "reviewedBy"?: 4 }`
Rejects (`400`) if `reviewedBy` equals the preparer, matching `chk_reports_reviewer_ne_author`. Sets `finalized_at` automatically when status becomes `finalized`.

### `POST /api/reports/:id/versions`
**Role: ADMIN, LEAD_INVESTIGATOR, FORENSIC_ANALYST.**
**Body:** `{ "filePath": "...", "changeSummary"?: "..." }`
Appends the next `version_number` (protected from races by `uq_report_versions_report_version`).

---

## 13. Timeline (nested under a case) — read-only

### `GET /api/cases/:caseId/timeline`
**Role: ADMIN, LEAD_INVESTIGATOR, INVESTIGATOR, FORENSIC_ANALYST, VIEWER.** Paginated, newest first.
**Row-level scoping:** `INVESTIGATOR` gets `403` for any case they are not assigned to.

---

## 14. Audit Logs — ADMIN only, read-only

### `GET /api/audit-logs`
**Role: ADMIN.**
Query: `tableName`, `recordId`, `userId`, `actionType`, `fromDate`, `toDate`. Uses `idx_audit_logs_entity` for the `(tableName, recordId)` lookup pattern.

---

## 15. Dashboard — ADMIN, LEAD_INVESTIGATOR, VIEWER; every number is a live query

### `GET /api/dashboard/summary`
**Role: ADMIN, LEAD_INVESTIGATOR, VIEWER.** Returns:
```json
{
  "totalCases": 5, "activeCases": 3, "closedCases": 2,
  "evidenceCount": 30, "deviceCount": 15,
  "integrityAlerts": 2, "pendingExaminations": 3,
  "casesByStatus": [ { "status": "open", "count": 1 }, ... ],
  "casesByPriority": [ { "priority": "critical", "count": 1 }, ... ]
}
```
`integrityAlerts` = `COUNT(*) FROM vw_evidence_integrity WHERE integrity_status <> 'intact'`.
`activeCases` = `COUNT(*) FROM vw_active_cases`.

### `GET /api/dashboard/workload`
**Role: ADMIN, LEAD_INVESTIGATOR, VIEWER.** A direct pass-through of **`vw_investigator_workload`**.

### `GET /api/dashboard/integrity-alerts`
**Role: ADMIN, LEAD_INVESTIGATOR, VIEWER.** The evidence rows behind the `integrityAlerts` count, for drill-down.

## 16. Security implementation summary

| Requirement | Implementation |
|---|---|
| Input validation | Zod schemas (`src/validators/*.ts`) on every `body`/`params`/`query`, applied via `middleware/validate.ts` |
| SQL injection protection | Every query uses `?` parameterized placeholders (`mysql2`) — user input is never string-concatenated into SQL, anywhere in the codebase |
| Environment variables | `src/config/env.ts` loads and validates `.env`; process exits at startup if anything required is missing. `.env.example` provided, `.env` gitignored |
| Error handling | Single centralized `middleware/errorHandler.ts`; MySQL errors mapped by `utils/mysqlErrorMap.ts`; stack traces never leave the process outside development |
| Password hashing | `bcryptjs`, `BCRYPT_SALT_ROUNDS` (default 12) from `.env`; `users.password_hash` is `CHAR(60)`, never returned in any API response |
| Authentication middleware | `middleware/authenticate.ts` — JWT verification (+ `jti` revocation check), populates `req.user` |
| Session/logout | JWT + server-side revocation store (`utils/tokenBlocklist.ts`) — see §19.4 |
| Authorization middleware | `middleware/authorize.ts` (`requirePermission`) — a centralized resource×action×role matrix (`config/permissions.ts`), not scattered per-route role lists; plus `middleware/caseAccess.ts` for `INVESTIGATOR`'s row-level "assigned cases only" scoping — see §19 |
| Least-privilege DB user | The backend connects as `forgex_app`, a MySQL user granted only `SELECT, INSERT, UPDATE, DELETE, EXECUTE` on `forge_x.*` — it cannot `DROP`/`ALTER`/`CREATE` the schema (verified: `DROP TABLE` as this user fails with `ERROR 1142`) |
| Security headers | `helmet()` middleware |
| CORS | Restricted to `CORS_ORIGIN` from `.env`, not `*` |
| Request body limit | `express.json({ limit: '2mb' })` |

## 17. Setup

```bash
cd backend
cp .env.example .env   # fill in DB credentials + a real JWT_SECRET (openssl rand -hex 32)
npm install
npm run build
npm start               # or: npm run dev  (ts-node-dev, auto-restart)
```

Dev-only helper (never run against production data):
```bash
node scripts/set-dev-passwords.js
# Sets every seeded user's password to ForgeX@Demo2026 so login can be
# tested immediately against 09_seed_data.sql's placeholder password hashes.
```

Run the full RBAC test suite (server must already be running):
```bash
bash scripts/test-rbac.sh
```

## 18. Testing summary

Every endpoint in this document, and every permission boundary in §19,
was exercised live against the seeded database during development —
`scripts/test-rbac.sh` is the reusable, re-runnable form of that test
pass (33 checks across all 6 roles, all passing on a clean rebuild).
Highlights:
- `INVESTIGATOR` (`areddy`, assigned only to `CASE-2026-002`): `GET
  /api/cases` returns exactly 1 case; `GET /api/cases/1` (unassigned)
  → `403`; `GET /api/cases/2` (assigned) → `200`. Same pattern proven
  for `/api/evidence/:id`, `POST /api/evidence`, and
  `/api/cases/:id/timeline`.
- `EVIDENCE_CUSTODIAN` (`nkulkarni`): blocked (`403`) from creating
  cases, editing evidence metadata, and creating devices; succeeds
  (`200`) on `POST /api/evidence/:id/transfer` — their one real grant.
- `VIEWER` (`dmenon`): every write endpoint tested returns `403`; every
  read endpoint tested returns `200`.
- `FORENSIC_ANALYST` (`rverma`): can create examinations, blocked from
  creating cases or assigning investigators.
- `LEAD_INVESTIGATOR` (`asharma`): full CRUD on their 6 granted
  resources, blocked from `/api/users` and `/api/audit-logs`.
- `ADMIN` (`srao`): unrestricted access confirmed across every
  resource tested, including `/api/users` and `/api/audit-logs`.
- Logout: token works pre-logout (`200`), `POST /api/auth/logout`
  succeeds, the *same* token is then rejected (`401`) on every
  subsequent request, and logging out twice is handled gracefully
  (`401`, not a crash).

## 19. Roles & Permissions (Step 7)

### 19.1 The 6 roles

| Role | `roles.role_name` | Grant (from the project brief) |
|---|---|---|
| Administrator | `ADMIN` | Full system access |
| Lead Investigator | `LEAD_INVESTIGATOR` | Cases, Investigators, Persons, Devices, Evidence, Reports |
| Investigator | `INVESTIGATOR` | **Assigned** cases, Evidence, Timeline (row-level — see §19.3) |
| Forensic Analyst | `FORENSIC_ANALYST` | Evidence, Examinations, Reports |
| Evidence Custodian | `EVIDENCE_CUSTODIAN` | Evidence custody transfers (only) |
| Viewer | `VIEWER` | Read-only access |

`roles.role_name` is the literal string used in the JWT payload and
checked by `requirePermission()` — there is no separate display-name
column; a frontend may title-case these for presentation.

### 19.2 Full permission matrix

Source of truth: `backend/src/config/permissions.ts`. R = read, W = write.
Resources beyond the 6 the brief names explicitly (`evidenceHashes`,
`custody`, `custodyTransfer`, `users`, `auditLogs`, `dashboard`) are
real endpoints from Step 6; `permissions.ts`'s header comment explains
the reasoning for each one's grant in detail.

| Resource | ADMIN | LEAD_INVESTIGATOR | INVESTIGATOR | FORENSIC_ANALYST | EVIDENCE_CUSTODIAN | VIEWER |
|---|---|---|---|---|---|---|
| users | RW | | | | | |
| cases | RW | RW | R (assigned only) | | | R |
| investigators | RW | RW | | | | |
| persons | RW | RW | | | | R |
| devices | RW | RW | | | | R |
| evidence | RW | RW | RW (assigned only) | RW | R | R |
| evidenceHashes | RW | RW | R (assigned only) | RW | R | R |
| custody | R | R | R | R | R | R |
| custodyTransfer | RW | RW | RW (assigned only) | RW | RW | |
| examinations | RW | | | RW | | R |
| reports | RW | RW | | RW | | R |
| timeline | R | R | R (assigned only) | R | | R |
| auditLogs | R | | | | | |
| dashboard | R | R | | | | R |

### 19.3 Row-level scoping for INVESTIGATOR

The matrix above is role × resource × action only — it cannot express
"this user may read `cases`, but only case #7". That extra rule is a
**second, separate authorization layer**:
- `middleware/caseAccess.ts` — `requireCaseAssignment()` /
  `requireCaseAssignmentViaEvidence()` — blocks direct access
  (`GET /api/cases/:id`, `/api/evidence/:id`, `/api/cases/:caseId/timeline`,
  etc.) to a case/evidence item the caller isn't assigned to, via a
  live query against `case_investigators`.
- List endpoints (`GET /api/cases`, `GET /api/evidence`) don't 403 —
  they **filter** results at the SQL layer instead
  (`caseScopeSqlFilter()`), so an `INVESTIGATOR` simply never sees
  other investigators' cases in a list, rather than seeing them and
  being blocked from opening them.
- `POST /api/evidence` checks case assignment inline (the target
  `caseId` is in the request body, not a URL param, so the two
  middleware helpers above don't apply directly).

This only applies to `INVESTIGATOR` today (see `CASE_SCOPED_ROLES` in
`permissions.ts`) — every other role's access is fully decided by the
resource-level matrix in §19.2.

### 19.4 Password hashing, sessions, and logout

- **Hashing:** `bcryptjs`, `BCRYPT_SALT_ROUNDS` from `.env` (default
  12). `users.password_hash` is never included in any API response.
- **Session model:** stateless JWT, signed with `JWT_SECRET`, `exp`
  per `JWT_EXPIRES_IN`. Every token carries a unique `jti`.
- **Logout:** `POST /api/auth/logout` adds the caller's `jti` to an
  in-process revocation store (`utils/tokenBlocklist.ts`);
  `authenticate()` rejects any token whose `jti` is revoked, even if
  its signature and `exp` are still valid. **Documented limitation:**
  this store is in-memory and per-process — correct for this
  project's single-instance scope, but does not survive a restart or
  work across multiple server instances. A production multi-instance
  deployment would back it with Redis (`SET jti 1 EX <ttl>`), which is
  a one-file change (`tokenBlocklist.ts` only) given the current
  interface.

### 19.5 Demo credentials (seeded development users)

All 10 users from `09_seed_data.sql` share one password after running
`node scripts/set-dev-passwords.js`:

```
Password (ALL seeded users): ForgeX@Demo2026
```

**These are placeholder development/demo credentials only — never
real secrets, never used outside a local seeded database, and this
password is never committed anywhere except this documentation and
the dev-only seeding script that sets it.**

| Username | Full name | Role | Notes |
|---|---|---|---|
| `srao` | Siddharth Rao | `ADMIN` | Full access |
| `asharma` | Ananya Sharma | `LEAD_INVESTIGATOR` | Leads CASE-2026-001 |
| `kiyer` | Karthik Iyer | `LEAD_INVESTIGATOR` | |
| `mjoshi` | Meera Joshi | `LEAD_INVESTIGATOR` | Leads CASE-2026-002 |
| `areddy` | Arjun Reddy | `INVESTIGATOR` | Assigned only to CASE-2026-002 |
| `vsingh` | Vikram Singh | `INVESTIGATOR` | Assigned only to CASE-2026-004 |
| `rverma` | Rohan Verma | `FORENSIC_ANALYST` | |
| `pnair` | Priya Nair | `FORENSIC_ANALYST` | |
| `nkulkarni` | Neha Kulkarni | `EVIDENCE_CUSTODIAN` | |
| `dmenon` | Divya Menon | `VIEWER` | |

```bash
curl -X POST http://localhost:4000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"areddy","password":"ForgeX@Demo2026"}'
```
