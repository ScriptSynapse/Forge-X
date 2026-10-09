# FORGE-X User Guide

FORGE-X records how a forensic lab handles digital evidence. What you see depends on your role:

* **Administrators, custodians and auditors** see the whole lab.
* **Investigators** see only the cases they're assigned to.

Every change you make is recorded in the audit log. Records that are part of the forensic history can never be edited or deleted; mistakes are fixed by adding a linked correction.

---

## Getting an account

1. On the landing page, choose **Request access** and fill in the form.
2. An administrator approves or rejects your request. You can't log in until it's approved.
3. Log in with your username or email. If an administrator set a temporary password for you, you'll be asked to choose a new one first.

**Lockouts.** After 5 wrong passwords within 15 minutes, login for that account pauses. It resumes as the failures age out of that 15-minute window, so the wait is at most 15 minutes.

**Forgotten password.** Ask an administrator. FORGE-X doesn't send email, so there is no reset link.

---

## Investigator

| Task | Where | Notes |
|---|---|---|
| Register a case | **Cases → New case** | You become its lead investigator |
| Add investigators, change status, close a case | Case page | Lead investigator only. Closing is final and is refused while examinations are open or evidence is out of storage |
| Set or change a due date | **New case**, or case page → **Edit case** | Open cases past their due date show as overdue |
| Record a note or reference | Case page → **Notes** tab | Notes can't be edited or deleted. Use **Add a correction** to fix one; the correction is linked to the original |
| Register evidence | Case page → **Evidence** tab → **Register evidence** | The item starts **In Transit**, with a **Collected** custody entry |
| Store the evidence file | **Register evidence** → *Evidence file*, or evidence page → **Stored file** → **Store file** | Up to 100 MB. Its SHA-256 becomes the reference hash, or must match the existing one. Stored files are read-only and never replaced |
| Record the original hash | Evidence page → **Record hash** | For items without a stored file: upload a sample file (hashed, then discarded) or enter a hash with notes on its source |
| Verify the stored copy | Evidence page → **Stored file** → **Verify stored file** | Re-hashes the stored copy. A mismatch is recorded, and the trusted hash is kept |
| Download the stored copy | Evidence page → **Stored file** → **Download** | Administrators, custodians and the case's investigators. Every download is recorded as an **Exported** custody entry; the original stays where it is |
| Verify integrity | Evidence page → **Verify hash** | Every check is kept, including failures |
| Take evidence for examination | Evidence page → **Transfer custody** | Investigators can record only **Checked Out**, **Examined** and **Returned** |
| Run an examination | **Examinations → New examination** → **Start** → **Edit record** → **Submit for review** | Submitting needs tools and methods, and findings. Keep observations (what you saw) separate from findings and the conclusion (what you conclude) |
| Record artifacts | Examination → **Artifacts** tab | Files, registry or log entries, indicators. They can't be edited; record a correction if needed |
| Review an examination | Examination page → **Review this examination** → **Approve and complete** or **Return for revision** | Administrators and the case's lead investigator, but never the examiner. Approved examinations are final |
| Examination PDF | Examination → **Report** tab | Watermarked NOT REVIEWED until approved |
| Explore how records connect | **Relationship graph**, or **Relationship graph** on a case page | Select a node for details; double-click or press E to expand. Solid = recorded link, dashed = YARA match, dotted = identical SHA-256 (identical bytes, not an accusation) |
| Use the API from a script | **My account → API tokens** → **Create token**, then see **Developer API** | The token is shown once; it sees exactly what you see. Revoke it when you're done |
| Manage YARA rules | **YARA rules** → **New rule**, or a rule's page | Administrators. Rules are validated before saving; every change is a new version; choose *All cases* or *Selected cases*; enable or disable |
| Scan evidence with YARA | Evidence page → **YARA scans** → **Run YARA scan** | Stored files only; runs every enabled rule that applies to the case. A match is an indicator to examine, not a conclusion |
| Write a report | **Reports → New report** | Every save creates a new version; earlier versions are kept |
| Submit for review | Report page → **Submit for review** | The report can't be edited while under review |

## Evidence custodian

| Task | Where | Notes |
|---|---|---|
| Receive, store, check out, release, archive | Evidence page → **Transfer custody**, or **Chain of custody → Record a transfer** | Only actions valid for the item's current status are offered. Going into storage needs a storage location |
| Fix a wrong custody entry | Evidence → **Chain of custody** tab → **Record a correction to this entry** | The original entry stays; the correction is linked to it |
| Fix a wrong reference hash | Evidence → **Hash information** → **Correct hash** | Give the reason; the old hash stays, marked superseded |
| See what is out of storage | **Chain of custody** | The "Out of storage" list shows items checked out or in transit |
| Review the full handling history | **Chain of custody** log | Custody entries, exports (downloads) and integrity checks in one list. Filter by case, evidence, event type, person and dates; choose *Oldest first* for a chronological account |

If someone else moves an item while your transfer form is open, your transfer is refused instead of recording two conflicting handovers. Reload the page and try again.

## Administrator

| Task | Where |
|---|---|
| Approve or reject access requests | **Users & roles** |
| Create users, grant or remove roles, deactivate, reset a password | **Users & roles** → user |
| Approve or return a report | Report page (only for reports you didn't write) |
| Correct a person's name, email or username | **Users & roles** → person → **Edit details** |
| Delete a case registered by mistake | Case page → **Overview** → **Delete case** (only if it has no evidence, examinations or reports and isn't closed) |
| Manage storage locations | **Storage locations** |
| Review activity and login abuse | **Audit logs**, **Security view** |

You can't change your own roles or deactivate yourself; another administrator has to.

## Read-only auditor

| Task | Where |
|---|---|
| Read every case, evidence item, examination and report | Any page |
| Filter the audit trail, or open a record's trail | **Audit logs**, or **Audit trail** on any record page |
| Export the filtered trail | **Audit logs → Export CSV** (the export itself is audited) |
| Review failed logins and refused actions | **Audit logs → Security view** |

---

## Everyone

* **Search** (top bar): type part of a title or description, or a full ID such as `FX-EV-2026-00001` to open that record directly. 8 or more characters of a SHA-256 hash find the item it belongs to.
* **Analytics**: seven charts for the last 6, 12 or 24 months. **SQL behind this chart** shows the query.
* **Dashboard**: live figures for the cases you can see. Every card opens the matching filtered list, and the period buttons (7, 30, 90 days or all time) change the activity figures. **How these figures are calculated** explains each one.
* **Lists**: click a column header in the case or evidence list to sort by it; click again to reverse the order. The case list can also filter by investigator, registration dates and overdue cases.
* **Case page tabs**: Overview, Evidence, Chain of custody (every handover of the case's evidence), Investigators, Examinations, Reports, Notes and Activity history.

## What a hash result means

* **Verified** means the content was identical to the recorded hash when it was compared.
* **Integrity mismatch** means it differed. Check you used the right sample file, then tell the lead investigator.
* **Pending verification** means a reference hash is recorded but has never been checked.
* **Verification unavailable** means no reference hash has been recorded yet.

Neither result, on its own, proves who created the evidence or that its custody was complete.
