import { Request, Response } from 'express';
import { pool, withActorConnection, RowDataPacket, ResultSetHeader } from '../config/db';
import { ApiError } from '../utils/ApiError';
import { parsePagination, paginatedResponse } from '../utils/pagination';
import { CreateCaseInput, UpdateCaseInput } from '../validators/cases.validators';
import { caseScopeSqlFilter } from '../middleware/caseAccess';
import { Role } from '../config/permissions';

interface CaseSummaryRow extends RowDataPacket {
  case_id: number;
  case_number: string;
  case_title: string;
  case_type: string;
  status: string;
  priority: string;
  investigator_count: number;
  person_count: number;
  device_count: number;
  evidence_count: number;
  report_count: number;
  opened_at: string;
  closed_at: string | null;
  days_duration: number;
}

/** GET /api/cases — list, filterable, paginated. Built on vw_case_summary
 * (05_views.sql) so counts are never computed by hand in JS. */
export async function listCases(req: Request, res: Response): Promise<void> {
  const pagination = parsePagination(req.query as Record<string, unknown>);
  const { status, priority, caseTypeId, search } = req.query as {
    status?: string;
    priority?: string;
    caseTypeId?: string;
    search?: string;
  };

  const where: string[] = [];
  const params: unknown[] = [];
  if (status) {
    where.push('status = ?');
    params.push(status);
  }
  if (priority) {
    where.push('priority = ?');
    params.push(priority);
  }
  if (caseTypeId) {
    where.push('case_type_id = (SELECT case_type_id FROM case_types WHERE case_type_id = ?)');
    params.push(Number(caseTypeId));
  }
  if (search) {
    where.push('(case_number LIKE ? OR case_title LIKE ?)');
    params.push(`%${search}%`, `%${search}%`);
  }

  // Row-level scoping: an INVESTIGATOR's "assigned cases" grant means
  // their case list is silently narrowed at the SQL layer, not
  // filtered in JS after fetching every case (which would still pull
  // other investigators' case data out of the database first).
  const scope = caseScopeSqlFilter(req.user!.roleName as Role, req.user!.userId, 'case_id');
  if (scope) {
    where.push(scope.clause);
    params.push(...scope.params);
  }

  const whereClause = where.length ? `WHERE ${where.join(' AND ')}` : '';

  const [countRows] = await pool.query<RowDataPacket[]>(
    `SELECT COUNT(*) AS total FROM vw_case_summary ${whereClause}`,
    params
  );
  const total = countRows[0]?.total ?? 0;

  const [rows] = await pool.query<CaseSummaryRow[]>(
    `SELECT * FROM vw_case_summary ${whereClause} ORDER BY case_id DESC LIMIT ? OFFSET ?`,
    [...params, pagination.pageSize, pagination.offset]
  );

  res.status(200).json(paginatedResponse(rows, total, pagination));
}

/** GET /api/cases/:id — full case detail: summary row + investigators +
 * persons + devices + evidence + reports, fetched in parallel. */
export async function getCase(req: Request, res: Response): Promise<void> {
  const caseId = Number(req.params.id);

  const [summaryRows] = await pool.query<CaseSummaryRow[]>(
    'SELECT * FROM vw_case_summary WHERE case_id = ?',
    [caseId]
  );
  const summary = summaryRows[0];
  if (!summary) {
    throw ApiError.notFound(`Case ${caseId} not found.`);
  }

  const [investigators, persons, devices, evidence, reports, timeline] = await Promise.all([
    pool.query<RowDataPacket[]>(
      `SELECT u.user_id, u.full_name, ci.role_in_case, ci.assigned_at, ci.unassigned_at
         FROM case_investigators ci JOIN users u ON ci.user_id = u.user_id
        WHERE ci.case_id = ? ORDER BY ci.assigned_at`,
      [caseId]
    ),
    pool.query<RowDataPacket[]>(
      `SELECT p.person_id, p.first_name, p.last_name, cp.person_role, cp.notes, cp.linked_at
         FROM case_persons cp JOIN persons p ON cp.person_id = p.person_id
        WHERE cp.case_id = ? ORDER BY cp.linked_at`,
      [caseId]
    ),
    pool.query<RowDataPacket[]>(
      `SELECT d.device_id, d.serial_number, d.make, d.model, dt.type_name AS device_type, d.device_status
         FROM devices d JOIN device_types dt ON d.device_type_id = dt.device_type_id
        WHERE d.case_id = ? ORDER BY d.device_id`,
      [caseId]
    ),
    pool.query<RowDataPacket[]>(
      `SELECT e.evidence_id, e.evidence_number, et.type_name AS evidence_type,
              e.integrity_status, e.current_custodian_id, u.full_name AS current_custodian
         FROM evidence e
         JOIN evidence_types et ON e.evidence_type_id = et.evidence_type_id
         LEFT JOIN users u ON e.current_custodian_id = u.user_id
        WHERE e.case_id = ? ORDER BY e.evidence_id`,
      [caseId]
    ),
    pool.query<RowDataPacket[]>(
      `SELECT report_id, report_number, title, report_status, created_at, finalized_at
         FROM forensic_reports WHERE case_id = ? ORDER BY created_at DESC`,
      [caseId]
    ),
    pool.query<RowDataPacket[]>(
      `SELECT timeline_id, event_type, event_description, event_timestamp
         FROM case_timeline WHERE case_id = ? ORDER BY event_timestamp DESC LIMIT 20`,
      [caseId]
    ),
  ]);

  res.status(200).json({
    data: {
      ...summary,
      investigators: investigators[0],
      persons: persons[0],
      devices: devices[0],
      evidence: evidence[0],
      reports: reports[0],
      recentTimeline: timeline[0],
    },
  });
}

/** POST /api/cases — creates via sp_create_case() (07_procedures.sql),
 * never a raw INSERT, so the case-opened timeline event is guaranteed
 * to exist in exactly one place: the procedure. */
export async function createCase(req: Request, res: Response): Promise<void> {
  const actorUserId = req.user!.userId;
  const body = req.body as CreateCaseInput;

  const caseId = await withActorConnection(actorUserId, async (conn) => {
    await conn.query(
      `CALL sp_create_case(?, ?, ?, ?, ?, ?, ?, @out_case_id)`,
      [
        body.caseNumber,
        body.caseTitle,
        body.caseTypeId,
        body.priority ?? 'medium',
        body.jurisdictionLocationId ?? null,
        body.description ?? null,
        actorUserId,
      ]
    );
    const [outRows] = await conn.query<RowDataPacket[]>('SELECT @out_case_id AS case_id');
    return outRows[0].case_id as number;
  });

  const [rows] = await pool.query<CaseSummaryRow[]>('SELECT * FROM vw_case_summary WHERE case_id = ?', [caseId]);
  res.status(201).json({ data: rows[0] });
}

/** PUT /api/cases/:id — updates editable metadata directly (no
 * dedicated procedure covers generic field edits). Manually writes an
 * audit_logs row since — unlike `evidence` (Trigger 5) — `cases` has
 * no field-level change-audit trigger; this is the API layer covering
 * ground the DB layer intentionally leaves to it. */
export async function updateCase(req: Request, res: Response): Promise<void> {
  const caseId = Number(req.params.id);
  const actorUserId = req.user!.userId;
  const body = req.body as UpdateCaseInput;

  await withActorConnection(actorUserId, async (conn) => {
    const [existingRows] = await conn.query<RowDataPacket[]>(
      'SELECT case_title, priority, jurisdiction_location_id, description FROM cases WHERE case_id = ? FOR UPDATE',
      [caseId]
    );
    const existing = existingRows[0];
    if (!existing) {
      throw ApiError.notFound(`Case ${caseId} not found.`);
    }

    const fields: string[] = [];
    const values: unknown[] = [];
    if (body.caseTitle !== undefined) { fields.push('case_title = ?'); values.push(body.caseTitle); }
    if (body.priority !== undefined) { fields.push('priority = ?'); values.push(body.priority); }
    if (body.jurisdictionLocationId !== undefined) { fields.push('jurisdiction_location_id = ?'); values.push(body.jurisdictionLocationId); }
    if (body.description !== undefined) { fields.push('description = ?'); values.push(body.description); }

    await conn.query(`UPDATE cases SET ${fields.join(', ')} WHERE case_id = ?`, [...values, caseId]);

    await conn.query(
      `INSERT INTO audit_logs (user_id, table_name, record_id, action_type, old_values, new_values)
       VALUES (?, 'cases', ?, 'UPDATE', ?, ?)`,
      [actorUserId, caseId, JSON.stringify(existing), JSON.stringify(body)]
    );
  });

  const [rows] = await pool.query<CaseSummaryRow[]>('SELECT * FROM vw_case_summary WHERE case_id = ?', [caseId]);
  res.status(200).json({ data: rows[0] });
}

/** PATCH /api/cases/:id/status — routes 'closed' through sp_close_case()
 * (which enforces the examination/report business rules from
 * 07_procedures.sql); any other status transition is a direct UPDATE,
 * which trg_cases_status_change (08_triggers.sql) automatically logs
 * to case_timeline as a CASE_STATUS_CHANGED event. */
export async function updateCaseStatus(req: Request, res: Response): Promise<void> {
  const caseId = Number(req.params.id);
  const actorUserId = req.user!.userId;
  const { status } = req.body as { status: string };

  if (status === 'closed') {
    const message = await withActorConnection(actorUserId, async (conn) => {
      await conn.query('CALL sp_close_case(?, ?, @out_message)', [caseId, actorUserId]);
      const [outRows] = await conn.query<RowDataPacket[]>('SELECT @out_message AS message');
      return outRows[0].message as string;
    });
    const [rows] = await pool.query<CaseSummaryRow[]>('SELECT * FROM vw_case_summary WHERE case_id = ?', [caseId]);
    res.status(200).json({ data: rows[0], message });
    return;
  }

  await withActorConnection(actorUserId, async (conn) => {
    const [existing] = await conn.query<RowDataPacket[]>('SELECT status FROM cases WHERE case_id = ? FOR UPDATE', [caseId]);
    if (!existing[0]) {
      throw ApiError.notFound(`Case ${caseId} not found.`);
    }
    const [result] = await conn.query<ResultSetHeader>('UPDATE cases SET status = ? WHERE case_id = ?', [status, caseId]);
    if (result.affectedRows === 0) {
      throw ApiError.notFound(`Case ${caseId} not found.`);
    }
  });

  const [rows] = await pool.query<CaseSummaryRow[]>('SELECT * FROM vw_case_summary WHERE case_id = ?', [caseId]);
  res.status(200).json({ data: rows[0] });
}
