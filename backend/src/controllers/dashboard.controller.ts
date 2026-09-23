import { Request, Response } from 'express';
import { pool, RowDataPacket } from '../config/db';

/**
 * GET /api/dashboard/summary
 * Every number below is a live COUNT/SUM against the actual tables and
 * views built in Steps 2-5 (vw_active_cases, vw_evidence_integrity —
 * 05_views.sql). Nothing here is a constant — if the underlying data
 * changes, every field in this response changes on the next request.
 */
export async function getDashboardSummary(_req: Request, res: Response): Promise<void> {
  const [
    [totalCasesRow],
    [activeCasesRow],
    [closedCasesRow],
    [evidenceCountRow],
    [deviceCountRow],
    [integrityAlertsRow],
    [pendingExamsRow],
    casesByStatus,
    casesByPriority,
  ] = await Promise.all([
    pool.query<RowDataPacket[]>('SELECT COUNT(*) AS count FROM cases').then((r) => r[0]),
    pool.query<RowDataPacket[]>('SELECT COUNT(*) AS count FROM vw_active_cases').then((r) => r[0]),
    pool.query<RowDataPacket[]>(`SELECT COUNT(*) AS count FROM cases WHERE status IN ('closed', 'archived')`).then((r) => r[0]),
    pool.query<RowDataPacket[]>('SELECT COUNT(*) AS count FROM evidence').then((r) => r[0]),
    pool.query<RowDataPacket[]>('SELECT COUNT(*) AS count FROM devices').then((r) => r[0]),
    pool
      .query<RowDataPacket[]>(`SELECT COUNT(*) AS count FROM vw_evidence_integrity WHERE integrity_status <> 'intact'`)
      .then((r) => r[0]),
    pool
      .query<RowDataPacket[]>(`SELECT COUNT(*) AS count FROM evidence_examinations WHERE examination_status IN ('scheduled','in_progress')`)
      .then((r) => r[0]),
    pool.query<RowDataPacket[]>('SELECT status, COUNT(*) AS count FROM cases GROUP BY status').then((r) => r[0]),
    pool.query<RowDataPacket[]>('SELECT priority, COUNT(*) AS count FROM cases GROUP BY priority').then((r) => r[0]),
  ]);

  res.status(200).json({
    data: {
      totalCases: totalCasesRow.count,
      activeCases: activeCasesRow.count,
      closedCases: closedCasesRow.count,
      evidenceCount: evidenceCountRow.count,
      deviceCount: deviceCountRow.count,
      integrityAlerts: integrityAlertsRow.count,
      pendingExaminations: pendingExamsRow.count,
      casesByStatus,
      casesByPriority,
    },
  });
}

/** GET /api/dashboard/workload — a straight pass-through of
 * vw_investigator_workload (05_views.sql). */
export async function getInvestigatorWorkload(_req: Request, res: Response): Promise<void> {
  const [rows] = await pool.query<RowDataPacket[]>(
    `SELECT * FROM vw_investigator_workload ORDER BY active_case_count DESC, assigned_case_count DESC`
  );
  res.status(200).json({ data: rows });
}

/** GET /api/dashboard/integrity-alerts — the evidence items actually
 * behind the integrityAlerts count above, for drill-down. */
export async function getIntegrityAlerts(_req: Request, res: Response): Promise<void> {
  const [rows] = await pool.query<RowDataPacket[]>(
    `SELECT * FROM vw_evidence_integrity WHERE integrity_status <> 'intact' ORDER BY evidence_id`
  );
  res.status(200).json({ data: rows });
}
