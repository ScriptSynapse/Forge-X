# FORGE-X Viva Guide

Likely questions, with short answers and where to show the proof. Each answer points to real files, so you can open the evidence during the viva.

**Before the viva:**
* Install the demo data (`install_demo.sql`), so the sample queries return their documented results.
* Open MySQL Workbench or a `mysql` prompt, and FORGE-X itself.

---

## Design

**1. Why a relational database, not files or NoSQL?**
The core value of FORGE-X is integrity across related records: a custody entry must refer to a real item, user and location, and a transfer must change several rows together or not at all. Foreign keys, CHECK constraints, triggers and ACID transactions give that directly. Show `database/schema.sql`.

**2. Walk us through the ER diagram.**
* **The centre:** evidence. A case has many items (1:N), and an item has many custody entries and hashes (1:N).
* **Many-to-many links:** users and roles; cases and investigators; examinations and evidence; reports and examinations.
* **Recursive relationships:** a custody entry correcting an earlier one; a hash superseding an earlier one.

See the report's section 5, or the Mermaid ER diagram from Phase 3.

**3. Show normalization from the spreadsheet to BCNF.**
* **UNF:** one row per item, with multi-valued cells.
* **1NF:** split the repeating groups.
* **2NF:** remove the partial dependency `evidence_code → case_ref, …` from the custody relation keyed by `(evidence_code, custody_seq)`.
* **3NF:** remove the transitive chains (case facts, types, users, locations).
* **BCNF:** every determinant is a candidate key.

The 3NF-but-not-BCNF example is `Holding(evidence_id, custodian_id, location_id)` with `custodian_id → location_id`, which FORGE-X avoids.

**4. Is there any redundancy?**
Two documented cases:
* `evidence.current_*` mirrors the latest custody entry. It is kept so a transfer has one row to lock, and so lists are fast. It changes only inside the transfer transaction, and `verify_demo.sql` checks it matches the history.
* `hash_verifications.result` is set by a trigger from immutable hashes, so it can never be wrong or go stale.

**5. Why surrogate keys, if business codes are unique?**
Codes are formatted, human-facing values. Integer keys are smaller in every foreign key and never need to change. The codes remain UNIQUE candidate keys.

**6. Why are some categories ENUMs and others lookup tables?**
* **Lookup tables:** categories an administrator may extend, such as case and evidence types and storage locations.
* **ENUMs:** fixed workflow states that code depends on, such as statuses and custody actions.

## Integrity and constraints

**7. How do you stop anyone editing the chain of custody?**
Two independent layers:
* BEFORE UPDATE and BEFORE DELETE triggers raise an error.
* The `forge_x_app` account has no UPDATE or DELETE privilege on that table.

Demonstrate it: `UPDATE chain_of_custody SET reason = 'x' WHERE custody_id = 1;` fails. `tests/test_privileges_db.py` checks all 8 history tables.

**8. Then how is a mistake fixed?**
By adding a linked correction:
* **Custody:** a new entry with `corrects_custody_id`.
* **Hashes:** a new hash with `supersedes_hash_id` and a reason.

The original stays, so the history shows both the mistake and the fix. Show entry #55 correcting #54 on `FX-EV-2026-00051`.

**9. How do you enforce "only one lead investigator per case" without partial indexes?**
A stored generated column `lead_case_id = IF(is_lead, case_id, NULL)` with a UNIQUE index. UNIQUE allows many NULLs, so only lead rows compete. The same technique allows only one pending request per email, and one original hash per item.

**10. Why a trigger for "same case" links, rather than a composite foreign key?**
Adding `case_id` to `examination_evidence` would make it depend on `evidence_id` alone, which is part of the key. That breaks 2NF, so a trigger keeps the table normalized.

**11. Who decides whether a hash verification passed?**
The database. `trg_hv_set_result` compares the computed hash with the reference hash before the row is inserted; the application never supplies the result.

**12. Can a case be deleted?**
Only one that has no forensic history: no evidence, examinations or reports, and not closed. That is, a case registered by mistake or twice. Two layers enforce this:
* the service checks first and explains why if deletion isn't allowed;
* RESTRICT foreign keys from `evidence`, `examinations` and `forensic_reports` refuse the delete in MySQL anyway.

The application account has DELETE on `cases`, but still none on any history table. Every deletion is audited with the case's reference, title and the reason.

## Transactions and concurrency

**13. What happens if two custodians transfer the same item at once?**
`sp_transfer_evidence` locks the evidence row with `SELECT … FOR UPDATE`:
1. The second transaction waits.
2. It then sees the custodian is no longer the one its form showed.
3. It rolls back, and the user is told someone else moved the item.

**14. How are case and evidence numbers gap-free?**
`sp_next_reference` increments a per-year counter row inside the same transaction that creates the record:
* A rollback undoes the increment, so no number is skipped.
* The row lock serialises concurrent registrations, so no number is used twice.

AUTO_INCREMENT can't do this: it leaves gaps on rollback and doesn't restart each year. Test R3 in `verify.sql` proves a failed registration uses no number.

**15. Which isolation level, and why?**
InnoDB's default, REPEATABLE READ. Decisions that depend on current data use locking reads (`FOR UPDATE`), which see the latest committed row and hold it until commit. Rows are always locked in the same order (counter, parent, child) to avoid deadlocks.

**16. Did least privilege ever cause a problem?**
Yes, and it's a good lesson. Since MySQL 8.0.22, `SELECT ... FOR UPDATE` needs UPDATE or DELETE privilege on every table it reads. The hash code locked `evidence_hashes`, where the app account deliberately has neither, so recording a hash failed with error 1142.

The fix was to lock the parent `evidence` row instead. All hash changes for one item lock that row first, so they still take turns. A test now checks every locking read in the code against the grants in `app_user.sql`, and it found a second case (a lock that included `roles`) before it reached users.

## SQL features

**17. Show a window function.**
`v_evidence_integrity` uses `ROW_NUMBER() OVER (PARTITION BY hash_id ORDER BY verified_at DESC)` to find each hash's latest check. The analytics *Investigator workload* chart uses `RANK() OVER`.

**18. Show a recursive CTE.**
*Lab activity per month* in Analytics: `WITH RECURSIVE months` generates every month, so months with no activity still appear. Open **SQL behind this chart**.

**19. Show a view and say why it exists.**
`v_activity_feed` is `audit_logs` UNION ALL `login_attempts`. It gives one timeline while each event is stored once.

**20. Which indexes, and how did you choose them?**
Each of the 15 extra indexes serves a named query. For example:
* `idx_coc_evidence_time` returns a custody timeline in order.
* `idx_login_ident_time` makes the rate-limit count a range scan.
* `idx_hashes_value` finds an item from a hash prefix.

Use `EXPLAIN` on a sample query to show the index being used.

## Security

**21. How do you prevent SQL injection?**
* Every value is a `%s` parameter.
* Sort orders and filters come from fixed lists.
* `tests/test_security.py` scans every f-string that builds SQL, and fails if an unreviewed value is ever interpolated.

**22. How are passwords stored?**
As Werkzeug scrypt hashes; never in plain text or in any file. Seed accounts have an unusable placeholder hash until `flask set-password` is run.

**23. What stops an investigator seeing other cases?**
Every query on case data adds a scope filter: `c.case_id IN (SELECT case_id FROM case_investigators WHERE user_id = %s)`. Records outside that scope return 404, so their existence isn't even revealed.

**24. Why does the application use its own MySQL account?**
Least privilege. Even if the application had a bug, the account can't drop tables, alter the schema, manage users, or rewrite history.

## Honest limitations

**25. Does a matching hash prove the evidence is authentic?**
No. It shows the content was identical when compared. Authenticity also depends on how the item was acquired and on an unbroken custody record.

**26. Could a database administrator still tamper with records?**
Yes. A MySQL administrator can drop triggers and edit rows. FORGE-X protects against ordinary use and application bugs. Hash-chaining the audit log is listed as future work, to make such tampering detectable.

**27. What would you change for production?**
* Store time in UTC.
* Add multi-factor authentication and email-based password reset.
* Use a managed MySQL with backups and replication.
* Sign approved reports digitally.
* Load-test the application.
