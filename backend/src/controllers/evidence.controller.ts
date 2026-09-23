import { Request, Response } from 'express';
import { pool, withActorConnection, RowDataPacket } from '../config/db';
import { ApiError } from '../utils/ApiError';
import { parsePagination, paginatedResponse } from '../utils/pagination';
import {
  CreateEvidenceInput,
  UpdateEvidenceInput,
  VerifyEvidenceInput,
  TransferEvidenceInput,
} from '../validators/evidence.validators';
import { CASE_SCOPED_ROLES, Role } from '../config/permissions';

interface EvidenceIntegrityRow extends RowDataPacket {
  evidence_id: number;
  evidence_number: string;
  case_number: string;
  integrity_status: string;
  evidence_type: string;
  reference_algorithm: string | null;
  reference_hash_value: string | null;
  reference_hash_computed_at: string | null;
  total_hash_records: number;
  total_custody_events: number;
  total_examinations: number;
}

/** GET /api/evidence — list, filterable, paginated. Built on
 * vw_evidence_integrity (05_views.sql). */
export async function listEvidence(req: Request, res: Response): Promise<void> {
  const pagination = parsePagination(req.query as Record<string, unknown>);
  const { caseId, integrityStatus, search } = req.query as {
    caseId?: string; integrityStatus?: string; search?: string;
  };

  const where: string[] = [];
  const params: unknown[] = [];
  if (caseId) {
    where.push('case_number = (SELECT case_number FROM cases WHERE case_id = ?)');
    params.push(Number(caseId));
  }
  if (integrityStatus) {
    where.push('integrity_status = ?');
    params.push(integrityStatus);
  }
  if (search) {
    where.push('evidence_number LIKE ?');
    params.push(`%${search}%`);
  }

  if (CASE_SCOPED_ROLES.has(req.user!.roleName as Role)) {
    // vw_evidence_integrity exposes case_number, not case_id, so scope
    // against a case_number subquery to stay consistent with the rest
    // of this endpoint's WHERE clauses (which also key off case_number
    // for the caseId filter above).
    where.push(
      `case_number IN (SELECT c.case_number FROM cases c
         WHERE c.case_id IN (SELECT case_id FROM case_investigators WHERE user_id = ? AND unassigned_at IS NULL))`
    );
    params.push(req.user!.userId);
  }

  const whereClause = where.length ? `WHERE ${where.join(' AND ')}` : '';

  const [countRows] = await pool.query<RowDataPacket[]>(
    `SELECT COUNT(*) AS total FROM vw_evidence_integrity ${whereClause}`, params
  );
  const total = countRows[0]?.total ?? 0;

  const [rows] = await pool.query<EvidenceIntegrityRow[]>(
    `SELECT * FROM vw_evidence_integrity ${whereClause} ORDER BY evidence_id DESC LIMIT ? OFFSET ?`,
    [...params, pagination.pageSize, pagination.offset]
  );

  res.status(200).json(paginatedResponse(rows, total, pagination));
}

/** GET /api/evidence/:id — full detail: integrity summary + custody
 * history + hash records + examinations, in parallel. */
export async function getEvidence(req: Request, res: Response): Promise<void> {
  const evidenceId = Number(req.params.id);

  const [summaryRows] = await pool.query<EvidenceIntegrityRow[]>(
    'SELECT * FROM vw_evidence_integrity WHERE evidence_id = ?', [evidenceId]
  );
  const summary = summaryRows[0];
  if (!summary) {
    throw ApiError.notFound(`Evidence ${evidenceId} not found.`);
  }

  const [custody, hashes, examinations, custodianRow] = await Promise.all([
    pool.query<RowDataPacket[]>(
      `SELECT cc.custody_id, cc.custody_action, uf.full_name AS transferred_from, ut.full_name AS transferred_to,
              l.location_name, cc.custody_timestamp, cc.remarks
         FROM chain_of_custody cc
         LEFT JOIN users uf ON cc.transferred_from = uf.user_id
         JOIN users ut ON cc.transferred_to = ut.user_id
         JOIN locations l ON cc.location_id = l.location_id
        WHERE cc.evidence_id = ? ORDER BY cc.custody_timestamp DESC`,
      [evidenceId]
    ),
    pool.query<RowDataPacket[]>(
      `SELECT hash_id, hash_algorithm, hash_value, is_original, computed_at,
              (SELECT full_name FROM users WHERE user_id = evidence_hashes.computed_by) AS computed_by
         FROM evidence_hashes WHERE evidence_id = ? ORDER BY computed_at DESC`,
      [evidenceId]
    ),
    pool.query<RowDataPacket[]>(
      `SELECT ex.examination_id, ex.examination_type, ex.examination_status, ft.tool_name,
              u.full_name AS examiner, ex.started_at, ex.completed_at, ex.findings_summary
         FROM evidence_examinations ex
         JOIN forensic_tools ft ON ex.tool_id = ft.tool_id
         JOIN users u ON ex.examiner_id = u.user_id
        WHERE ex.evidence_id = ? ORDER BY ex.started_at DESC`,
      [evidenceId]
    ),
    pool.query<RowDataPacket[]>(
      `SELECT e.current_custodian_id, u.full_name AS current_custodian_name
         FROM evidence e LEFT JOIN users u ON e.current_custodian_id = u.user_id
        WHERE e.evidence_id = ?`,
      [evidenceId]
    ),
  ]);

  res.status(200).json({
    data: {
      ...summary,
      currentCustodianId: custodianRow[0][0]?.current_custodian_id ?? null,
      currentCustodianName: custodianRow[0][0]?.current_custodian_name ?? null,
      custodyHistory: custody[0],
      hashRecords: hashes[0],
      examinations: examinations[0],
    },
  });
}

/** POST /api/evidence — registers new evidence via sp_register_evidence()
 * (07_procedures.sql), which atomically creates the evidence row, its
 * first chain_of_custody 'collected' entry, and a timeline event. */
export async function createEvidence(req: Request, res: Response): Promise<void> {
  const actorUserId = req.user!.userId;
  const body = req.body as CreateEvidenceInput;

  // caseId is in the request BODY here, not a route param, so the
  // requireCaseAssignmentViaEvidence middleware (which reads params)
  // can't cover this endpoint -- the same row-level rule is applied
  // inline instead: an INVESTIGATOR may only register evidence under a
  // case they are actually assigned to.
  if (CASE_SCOPED_ROLES.has(req.user!.roleName as Role)) {
    const [assignmentRows] = await pool.query<RowDataPacket[]>(
      `SELECT 1 FROM case_investigators WHERE case_id = ? AND user_id = ? AND unassigned_at IS NULL LIMIT 1`,
      [body.caseId, actorUserId]
    );
    if (!assignmentRows[0]) {
      throw ApiError.forbidden(
        `As ${req.user!.roleName}, you can only register evidence for cases you are assigned to.`
      );
    }
  }

  const evidenceId = await withActorConnection(actorUserId, async (conn) => {
    await conn.query(
      `CALL sp_register_evidence(?, ?, ?, ?, ?, ?, ?, ?, @out_evidence_id)`,
      [
        body.evidenceNumber,
        body.caseId,
        body.deviceId ?? null,
        body.evidenceTypeId,
        body.description,
        body.acquisitionMethod,
        actorUserId,
        body.storageLocationId ?? null,
      ]
    );
    const [outRows] = await conn.query<RowDataPacket[]>('SELECT @out_evidence_id AS evidence_id');
    return outRows[0].evidence_id as number;
  });

  const [rows] = await pool.query<EvidenceIntegrityRow[]>(
    'SELECT * FROM vw_evidence_integrity WHERE evidence_id = ?', [evidenceId]
  );
  res.status(201).json({ data: rows[0] });
}

/** PUT /api/evidence/:id — updates evidentiarily significant metadata
 * directly. trg_evidence_important_changes_audit (08_triggers.sql)
 * automatically writes the audit_logs row for this — the API layer
 * does NOT duplicate that insert, the same non-duplication principle
 * applied throughout 07_procedures.sql. */
export async function updateEvidence(req: Request, res: Response): Promise<void> {
  const evidenceId = Number(req.params.id);
  const actorUserId = req.user!.userId;
  const body = req.body as UpdateEvidenceInput;

  await withActorConnection(actorUserId, async (conn) => {
    const [existing] = await conn.query<RowDataPacket[]>(
      'SELECT evidence_id FROM evidence WHERE evidence_id = ? FOR UPDATE', [evidenceId]
    );
    if (!existing[0]) {
      throw ApiError.notFound(`Evidence ${evidenceId} not found.`);
    }

    const fields: string[] = [];
    const values: unknown[] = [];
    if (body.description !== undefined) { fields.push('description = ?'); values.push(body.description); }
    if (body.integrityStatus !== undefined) { fields.push('integrity_status = ?'); values.push(body.integrityStatus); }
    if (body.storageLocationId !== undefined) { fields.push('storage_location_id = ?'); values.push(body.storageLocationId); }
    if (body.filePath !== undefined) { fields.push('file_path = ?'); values.push(body.filePath); }
    if (body.evidenceTypeId !== undefined) { fields.push('evidence_type_id = ?'); values.push(body.evidenceTypeId); }

    // trg_evidence_important_changes_audit fires automatically here.
    await conn.query(`UPDATE evidence SET ${fields.join(', ')} WHERE evidence_id = ?`, [...values, evidenceId]);
  });

  const [rows] = await pool.query<EvidenceIntegrityRow[]>(
    'SELECT * FROM vw_evidence_integrity WHERE evidence_id = ?', [evidenceId]
  );
  res.status(200).json({ data: rows[0] });
}

/** POST /api/evidence/:id/verify — calls sp_verify_evidence()
 * (07_procedures.sql) directly. This endpoint deliberately contains NO
 * hash-comparison logic of its own — fn_compare_hash() inside the
 * procedure is the single source of truth for what counts as a match,
 * so the API and any future caller (a CLI tool, a batch job) can never
 * disagree with each other about it. */
export async function verifyEvidence(req: Request, res: Response): Promise<void> {
  const evidenceId = Number(req.params.id);
  const actorUserId = req.user!.userId;
  const body = req.body as VerifyEvidenceInput;

  const matchResult = await withActorConnection(actorUserId, async (conn) => {
    await conn.query(
      'CALL sp_verify_evidence(?, ?, ?, ?, @out_match_result)',
      [evidenceId, body.hashAlgorithm, body.freshlyComputedHash, actorUserId]
    );
    const [outRows] = await conn.query<RowDataPacket[]>('SELECT @out_match_result AS match_result');
    return outRows[0].match_result as string;
  });

  const [rows] = await pool.query<EvidenceIntegrityRow[]>(
    'SELECT * FROM vw_evidence_integrity WHERE evidence_id = ?', [evidenceId]
  );

  res.status(200).json({ data: { matchResult, evidence: rows[0] } });
}

/** POST /api/evidence/:id/transfer — calls sp_transfer_evidence()
 * (07_procedures.sql) — THE flagship procedure from Step 5. This
 * endpoint does not perform any of the 8 custody-transfer steps
 * itself (no manual chain_of_custody insert, no manual audit_logs
 * insert, no manual lock/validation) — it is a thin pass-through to
 * the procedure by design, per the project brief. */
export async function transferEvidence(req: Request, res: Response): Promise<void> {
  const evidenceId = Number(req.params.id);
  const actorUserId = req.user!.userId;
  const body = req.body as TransferEvidenceInput;

  await withActorConnection(actorUserId, async (conn) => {
    await conn.query(
      'CALL sp_transfer_evidence(?, ?, ?, ?, ?, ?)',
      [
        evidenceId,
        body.newCustodianId,
        actorUserId,
        body.expectedCurrentCustodianId ?? null,
        body.locationId ?? null,
        body.remarks ?? null,
      ]
    );
  });

  const [rows] = await pool.query<EvidenceIntegrityRow[]>(
    'SELECT * FROM vw_evidence_integrity WHERE evidence_id = ?', [evidenceId]
  );
  const [custodyRows] = await pool.query<RowDataPacket[]>(
    `SELECT cc.custody_action, ut.full_name AS transferred_to, cc.custody_timestamp, cc.remarks
       FROM chain_of_custody cc JOIN users ut ON cc.transferred_to = ut.user_id
      WHERE cc.evidence_id = ? ORDER BY cc.custody_id DESC LIMIT 1`,
    [evidenceId]
  );

  res.status(200).json({ data: { evidence: rows[0], latestCustodyEvent: custodyRows[0] } });
}
