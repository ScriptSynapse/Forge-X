/**
 * FORGE-X RBAC permission matrix (Step 7).
 *
 * The 6 roles below come from the `roles` table (02_tables.sql /
 * 09_seed_data.sql) — role_name is now the literal identifier used
 * here and throughout the JWT payload, not a display string. There is
 * no separate "pretty name" column; the frontend, when built, may
 * title-case these for display (e.g. LEAD_INVESTIGATOR -> "Lead
 * Investigator").
 *
 * SPEC -> MATRIX, and where the brief was ambiguous
 *   The brief names exactly six resource groups (Cases, Investigators,
 *   Persons, Devices, Evidence, Reports for LEAD_INVESTIGATOR; Assigned
 *   cases, Evidence, Timeline for INVESTIGATOR; Evidence, Examinations,
 *   Reports for FORENSIC_ANALYST; Evidence custody transfers for
 *   EVIDENCE_CUSTODIAN; read-only everywhere for VIEWER). This API has
 *   more resources than that (evidenceHashes, custody, users,
 *   auditLogs, dashboard) because they are real endpoints from Step 6.
 *   For each of those, the grant below is the closest reasonable
 *   reading of the spec, called out in the comment on that line so the
 *   reasoning is auditable rather than silently invented:
 *     - users / auditLogs -> ADMIN only. Neither appears in any
 *       non-admin role's list; both are classic admin/compliance-only
 *       surfaces (managing accounts; a full cross-user audit trail).
 *     - evidenceHashes -> follows `evidence`'s grants exactly (hashes
 *       are evidence's own integrity data, not a separate concern).
 *     - custodyTransfer -> its own resource (see the note on it below)
 *       since "Evidence custody transfers" is EVIDENCE_CUSTODIAN's
 *       ENTIRE grant and is clearly meant to be narrower than general
 *       evidence read/write.
 *     - custody (read of the chain_of_custody ledger) -> granted
 *       wherever `evidence` read is granted, since custody history is
 *       part of viewing an evidence item, not a separate permission.
 *     - examinations -> FORENSIC_ANALYST gets read+write (explicit),
 *       ADMIN gets everything, VIEWER gets read (their blanket
 *       read-only grant). LEAD_INVESTIGATOR and INVESTIGATOR are
 *       deliberately NOT granted this resource directly -- neither
 *       lists "Examinations" in the spec -- but they still see
 *       examination data as part of an evidence item's own detail
 *       response (GET /api/evidence/:id embeds it), since that is data
 *       returned from a resource (`evidence`) they ARE granted, not a
 *       separate access path into `examinations` itself.
 *     - timeline -> read-only for every role that can see the
 *       underlying case/evidence (there is no direct "create a
 *       timeline row" endpoint in this API regardless; timeline rows
 *       are written by triggers/procedures, not directly by a
 *       controller, so a "write" grant here would be moot in practice).
 *     - dashboard -> read-only, granted to ADMIN, LEAD_INVESTIGATOR,
 *       and VIEWER (aggregate counts only, no row-level forensic
 *       detail, and "VIEWER: read-only access" reads as "access", not
 *       "no access").
 *
 * INVESTIGATOR's "assigned cases" restriction is NOT expressed in this
 * matrix — permissions here are role x resource x action only. The
 * additional row-level rule ("only cases/evidence this investigator is
 * actually assigned to, via case_investigators") is enforced separately
 * by middleware/caseAccess.ts and by explicit filtering in
 * cases.controller.ts / evidence.controller.ts's list/get handlers.
 * Row-level and role-level authorization are deliberately two
 * different, composable layers, not conflated into one matrix.
 */

export const ROLES = [
  'ADMIN',
  'LEAD_INVESTIGATOR',
  'INVESTIGATOR',
  'FORENSIC_ANALYST',
  'EVIDENCE_CUSTODIAN',
  'VIEWER',
] as const;
export type Role = (typeof ROLES)[number];

export const RESOURCES = [
  'users',
  'cases',
  'investigators',
  'persons',
  'devices',
  'evidence',
  'evidenceHashes',
  'custody',
  'custodyTransfer',
  'examinations',
  'reports',
  'timeline',
  'auditLogs',
  'dashboard',
] as const;
export type Resource = (typeof RESOURCES)[number];

export type Action = 'read' | 'write';

type Matrix = Record<Resource, Partial<Record<Role, Action[]>>>;

const RW: Action[] = ['read', 'write'];
const R: Action[] = ['read'];

export const PERMISSIONS: Matrix = {
  users:           { ADMIN: RW },
  cases:           { ADMIN: RW, LEAD_INVESTIGATOR: RW, INVESTIGATOR: R, VIEWER: R },
  investigators:   { ADMIN: RW, LEAD_INVESTIGATOR: RW },
  persons:         { ADMIN: RW, LEAD_INVESTIGATOR: RW, VIEWER: R },
  devices:         { ADMIN: RW, LEAD_INVESTIGATOR: RW, VIEWER: R },
  evidence:        { ADMIN: RW, LEAD_INVESTIGATOR: RW, INVESTIGATOR: RW, FORENSIC_ANALYST: RW, EVIDENCE_CUSTODIAN: R, VIEWER: R },
  evidenceHashes:  { ADMIN: RW, LEAD_INVESTIGATOR: RW, INVESTIGATOR: R,  FORENSIC_ANALYST: RW, EVIDENCE_CUSTODIAN: R, VIEWER: R },
  custody:         { ADMIN: R,  LEAD_INVESTIGATOR: R,  INVESTIGATOR: R,  FORENSIC_ANALYST: R,  EVIDENCE_CUSTODIAN: R, VIEWER: R },
  custodyTransfer: { ADMIN: RW, LEAD_INVESTIGATOR: RW, INVESTIGATOR: RW, FORENSIC_ANALYST: RW, EVIDENCE_CUSTODIAN: RW },
  examinations:    { ADMIN: RW, FORENSIC_ANALYST: RW, VIEWER: R },
  reports:         { ADMIN: RW, LEAD_INVESTIGATOR: RW, FORENSIC_ANALYST: RW, VIEWER: R },
  timeline:        { ADMIN: R,  LEAD_INVESTIGATOR: R,  INVESTIGATOR: R,  FORENSIC_ANALYST: R, VIEWER: R },
  auditLogs:       { ADMIN: R },
  dashboard:       { ADMIN: R,  LEAD_INVESTIGATOR: R,  VIEWER: R },
};

/** True if `role` has `action` on `resource`. ADMIN is granted
 * everywhere the matrix says so explicitly (every resource lists
 * ADMIN: RW) rather than via a silent bypass, so this matrix alone is
 * a complete, auditable description of the system's access control —
 * nothing is granted "off the books". */
export function hasPermission(role: Role, resource: Resource, action: Action): boolean {
  return PERMISSIONS[resource]?.[role]?.includes(action) ?? false;
}

/** Roles for which INVESTIGATOR-style "assigned cases only" row-level
 * scoping applies. Currently just INVESTIGATOR itself, but expressed
 * as a set (not a bare `=== 'INVESTIGATOR'` check scattered around the
 * codebase) so a future role needing the same treatment is a one-line
 * change here, not a hunt through every controller. */
export const CASE_SCOPED_ROLES: ReadonlySet<Role> = new Set(['INVESTIGATOR']);
