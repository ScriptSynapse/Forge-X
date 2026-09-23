import { Request, Response } from 'express';
import { pool, withActorConnection, RowDataPacket, ResultSetHeader } from '../config/db';
import { ApiError } from '../utils/ApiError';
import { parsePagination, paginatedResponse } from '../utils/pagination';
import { UpdateUserInput } from '../validators/users.validators';

const SAFE_USER_COLUMNS = `
  u.user_id, u.badge_number, u.username, u.email, u.full_name, u.phone_number,
  u.role_id, r.role_name, u.department_id, d.department_name, u.is_active,
  u.last_login_at, u.created_at
`;

/** GET /api/users */
export async function listUsers(req: Request, res: Response): Promise<void> {
  const pagination = parsePagination(req.query as Record<string, unknown>);
  const { roleId, departmentId, isActive } = req.query as { roleId?: string; departmentId?: string; isActive?: string };

  const where: string[] = [];
  const params: unknown[] = [];
  if (roleId) { where.push('u.role_id = ?'); params.push(Number(roleId)); }
  if (departmentId) { where.push('u.department_id = ?'); params.push(Number(departmentId)); }
  if (isActive !== undefined) { where.push('u.is_active = ?'); params.push(Number(isActive)); }
  const whereClause = where.length ? `WHERE ${where.join(' AND ')}` : '';

  const [countRows] = await pool.query<RowDataPacket[]>(
    `SELECT COUNT(*) AS total FROM users u ${whereClause}`, params
  );
  const [rows] = await pool.query<RowDataPacket[]>(
    `SELECT ${SAFE_USER_COLUMNS} FROM users u
       JOIN roles r ON u.role_id = r.role_id
       JOIN departments d ON u.department_id = d.department_id
       ${whereClause}
      ORDER BY u.user_id LIMIT ? OFFSET ?`,
    [...params, pagination.pageSize, pagination.offset]
  );

  res.status(200).json(paginatedResponse(rows, countRows[0]?.total ?? 0, pagination));
}

/** GET /api/users/:id */
export async function getUser(req: Request, res: Response): Promise<void> {
  const userId = Number(req.params.id);
  const [rows] = await pool.query<RowDataPacket[]>(
    `SELECT ${SAFE_USER_COLUMNS} FROM users u
       JOIN roles r ON u.role_id = r.role_id
       JOIN departments d ON u.department_id = d.department_id
      WHERE u.user_id = ?`,
    [userId]
  );
  if (!rows[0]) throw ApiError.notFound(`User ${userId} not found.`);
  res.status(200).json({ data: rows[0] });
}

/** PUT /api/users/:id — Administrator only (see routes). Direct UPDATE;
 * `users` has no dedicated change-audit trigger, so this endpoint
 * writes its own audit_logs row, same pattern as updateCase. */
export async function updateUser(req: Request, res: Response): Promise<void> {
  const userId = Number(req.params.id);
  const actorUserId = req.user!.userId;
  const body = req.body as UpdateUserInput;

  await withActorConnection(actorUserId, async (conn) => {
    const [existingRows] = await conn.query<RowDataPacket[]>(
      'SELECT full_name, role_id, department_id, phone_number, is_active FROM users WHERE user_id = ? FOR UPDATE',
      [userId]
    );
    const existing = existingRows[0];
    if (!existing) throw ApiError.notFound(`User ${userId} not found.`);

    const fields: string[] = [];
    const values: unknown[] = [];
    if (body.fullName !== undefined) { fields.push('full_name = ?'); values.push(body.fullName); }
    if (body.roleId !== undefined) { fields.push('role_id = ?'); values.push(body.roleId); }
    if (body.departmentId !== undefined) { fields.push('department_id = ?'); values.push(body.departmentId); }
    if (body.phoneNumber !== undefined) { fields.push('phone_number = ?'); values.push(body.phoneNumber); }
    if (body.isActive !== undefined) { fields.push('is_active = ?'); values.push(body.isActive ? 1 : 0); }

    const [result] = await conn.query<ResultSetHeader>(
      `UPDATE users SET ${fields.join(', ')} WHERE user_id = ?`, [...values, userId]
    );
    if (result.affectedRows === 0) throw ApiError.notFound(`User ${userId} not found.`);

    await conn.query(
      `INSERT INTO audit_logs (user_id, table_name, record_id, action_type, old_values, new_values)
       VALUES (?, 'users', ?, 'UPDATE', ?, ?)`,
      [actorUserId, userId, JSON.stringify(existing), JSON.stringify(body)]
    );
  });

  const [rows] = await pool.query<RowDataPacket[]>(
    `SELECT ${SAFE_USER_COLUMNS} FROM users u
       JOIN roles r ON u.role_id = r.role_id
       JOIN departments d ON u.department_id = d.department_id
      WHERE u.user_id = ?`,
    [userId]
  );
  res.status(200).json({ data: rows[0] });
}
