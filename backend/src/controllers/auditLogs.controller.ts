import { Request, Response } from 'express';
import { pool, RowDataPacket } from '../config/db';
import { parsePagination, paginatedResponse } from '../utils/pagination';

/** GET /api/audit-logs — read-only, uses idx_audit_logs_entity
 * (table_name, record_id) from 04_indexes.sql for the common
 * "full history of this one row" lookup pattern. */
export async function listAuditLogs(req: Request, res: Response): Promise<void> {
  const pagination = parsePagination(req.query as Record<string, unknown>);
  const { tableName, recordId, userId, actionType, fromDate, toDate } = req.query as {
    tableName?: string; recordId?: string; userId?: string; actionType?: string; fromDate?: string; toDate?: string;
  };

  const where: string[] = [];
  const params: unknown[] = [];
  if (tableName) { where.push('a.table_name = ?'); params.push(tableName); }
  if (recordId) { where.push('a.record_id = ?'); params.push(Number(recordId)); }
  if (userId) { where.push('a.user_id = ?'); params.push(Number(userId)); }
  if (actionType) { where.push('a.action_type = ?'); params.push(actionType); }
  if (fromDate) { where.push('a.action_timestamp >= ?'); params.push(fromDate); }
  if (toDate) { where.push('a.action_timestamp <= ?'); params.push(toDate); }
  const whereClause = where.length ? `WHERE ${where.join(' AND ')}` : '';

  const [countRows] = await pool.query<RowDataPacket[]>(`SELECT COUNT(*) AS total FROM audit_logs a ${whereClause}`, params);
  const [rows] = await pool.query<RowDataPacket[]>(
    `SELECT a.audit_id, u.full_name AS user_name, a.table_name, a.record_id, a.action_type,
            a.old_values, a.new_values, a.action_timestamp, a.ip_address
       FROM audit_logs a LEFT JOIN users u ON a.user_id = u.user_id
       ${whereClause}
      ORDER BY a.action_timestamp DESC LIMIT ? OFFSET ?`,
    [...params, pagination.pageSize, pagination.offset]
  );

  res.status(200).json(paginatedResponse(rows, countRows[0]?.total ?? 0, pagination));
}
