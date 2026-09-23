import { NextFunction, Request, Response } from 'express';
import { ApiError } from '../utils/ApiError';
import { Action, hasPermission, Resource, Role } from '../config/permissions';

/**
 * Resource + action based authorization (Step 7). Replaces the flat
 * per-route role allow-lists from Step 6 with a single, centrally
 * defined permission matrix (config/permissions.ts), so "who can do
 * what" lives in exactly one auditable place instead of being
 * scattered as string arrays across every routes/*.ts file.
 *
 * Usage: router.post('/', authenticate, requirePermission('cases', 'write'), validate(...), handler)
 * Must run AFTER authenticate() (needs req.user).
 *
 * This is enforced entirely server-side -- the frontend (not built in
 * this phase) is expected to hide controls a role can't use for a
 * better UX, but every one of those actions is independently and
 * unconditionally rejected here even if called directly (curl,
 * Postman, a modified client), which is what "do not rely only on
 * frontend route hiding" requires.
 */
export function requirePermission(resource: Resource, action: Action) {
  return (req: Request, _res: Response, next: NextFunction): void => {
    if (!req.user) {
      throw ApiError.unauthorized();
    }
    const role = req.user.roleName as Role;
    if (!hasPermission(role, resource, action)) {
      throw ApiError.forbidden(
        `Role ${role} does not have ${action} access to ${resource}.`
      );
    }
    next();
  };
}
