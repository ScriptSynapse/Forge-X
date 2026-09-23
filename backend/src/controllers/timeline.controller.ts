import { Request, Response } from 'express';
import { pool, RowDataPacket } from '../config/db';
import { parsePagination, paginatedResponse } from '../utils/pagination';

/** GET /api/cases/:caseId/timeline — uses idx_timeline_case's underlying
 * FK index (04_indexes.sql notes: already covered by fk_timeline_case). */
export async function listTimelineForCase(req: Request, res: Response): Promise<void> {
  const caseId = Number(req.params.caseId);
  const pagination = parsePagination(req.query as Record<string, unknown>);

  const [countRows] = await pool.query<RowDataPacket[]>('SELECT COUNT(*) AS total FROM case_timeline WHERE case_id = ?', [caseId]);
  const [rows] = await pool.query<RowDataPacket[]>(
    `SELECT t.timeline_id, t.event_type, t.event_description, t.related_table, t.related_record_id,
            t.event_timestamp, u.full_name AS recorded_by
       FROM case_timeline t JOIN users u ON t.recorded_by = u.user_id
      WHERE t.case_id = ? ORDER BY t.event_timestamp DESC LIMIT ? OFFSET ?`,
    [caseId, pagination.pageSize, pagination.offset]
  );

  res.status(200).json(paginatedResponse(rows, countRows[0]?.total ?? 0, pagination));
}
