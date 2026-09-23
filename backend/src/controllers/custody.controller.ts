import { Request, Response } from 'express';
import { pool, RowDataPacket } from '../config/db';
import { parsePagination, paginatedResponse } from '../utils/pagination';

/**
 * GET /api/evidence/:evidenceId/custody
 * GET /api/custody (system-wide, filterable by date — uses
 * idx_custody_timestamp from 04_indexes.sql)
 *
 * Deliberately READ-ONLY: chain_of_custody has no direct-write
 * endpoint anywhere in this API. Every custody row in the system is
 * created exactly one way — either sp_register_evidence()'s initial
 * 'collected' entry, or trg_evidence_custody_audit firing when
 * sp_transfer_evidence() changes current_custodian_id. That is a
 * deliberate design choice (see 07_procedures.sql's header note): the
 * custody ledger must never be edited by hand, only appended to by the
 * one procedure built for it.
 */
export async function listCustodyForEvidence(req: Request, res: Response): Promise<void> {
  const evidenceId = Number(req.params.evidenceId);
  const [rows] = await pool.query<RowDataPacket[]>(
    `SELECT cc.custody_id, cc.custody_action, uf.full_name AS transferred_from, ut.full_name AS transferred_to,
            l.location_name, cc.custody_timestamp, cc.remarks
       FROM chain_of_custody cc
       LEFT JOIN users uf ON cc.transferred_from = uf.user_id
       JOIN users ut ON cc.transferred_to = ut.user_id
       JOIN locations l ON cc.location_id = l.location_id
      WHERE cc.evidence_id = ? ORDER BY cc.custody_timestamp DESC`,
    [evidenceId]
  );
  res.status(200).json({ data: rows });
}

export async function listCustody(req: Request, res: Response): Promise<void> {
  const pagination = parsePagination(req.query as Record<string, unknown>);
  const { fromDate, toDate } = req.query as { fromDate?: string; toDate?: string };

  const where: string[] = [];
  const params: unknown[] = [];
  if (fromDate) { where.push('cc.custody_timestamp >= ?'); params.push(fromDate); }
  if (toDate) { where.push('cc.custody_timestamp <= ?'); params.push(toDate); }
  const whereClause = where.length ? `WHERE ${where.join(' AND ')}` : '';

  const [countRows] = await pool.query<RowDataPacket[]>(`SELECT COUNT(*) AS total FROM chain_of_custody cc ${whereClause}`, params);
  const [rows] = await pool.query<RowDataPacket[]>(
    `SELECT cc.custody_id, e.evidence_number, cc.custody_action, uf.full_name AS transferred_from,
            ut.full_name AS transferred_to, l.location_name, cc.custody_timestamp
       FROM chain_of_custody cc
       JOIN evidence e ON cc.evidence_id = e.evidence_id
       LEFT JOIN users uf ON cc.transferred_from = uf.user_id
       JOIN users ut ON cc.transferred_to = ut.user_id
       JOIN locations l ON cc.location_id = l.location_id
       ${whereClause}
      ORDER BY cc.custody_timestamp DESC LIMIT ? OFFSET ?`,
    [...params, pagination.pageSize, pagination.offset]
  );

  res.status(200).json(paginatedResponse(rows, countRows[0]?.total ?? 0, pagination));
}
