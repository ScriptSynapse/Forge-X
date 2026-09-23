import { NextFunction, Request, Response } from 'express';
import { pool, RowDataPacket } from '../config/db';
import { ApiError } from '../utils/ApiError';
import { CASE_SCOPED_ROLES, Role } from '../config/permissions';
import { asyncHandler } from '../utils/asyncHandler';

/**
 * Row-level authorization for INVESTIGATOR's "assigned cases" grant.
 * The permission matrix (config/permissions.ts) only knows role x
 * resource x action — it cannot express "this INVESTIGATOR may read
 * `cases`, but only the ONE case with id=7, not case id=8". That is a
 * data-dependent (row-level) rule, so it lives here as a second,
 * separate authorization layer that runs after requirePermission()
 * has already confirmed the role is allowed to touch the resource at
 * all.
 *
 * For any role NOT in CASE_SCOPED_ROLES (i.e. everyone except
 * INVESTIGATOR today), this middleware is a no-op — their access was
 * already fully decided by the resource-level matrix. This function is
 * deliberately NOT an "ADMIN/LEAD_INVESTIGATOR bypass hack" — it
 * simply has nothing to check for roles whose grant was never
 * case-scoped in the first place.
 *
 * Two variants are exported because the case id is reachable two
 * different ways depending on the route:
 *   - requireCaseAssignment: the case id IS the route param (mounted
 *     at /cases/:id or /cases/:caseId/...)
 *   - requireCaseAssignmentViaEvidence: the route param is an
 *     evidence id; the case id must be looked up from evidence.case_id
 *     first (mounted at /evidence/:id or /evidence/:evidenceId/...)
 */

async function isAssignedToCase(userId: number, caseId: number): Promise<boolean> {
  const [rows] = await pool.query<RowDataPacket[]>(
    `SELECT 1 FROM case_investigators
      WHERE case_id = ? AND user_id = ? AND unassigned_at IS NULL
      LIMIT 1`,
    [caseId, userId]
  );
  return rows.length > 0;
}

export function requireCaseAssignment(caseIdParamName: 'id' | 'caseId' = 'id') {
  return asyncHandler(async (req: Request, _res: Response, next: NextFunction): Promise<void> => {
    const role = req.user!.roleName as Role;
    if (!CASE_SCOPED_ROLES.has(role)) {
      next();
      return;
    }

    const caseId = Number(req.params[caseIdParamName]);
    const assigned = await isAssignedToCase(req.user!.userId, caseId);
    if (!assigned) {
      throw ApiError.forbidden(
        `As ${role}, you can only access cases you are assigned to. You are not assigned to case ${caseId}.`
      );
    }
    next();
  });
}

export function requireCaseAssignmentViaEvidence(evidenceIdParamName: 'id' | 'evidenceId' = 'id') {
  return asyncHandler(async (req: Request, _res: Response, next: NextFunction): Promise<void> => {
    const role = req.user!.roleName as Role;
    if (!CASE_SCOPED_ROLES.has(role)) {
      next();
      return;
    }

    const evidenceId = Number(req.params[evidenceIdParamName]);
    const [rows] = await pool.query<RowDataPacket[]>(
      'SELECT case_id FROM evidence WHERE evidence_id = ?',
      [evidenceId]
    );
    if (!rows[0]) {
      throw ApiError.notFound(`Evidence ${evidenceId} not found.`);
    }

    const assigned = await isAssignedToCase(req.user!.userId, rows[0].case_id);
    if (!assigned) {
      throw ApiError.forbidden(
        `As ${role}, you can only access evidence belonging to cases you are assigned to.`
      );
    }
    next();
  });
}

/** For list endpoints (GET /api/cases, GET /api/evidence): rather than
 * a 403 (which doesn't make sense for a list), CASE_SCOPED_ROLES get
 * their results silently filtered down to assigned cases only, at the
 * SQL layer -- not filtered out of a full result set in JavaScript
 * after the fact, which would still have pulled every other
 * investigator's case data out of the database. Returns a SQL
 * fragment + params to AND into the caller's WHERE clause, or null if
 * no extra restriction applies to this role. */
export function caseScopeSqlFilter(
  role: Role,
  userId: number,
  caseIdColumn: string
): { clause: string; params: unknown[] } | null {
  if (!CASE_SCOPED_ROLES.has(role)) {
    return null;
  }
  return {
    clause: `${caseIdColumn} IN (SELECT case_id FROM case_investigators WHERE user_id = ? AND unassigned_at IS NULL)`,
    params: [userId],
  };
}
