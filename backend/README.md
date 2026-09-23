# FORGE-X — Backend

Node.js + Express + TypeScript API server for FORGE-X. Talks to the
**same `forge_x` MySQL database** built in `/database` (Steps 1-5) via
`mysql2` — no ORM, no second database. Full endpoint reference:
[`/docs/09_API_Documentation.md`](../docs/09_API_Documentation.md).

## Quick start

```bash
# 1. Database must already be built and seeded (see /database/README.md).
#    Then create a least-privilege app user (recommended over root):
mysql -u root --default-character-set=utf8mb4 -e "
  CREATE USER 'forgex_app'@'localhost' IDENTIFIED BY 'change_me';
  GRANT SELECT, INSERT, UPDATE, DELETE ON forge_x.* TO 'forgex_app'@'localhost';
  GRANT EXECUTE ON forge_x.* TO 'forgex_app'@'localhost';
"

# 2. Configure
cp .env.example .env
# edit .env: DB_PASSWORD to match above, JWT_SECRET to `openssl rand -hex 32`

# 3. Install, build, run
npm install
npm run build
npm start
# or for development with auto-restart:
npm run dev
```

Server starts on `http://localhost:4000` (configurable via `PORT`).
`GET /health` needs no auth and confirms the DB connection.

## Test login (dev only)

The seeded users (`09_seed_data.sql`) ship with a non-functional
placeholder `password_hash`. To log in locally:

```bash
node scripts/set-dev-passwords.js
```

This sets **every** seeded user's password to `ForgeX@Demo2026` across
all 6 roles:

| Username | Role |
|---|---|
| `srao` | `ADMIN` |
| `asharma`, `kiyer`, `mjoshi` | `LEAD_INVESTIGATOR` |
| `areddy`, `vsingh` | `INVESTIGATOR` (assigned to specific cases only — see `docs/09_API_Documentation.md` §19.5) |
| `rverma`, `pnair` | `FORENSIC_ANALYST` |
| `nkulkarni` | `EVIDENCE_CUSTODIAN` |
| `dmenon` | `VIEWER` |

**Never** run this script against anything but a local/demo database.

```bash
curl -X POST http://localhost:4000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"asharma","password":"ForgeX@Demo2026"}'
```

Run the full RBAC test suite (33 checks across all 6 roles, including
row-level scoping and logout) against a running server:
```bash
bash scripts/test-rbac.sh
```

## Project layout

```
src/
  config/       env.ts (validated env vars), db.ts (mysql2 pool + the
                @forgex_actor_id session-variable helper)
  middleware/   authenticate, authorize, validate (Zod), errorHandler
  routes/       one file per resource, assembled in routes/index.ts
  controllers/  route handlers — parameterized SQL, or CALL into a
                stored procedure from 07_procedures.sql where one exists
  validators/   Zod schemas, one file per resource
  utils/        ApiError, asyncHandler, mysqlErrorMap, pagination
  types/        Express Request augmentation (req.user)
scripts/
  set-dev-passwords.js   (dev-only, see above)
```

## Design principles this codebase follows

- **Stored procedures over duplicated logic.** `POST /api/evidence/:id/transfer`
  calls `sp_transfer_evidence()` — it does not re-implement locking,
  validation, or custody-record writing in JavaScript. Same for case
  creation, evidence registration, investigator assignment, hash
  verification, and case closure.
- **Triggers over manual audit inserts.** Where a trigger from
  `08_triggers.sql` already writes an `audit_logs`/`chain_of_custody`
  row automatically (e.g. `trg_evidence_important_changes_audit`), the
  matching controller does **not** also insert one — that would
  silently duplicate the audit trail. See the comments in
  `controllers/evidence.controller.ts` and `07_procedures.sql`'s file
  header for exactly which endpoint relies on which trigger.
- **Parameterized SQL everywhere.** No string concatenation into a
  query, anywhere — this is the SQL-injection defense, alongside Zod's
  shape/type validation on every request.
- **Two-layer authorization.** `requirePermission(resource, action)`
  (role × resource × action, `config/permissions.ts`) decides *whether
  a role can touch a resource at all*; `middleware/caseAccess.ts`
  separately decides, for `INVESTIGATOR` only, *which specific rows*
  ("assigned cases") — composed, not conflated into one check. Both
  are enforced server-side; there is no client-trusted authorization
  anywhere in this codebase.
- **Least privilege.** The backend's own DB user cannot alter the
  schema, only read/write data and call routines.
