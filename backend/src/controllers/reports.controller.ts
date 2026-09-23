import { Request, Response } from 'express';
import { pool, withActorConnection, RowDataPacket, ResultSetHeader } from '../config/db';
import { ApiError } from '../utils/ApiError';
import { parsePagination, paginatedResponse } from '../utils/pagination';
import { CreateReportInput, UpdateReportStatusInput, AddReportVersionInput } from '../validators/reports.validators';

/** GET /api/reports */
export async function listReports(req: Request, res: Response): Promise<void> {
  const pagination = parsePagination(req.query as Record<string, unknown>);
  const { caseId, status } = req.query as { caseId?: string; status?: string };

  const where: string[] = [];
  const params: unknown[] = [];
  if (caseId) { where.push('r.case_id = ?'); params.push(Number(caseId)); }
  if (status) { where.push('r.report_status = ?'); params.push(status); }
  const whereClause = where.length ? `WHERE ${where.join(' AND ')}` : '';

  const [countRows] = await pool.query<RowDataPacket[]>(`SELECT COUNT(*) AS total FROM forensic_reports r ${whereClause}`, params);
  const [rows] = await pool.query<RowDataPacket[]>(
    `SELECT r.report_id, r.report_number, c.case_number, r.title, r.report_status,
            up.full_name AS prepared_by, ur.full_name AS reviewed_by, r.created_at, r.finalized_at
       FROM forensic_reports r
       JOIN cases c ON r.case_id = c.case_id
       JOIN users up ON r.prepared_by = up.user_id
       LEFT JOIN users ur ON r.reviewed_by = ur.user_id
       ${whereClause}
      ORDER BY r.created_at DESC LIMIT ? OFFSET ?`,
    [...params, pagination.pageSize, pagination.offset]
  );

  res.status(200).json(paginatedResponse(rows, countRows[0]?.total ?? 0, pagination));
}

/** GET /api/reports/:id — includes full version history. */
export async function getReport(req: Request, res: Response): Promise<void> {
  const id = Number(req.params.id);
  const [rows] = await pool.query<RowDataPacket[]>(
    `SELECT r.report_id, r.report_number, c.case_number, r.title, r.report_status,
            up.full_name AS prepared_by, ur.full_name AS reviewed_by, r.created_at, r.finalized_at
       FROM forensic_reports r
       JOIN cases c ON r.case_id = c.case_id
       JOIN users up ON r.prepared_by = up.user_id
       LEFT JOIN users ur ON r.reviewed_by = ur.user_id
      WHERE r.report_id = ?`,
    [id]
  );
  if (!rows[0]) throw ApiError.notFound(`Report ${id} not found.`);

  const [versions] = await pool.query<RowDataPacket[]>(
    `SELECT v.version_id, v.version_number, v.file_path, v.change_summary, v.created_at, u.full_name AS created_by
       FROM report_versions v JOIN users u ON v.created_by = u.user_id
      WHERE v.report_id = ? ORDER BY v.version_number DESC`,
    [id]
  );

  res.status(200).json({ data: { ...rows[0], versions } });
}

/** POST /api/reports — creates the report plus its version 1, atomically,
 * and logs a report_filed timeline event. */
export async function createReport(req: Request, res: Response): Promise<void> {
  const actorUserId = req.user!.userId;
  const body = req.body as CreateReportInput;

  const reportId = await withActorConnection(actorUserId, async (conn) => {
    const [result] = await conn.query<ResultSetHeader>(
      `INSERT INTO forensic_reports (case_id, report_number, title, prepared_by) VALUES (?, ?, ?, ?)`,
      [body.caseId, body.reportNumber, body.title, actorUserId]
    );
    const newReportId = result.insertId;

    await conn.query(
      `INSERT INTO report_versions (report_id, version_number, file_path, created_by) VALUES (?, 1, ?, ?)`,
      [newReportId, body.filePath, actorUserId]
    );

    await conn.query(
      `INSERT INTO case_timeline (case_id, event_type, event_description, related_table, related_record_id, recorded_by)
       VALUES (?, 'report_filed', CONCAT('Report ', ?, ' filed: ', ?, '.'), 'forensic_reports', ?, ?)`,
      [body.caseId, body.reportNumber, body.title, newReportId, actorUserId]
    );

    return newReportId;
  });

  const [rows] = await pool.query<RowDataPacket[]>('SELECT * FROM forensic_reports WHERE report_id = ?', [reportId]);
  res.status(201).json({ data: rows[0] });
}

/** PATCH /api/reports/:id/status — report_status transitions. The
 * chk_reports_reviewer_ne_author CHECK constraint (03_constraints.sql)
 * is the ultimate guarantor that a reviewer can never be the same
 * person as the preparer; this endpoint's own check below just gives a
 * friendlier 400 instead of letting that surface as a raw SQL error. */
export async function updateReportStatus(req: Request, res: Response): Promise<void> {
  const id = Number(req.params.id);
  const actorUserId = req.user!.userId;
  const body = req.body as UpdateReportStatusInput;

  await withActorConnection(actorUserId, async (conn) => {
    const [existingRows] = await conn.query<RowDataPacket[]>(
      'SELECT prepared_by FROM forensic_reports WHERE report_id = ? FOR UPDATE', [id]
    );
    if (!existingRows[0]) throw ApiError.notFound(`Report ${id} not found.`);

    if (body.reviewedBy && body.reviewedBy === existingRows[0].prepared_by) {
      throw ApiError.badRequest('The reviewer cannot be the same user who prepared the report.');
    }

    const fields = ['report_status = ?'];
    const values: unknown[] = [body.reportStatus];
    if (body.reviewedBy !== undefined) { fields.push('reviewed_by = ?'); values.push(body.reviewedBy); }
    if (body.reportStatus === 'finalized') { fields.push('finalized_at = NOW()'); }

    await conn.query(`UPDATE forensic_reports SET ${fields.join(', ')} WHERE report_id = ?`, [...values, id]);
  });

  const [rows] = await pool.query<RowDataPacket[]>('SELECT * FROM forensic_reports WHERE report_id = ?', [id]);
  res.status(200).json({ data: rows[0] });
}

/** POST /api/reports/:id/versions — appends the next version_number
 * (uq_report_versions_report_version, 02_tables.sql, guarantees no
 * duplicate/racing version numbers even under concurrent requests). */
export async function addReportVersion(req: Request, res: Response): Promise<void> {
  const id = Number(req.params.id);
  const actorUserId = req.user!.userId;
  const body = req.body as AddReportVersionInput;

  const versionId = await withActorConnection(actorUserId, async (conn) => {
    const [reportRows] = await conn.query<RowDataPacket[]>(
      'SELECT report_id FROM forensic_reports WHERE report_id = ? FOR UPDATE', [id]
    );
    if (!reportRows[0]) throw ApiError.notFound(`Report ${id} not found.`);

    const [maxRows] = await conn.query<RowDataPacket[]>(
      'SELECT COALESCE(MAX(version_number), 0) AS max_version FROM report_versions WHERE report_id = ?', [id]
    );
    const nextVersion = (maxRows[0].max_version as number) + 1;

    const [result] = await conn.query<ResultSetHeader>(
      `INSERT INTO report_versions (report_id, version_number, file_path, change_summary, created_by)
       VALUES (?, ?, ?, ?, ?)`,
      [id, nextVersion, body.filePath, body.changeSummary ?? null, actorUserId]
    );
    return result.insertId;
  });

  const [rows] = await pool.query<RowDataPacket[]>('SELECT * FROM report_versions WHERE version_id = ?', [versionId]);
  res.status(201).json({ data: rows[0] });
}
