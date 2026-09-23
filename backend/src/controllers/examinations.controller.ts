import { Request, Response } from 'express';
import { pool, withActorConnection, RowDataPacket, ResultSetHeader } from '../config/db';
import { ApiError } from '../utils/ApiError';
import { parsePagination, paginatedResponse } from '../utils/pagination';
import { CreateExaminationInput, UpdateExaminationInput } from '../validators/examinations.validators';

const EXAM_SELECT = `
  ex.examination_id, ex.evidence_id, e.evidence_number, ft.tool_name, u.full_name AS examiner,
  ex.examination_type, ex.started_at, ex.completed_at, ex.findings_summary, ex.examination_status
`;

/** GET /api/examinations */
export async function listExaminations(req: Request, res: Response): Promise<void> {
  const pagination = parsePagination(req.query as Record<string, unknown>);
  const { evidenceId, status } = req.query as { evidenceId?: string; status?: string };

  const where: string[] = [];
  const params: unknown[] = [];
  if (evidenceId) { where.push('ex.evidence_id = ?'); params.push(Number(evidenceId)); }
  if (status) { where.push('ex.examination_status = ?'); params.push(status); }
  const whereClause = where.length ? `WHERE ${where.join(' AND ')}` : '';

  const [countRows] = await pool.query<RowDataPacket[]>(`SELECT COUNT(*) AS total FROM evidence_examinations ex ${whereClause}`, params);
  const [rows] = await pool.query<RowDataPacket[]>(
    `SELECT ${EXAM_SELECT} FROM evidence_examinations ex
       JOIN evidence e ON ex.evidence_id = e.evidence_id
       JOIN forensic_tools ft ON ex.tool_id = ft.tool_id
       JOIN users u ON ex.examiner_id = u.user_id
       ${whereClause}
      ORDER BY ex.started_at DESC LIMIT ? OFFSET ?`,
    [...params, pagination.pageSize, pagination.offset]
  );

  res.status(200).json(paginatedResponse(rows, countRows[0]?.total ?? 0, pagination));
}

/** GET /api/examinations/:id */
export async function getExamination(req: Request, res: Response): Promise<void> {
  const id = Number(req.params.id);
  const [rows] = await pool.query<RowDataPacket[]>(
    `SELECT ${EXAM_SELECT} FROM evidence_examinations ex
       JOIN evidence e ON ex.evidence_id = e.evidence_id
       JOIN forensic_tools ft ON ex.tool_id = ft.tool_id
       JOIN users u ON ex.examiner_id = u.user_id
      WHERE ex.examination_id = ?`,
    [id]
  );
  if (!rows[0]) throw ApiError.notFound(`Examination ${id} not found.`);
  res.status(200).json({ data: rows[0] });
}

/** POST /api/examinations — starts a new examination and logs it to
 * that evidence item's case timeline. */
export async function createExamination(req: Request, res: Response): Promise<void> {
  const actorUserId = req.user!.userId;
  const body = req.body as CreateExaminationInput;

  const examinationId = await withActorConnection(actorUserId, async (conn) => {
    const [evidenceRows] = await conn.query<RowDataPacket[]>(
      'SELECT case_id, evidence_number FROM evidence WHERE evidence_id = ?', [body.evidenceId]
    );
    if (!evidenceRows[0]) throw ApiError.badRequest('evidenceId does not exist.');

    const [result] = await conn.query<ResultSetHeader>(
      `INSERT INTO evidence_examinations (evidence_id, tool_id, examiner_id, examination_type, started_at)
       VALUES (?, ?, ?, ?, COALESCE(?, NOW()))`,
      [body.evidenceId, body.toolId, actorUserId, body.examinationType, body.startedAt ?? null]
    );

    await conn.query(
      `INSERT INTO case_timeline (case_id, event_type, event_description, related_table, related_record_id, recorded_by)
       VALUES (?, 'examination_started', CONCAT('Examination started on evidence ', ?, '.'), 'evidence_examinations', ?, ?)`,
      [evidenceRows[0].case_id, evidenceRows[0].evidence_number, result.insertId, actorUserId]
    );

    return result.insertId;
  });

  const [rows] = await pool.query<RowDataPacket[]>(
    `SELECT ${EXAM_SELECT} FROM evidence_examinations ex
       JOIN evidence e ON ex.evidence_id = e.evidence_id
       JOIN forensic_tools ft ON ex.tool_id = ft.tool_id
       JOIN users u ON ex.examiner_id = u.user_id
      WHERE ex.examination_id = ?`,
    [examinationId]
  );
  res.status(201).json({ data: rows[0] });
}

/** PUT /api/examinations/:id — status/findings updates. Logs an
 * examination_completed timeline event when status transitions to
 * 'completed' or 'peer_reviewed'. */
export async function updateExamination(req: Request, res: Response): Promise<void> {
  const id = Number(req.params.id);
  const actorUserId = req.user!.userId;
  const body = req.body as UpdateExaminationInput;

  await withActorConnection(actorUserId, async (conn) => {
    const [existingRows] = await conn.query<RowDataPacket[]>(
      `SELECT ex.examination_status, ex.evidence_id, e.case_id, e.evidence_number
         FROM evidence_examinations ex JOIN evidence e ON ex.evidence_id = e.evidence_id
        WHERE ex.examination_id = ? FOR UPDATE`,
      [id]
    );
    const existing = existingRows[0];
    if (!existing) throw ApiError.notFound(`Examination ${id} not found.`);

    const fields: string[] = [];
    const values: unknown[] = [];
    if (body.examinationStatus !== undefined) { fields.push('examination_status = ?'); values.push(body.examinationStatus); }
    if (body.findingsSummary !== undefined) { fields.push('findings_summary = ?'); values.push(body.findingsSummary); }
    if (body.completedAt !== undefined) { fields.push('completed_at = ?'); values.push(body.completedAt); }

    await conn.query(`UPDATE evidence_examinations SET ${fields.join(', ')} WHERE examination_id = ?`, [...values, id]);

    if (
      body.examinationStatus &&
      ['completed', 'peer_reviewed'].includes(body.examinationStatus) &&
      existing.examination_status !== body.examinationStatus
    ) {
      await conn.query(
        `INSERT INTO case_timeline (case_id, event_type, event_description, related_table, related_record_id, recorded_by)
         VALUES (?, 'examination_completed', CONCAT('Examination on evidence ', ?, ' marked ', ?, '.'), 'evidence_examinations', ?, ?)`,
        [existing.case_id, existing.evidence_number, body.examinationStatus, id, actorUserId]
      );
    }
  });

  const [rows] = await pool.query<RowDataPacket[]>(
    `SELECT ${EXAM_SELECT} FROM evidence_examinations ex
       JOIN evidence e ON ex.evidence_id = e.evidence_id
       JOIN forensic_tools ft ON ex.tool_id = ft.tool_id
       JOIN users u ON ex.examiner_id = u.user_id
      WHERE ex.examination_id = ?`,
    [id]
  );
  res.status(200).json({ data: rows[0] });
}
