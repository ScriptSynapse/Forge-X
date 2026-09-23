import { Request, Response } from 'express';
import bcrypt from 'bcryptjs';
import jwt from 'jsonwebtoken';
import crypto from 'crypto';
import { pool, RowDataPacket } from '../config/db';
import { ApiError } from '../utils/ApiError';
import { env } from '../config/env';
import { LoginInput } from '../validators/auth.validators';
import { revokeToken } from '../utils/tokenBlocklist';

interface UserRow extends RowDataPacket {
  user_id: number;
  username: string;
  email: string;
  password_hash: string;
  full_name: string;
  role_id: number;
  role_name: string;
  department_id: number;
  is_active: number;
}

/**
 * POST /api/auth/login
 * Authenticates against users.password_hash (bcrypt) — the same
 * `users` table built in 02_tables.sql / 09_seed_data.sql, not a
 * separate auth store. Issues a signed JWT carrying the identity
 * fields every other endpoint needs (role for requirePermission(),
 * user_id for @forgex_actor_id / audit attribution) plus a unique
 * `jti` so this specific token can later be individually revoked by
 * POST /api/auth/logout (see utils/tokenBlocklist.ts).
 */
export async function login(req: Request, res: Response): Promise<void> {
  const { username, password } = req.body as LoginInput;

  const [rows] = await pool.query<UserRow[]>(
    `SELECT u.user_id, u.username, u.email, u.password_hash, u.full_name,
            u.role_id, r.role_name, u.department_id, u.is_active
       FROM users u
       JOIN roles r ON u.role_id = r.role_id
      WHERE u.username = ? OR u.email = ?
      LIMIT 1`,
    [username, username]
  );

  const user = rows[0];
  if (!user) {
    throw ApiError.unauthorized('Invalid username or password.');
  }
  if (user.is_active !== 1) {
    throw ApiError.forbidden('This account has been deactivated. Contact an administrator.');
  }

  const passwordMatches = await bcrypt.compare(password, user.password_hash);
  if (!passwordMatches) {
    throw ApiError.unauthorized('Invalid username or password.');
  }

  const payload = {
    userId: user.user_id,
    username: user.username,
    roleId: user.role_id,
    roleName: user.role_name,
    departmentId: user.department_id,
    fullName: user.full_name,
    jti: crypto.randomUUID(),
  };

  const token = jwt.sign(payload, env.jwt.secret, { expiresIn: env.jwt.expiresIn } as jwt.SignOptions);

  await pool.query('UPDATE users SET last_login_at = NOW() WHERE user_id = ?', [user.user_id]);

  res.status(200).json({
    data: {
      token,
      user: { ...payload, jti: undefined },
      expiresIn: env.jwt.expiresIn,
    },
  });
}

/**
 * POST /api/auth/logout
 * Auth required (you can only log out a token you're presenting).
 * Revokes THIS token's jti immediately — see utils/tokenBlocklist.ts
 * for what "revoked" means and its documented single-process caveat.
 * Idempotent: logging out an already-logged-out token just succeeds
 * again rather than erroring.
 */
export async function logout(req: Request, res: Response): Promise<void> {
  const authUser = req.user!;
  revokeToken(authUser.jti, authUser.exp);
  res.status(200).json({ data: { message: 'Logged out successfully. This token is no longer valid.' } });
}

/**
 * GET /api/auth/me
 * Returns the identity encoded in the caller's own token, re-checked
 * live against the users table (so a deactivated account is reflected
 * immediately even with an unexpired token still in hand).
 */
export async function me(req: Request, res: Response): Promise<void> {
  const authUser = req.user!;

  const [rows] = await pool.query<UserRow[]>(
    `SELECT u.user_id, u.username, u.email, u.password_hash, u.full_name,
            u.role_id, r.role_name, u.department_id, u.is_active
       FROM users u
       JOIN roles r ON u.role_id = r.role_id
      WHERE u.user_id = ?`,
    [authUser.userId]
  );

  const user = rows[0];
  if (!user || user.is_active !== 1) {
    throw ApiError.unauthorized('Account no longer active.');
  }

  res.status(200).json({
    data: {
      userId: user.user_id,
      username: user.username,
      email: user.email,
      fullName: user.full_name,
      roleId: user.role_id,
      roleName: user.role_name,
      departmentId: user.department_id,
    },
  });
}
