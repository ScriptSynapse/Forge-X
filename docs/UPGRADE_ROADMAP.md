# FORGE-X 2.0: Upgrade Roadmap

**Principle:** improve and extend what exists. Never rebuild or duplicate (rules 2, 3 and 5).
**Process for every phase:**

1. Inspect the code.
2. Propose the changes, the file list and the migrations.
3. Implement.
4. Test.
5. Update the documentation.
6. Report.
7. **Wait for your approval.**

Status symbols and decisions U1–U10 refer to `docs/PROJECT_AUDIT.md`.

## Overview

| Phase | Builds mostly on | New schema (migration) | Depends on | Relative size |
|---|---|---|---|---|
| 1. UI and dashboard | Design system, dashboard, layouts | None | U2, U6 (indicator only) | M |
| 2. Case management | `cases` module | 004: `case_notes`, `cases.due_date` | U4, U5 | M |
| 3. Evidence vault and integrity | `evidence`, `integrity` modules | 005: `evidence_files` | **U1**, U2 | L |
| 4. Chain of custody | `custody` module, procedures | Possibly 006: export/verification custody actions | U1 | S–M |
| 5. Examinations | `examinations`, `reports` modules | 007: review states, artifacts | **U3** | M–L |
| 6. Stabilisation | Whole test suite | None | Phases 1–5 | M |
| 7. YARA | Stored files, worker process | 008: rules, scans, matches | U1, Phase 6 | L |
| 8. Relationship graph | Existing relationships, `search` | 009: indicators (if wanted) | Phase 7 for indicators | M |
| 9. Object storage | Phase 3 storage layer | 010: storage backend column | U1 | M |
| 10. REST API | Services and `access.py` | 011: API tokens (if not session-based) | U8 | L |
| 11. Docker, CI, docs | README, tests | None | All | M |

Migrations continue the existing numbering (001–003 exist), run as root, and are never destructive. Each also updates `schema.sql` and `app_user.sql`, so a fresh install matches.

---

## Phase 1: Premium UI and dashboard

**Status: ✅ verified (all tests passed on your machine).**

**Reuse:** design tokens in `forge-x.css`, the layouts, the sidebar and topbar partials, the `ui.html` macros, the dashboard service and its JSON endpoints, and Chart.js.

**Planned changes:**

* **Design system pass:** consistent spacing scale, focus outlines, table density, and empty, loading and error states on every list. Move inline style attributes into CSS, so the CSP can drop `'unsafe-inline'` (audit #10).
* **Sidebar:** names as in your plan, with "Evidence" shown as **Evidence Vault**.
  * Keep Analytics, Search, Users & roles and Storage locations (rule 3).
  * Settings and Notifications appear only once built.
  * The notification bell is added in this phase but stays hidden until notifications exist (U6).
* **Login:** keep the current one; polish branding and states. No browser storage of secrets.
* **Dashboard:**
  * Add the missing real metrics: high-priority open cases, completed examinations, evidence awaiting examination (checked out but not yet examined), reports pending review.
  * Make every card open an exactly matching filtered list.
  * Add a date filter (7, 30 or 90 days, or all), a recent custody events panel, an examination progress panel and an integrity alerts panel, all scoped by role.
* **Column-header sorting** (server-side, allow-listed columns) on the main lists.
* **Integrity labels** per U2 (display only).
* **README drift fixes** (audit #3).

**Tests:** extend the dashboard tests so every new metric is checked against an independent SQL query; route-wide checks stay green; the accessibility audit is re-run on every page.

## Phase 2: Case management

**Status: ✅ verified.** See `docs/PROJECT_AUDIT.md` → *Phase 2 progress*.

**Reuse:** the existing list, filters, workspace tabs, procedures and permission rules.

* **List:** investigator filter, date-range filter, "last activity" column (latest audit or custody time), sortable columns.
* **Workspace:** add a **Chain of custody** tab (custody entries for all of the case's evidence) and a **Notes** tab.
* **Migration 004:**
  * `case_notes`: append-only (trigger plus INSERT-only grant), author, time, text, optional reference.
  * `cases.due_date`: nullable, with a CHECK that it isn't earlier than the creation date.
* **Archiving:** none; closure stays final (U4).

**Tests:** the full case lifecycle as an opt-in write test; note append-only probes added to `test_privileges_db.py`.

## Phase 3: Evidence vault and integrity (depends on U1)

**Status: ✅ verified.** See `docs/PROJECT_AUDIT.md` → *Phase 3 progress*.

**If U1 = "store files within limits":**

* **Storage layer `app/storage/`:**
  * an interface (`put`, `open_read`, `exists`), with a local-disk backend outside `app/static`;
  * `EVIDENCE_STORAGE_DIR` set in `.env`;
  * generated object IDs (UUID4);
  * files written once and never overwritten (an exclusive-create open);
  * SHA-256 computed while streaming the write.
* **Migration 005:** `evidence_files` (append-only) with evidence id, object id, original name (display only), size, MIME type checked against an allow-list, SHA-256, who stored it and when.
* **Upload limit** per route, configurable. Uploads stream to disk instead of being held in memory (audit #8).
* **Registration flow:** registering evidence and storing its file happens in one transaction, together with the first custody entry and an audit row. If the database step fails, the stored file is removed.
* **Verification:** re-hash from storage (read-only), stored as a normal `hash_verifications` row, so the existing trigger still decides the result. With no file stored, the status is "Verification unavailable".
* **Download:** authorised roles only, with an audited custody event (see Phase 4), served with `Content-Disposition: attachment`. No public URLs.
* **Evidence vault list:** SHA-256 column (shortened), file type, examination status, and investigator and date filters.

**If U1 = "keep metadata only":** only the list improvements and the U2 labels are done here, and Phases 7 and 9 are dropped.

## Phase 4: Chain of custody

**Status: ✅ verified.**

* Reuse everything that exists.
* Add case and investigator filters, and an event-type filter that includes verifications.
* If files are stored: an **Exported** custody action (migration 006 extends the action ENUM and `sp_transfer_evidence`'s rules, or adds a dedicated procedure).
* **Tests:** rollback on a failed transfer, a refused stale transfer, and corrections. Most already exist and will be extended.

## Phase 5: Examinations (depends on U3)

**Status: ✅ verified.**

**Migration 007:**

* Examination statuses *Under Review* and *Approved*; `reviewed_by` and `reviewed_at` with an independent-reviewer CHECK (as `chk_rep_independent`); a `conclusion` field.
* An append-only `examination_artifacts` table: description, location, optional SHA-256, recorded by, recorded at.
* `chk_exam_state` updated.

**Also in this phase:**

* **Workspace tabs:** Overview, Evidence, Methodology, Findings, Artifacts, History (audit trail), Report.
* **Examination PDF:** reuse `app/reports/pdf.py`'s layout and escaping; include the evidence hashes and custody references; audited.
* **Rule kept:** FORGE-X records analysis, it never runs tools. Automated results appear only from Phase 7 scans that actually ran.

## Phase 6: Stabilisation

**Status: ✅ verified.**

* The end-to-end sequence from your plan as one opt-in test, plus the existing security, privilege and route-wide tests.
* Run on real MySQL. Fix what fails.
* Produce `docs/CORE_STABILITY_REPORT.md` with the actual results, remaining defects and limitations.

## Phase 7: YARA (after Phase 6 approval)

**Status: ✅ verified** (YARA tests, including the real YARA-X, pass on Windows).

* `yara-python` in a **separate worker process**, never inside the web process.
* Time and memory limits; read-only access to the stored copy; no network access.
* **Migration 008:** `yara_rules` (versioned, validated before saving, enable/disable), `yara_scans` (evidence hash, rule version, scanner version, timing, status), `yara_matches`.
* A scan is marked complete only when the worker reports success.
* **Windows note:** `yara-python` has Windows wheels, but the worker isolation will be designed and tested on Windows specifically.

## Phase 8: Relationship graph

**Status: ✅ verified.**

* Built only from stored relationships: case–evidence, evidence–examination, examination–report, investigator–case, shared hashes, and indicators if Phase 7 adds them.
* A JSON endpoint scoped by `access.py`, rendered client-side with a library loaded locally.
* Controlled expansion: start from one case and expand on click.
* Analyst suggestions, if any, are drawn visibly differently from confirmed relationships.

## Phase 9: Object storage

**Status: ✅ verified.**

* A MinIO/S3 backend behind the Phase 3 storage interface, using `boto3` or `minio`.
* Metadata stays in MySQL.
* Short-lived, server-side streaming; no public or permanent URLs.
* **Migration tool:** hash before and after each copy, plus a custody/audit event per item. A rollback procedure is documented.

## Phase 10: REST API

**Status: implemented (read-only v1; migration 010), waiting for your test run and approval.** See `docs/API.md` and `docs/PROJECT_AUDIT.md` → *Phase 10 progress*.

* `/api/v1/...` on top of the **existing services**, so the rules aren't written twice.
* Session auth for the browser, plus personal API tokens (hashed in MySQL, migration 011) for scripts.
* Object-level checks through `Scope`; pagination; a consistent error envelope.
* OpenAPI generated from the implemented routes, for example with `apispec` and marshmallow schemas.
* Every documented endpoint has authorised and unauthorised tests.

## Phase 11: Deployment, CI and documentation

* **Docker Compose:** the app (Waitress), MySQL 8 (not published to the host by default), optional MinIO and the optional YARA worker. Named volumes and health checks.
* **GitHub Actions:**
  * dependency installation, `ruff` linting, offline tests;
  * a MySQL service container for the database tests;
  * `pip-audit` and `bandit`;
  * no automatic deployment.
* **Documents:** `DEPLOYMENT_GUIDE.md`, `SECURITY_REVIEW.md`, `FINAL_IMPLEMENTATION_REPORT.md`, plus updates to the README and the project report.

---

## Risks

| Risk | Mitigation |
|---|---|
| Breaking current behaviour | Every phase keeps the 184 existing tests green; migrations are additive; Git checkpoints (U9) |
| Storing evidence files adds legal and privacy weight | Synthetic data only; files outside the web root; least-privilege file access; audited downloads |
| YARA isolation on Windows | Separate process with limits; explicit tests; can be dropped without affecting Phases 1–6 |
| Time | Phases 1–6 deliver a complete 2.0 on their own; 7–11 are optional extensions (U10) |
| My sandbox can't run MySQL | Every phase ends with the commands for you to run; results recorded before approval |
