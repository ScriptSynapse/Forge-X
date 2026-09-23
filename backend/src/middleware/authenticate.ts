import { NextFunction, Request, Response } from 'express';
import jwt from 'jsonwebtoken';
import { env } from '../config/env';
import { ApiError } from '../utils/ApiError';
import { AuthUser } from '../types/express';
import { isRevoked } from '../utils/tokenBlocklist';

interface ForgeXJwtPayload {
  userId: number;
  username: string;
  roleId: number;
  roleName: string;
  departmentId: number;
  fullName: string;
  jti: string;
  exp: number;
}

/**
 * Verifies the `Authorization: Bearer <token>` header, populated by
 * POST /api/auth/login. On success, attaches req.user for downstream
 * handlers and for withActorConnection() to attribute writes to the
 * real acting user (see config/db.ts / the @forgex_actor_id
 * convention from 08_triggers.sql). Every route except
 * /api/auth/login and GET /health requires this middleware.
 *
 * Also checks the token's jti against the logout revocation store
 * (utils/tokenBlocklist.ts) -- a token can be cryptographically valid
 * and unexpired and STILL be rejected here if its holder already
 * called POST /api/auth/logout with it.
 */
export function authenticate(req: Request, _res: Response, next: NextFunction): void {
  const header = req.headers.authorization;
  if (!header || !header.startsWith('Bearer ')) {
    throw ApiError.unauthorized('Missing or malformed Authorization header. Expected: Bearer <token>.');
  }

  const token = header.slice('Bearer '.length).trim();

  let payload: ForgeXJwtPayload;
  try {
    payload = jwt.verify(token, env.jwt.secret) as ForgeXJwtPayload;
  } catch {
    throw ApiError.unauthorized('Invalid or expired token. Please log in again.');
  }

  if (isRevoked(payload.jti)) {
    throw ApiError.unauthorized('This session has been logged out. Please log in again.');
  }

  const user: AuthUser = {
    userId: payload.userId,
    username: payload.username,
    roleId: payload.roleId,
    roleName: payload.roleName,
    departmentId: payload.departmentId,
    fullName: payload.fullName,
    jti: payload.jti,
    exp: payload.exp,
  };
  req.user = user;
  next();
}
