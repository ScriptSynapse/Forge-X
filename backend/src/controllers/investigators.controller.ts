import { Request, Response } from 'express';
import { pool, withActorConnection, RowDataPacket, ResultSetHeader } from '../config/db';
import { ApiError } from '../utils/ApiError';
import { AssignInvestigatorInput } from '../validators/investigators.validators';

/** GET /api/cases/:caseId/investigators */
export async function listInvestigators(req: Request, res: Response): Promise<void> {
  const caseId = Number(req.params.caseId);
  const [rows] = await pool.query<RowDataPacket[]>(
    `SELECT u.user_id, u.full_name, u.username, ci.role_in_case, ci.assigned_at, ci.unassigned_at
       FROM case_investigators ci JOIN users u ON ci.user_id = u.user_id
      WHERE ci.case_id = ? ORDER BY ci.assigned_at`,
    [caseId]
  );
  res.status(200).json({ data: rows });
}

/** POST /api/cases/:caseId/investigators — calls sp_assign_investigator()
 * (07_procedures.sql), which validates the case/user and writes the
 * junction row + timeline event + audit_logs entry atomically. */
export async function assignInvestigator(req: Request, res: Response): Promise<void> {
  const caseId = Number(req.params.caseId);
  const actorUserId = req.user!.userId;
  const body = req.body as AssignInvestigatorInput;

  await withActorConnection(actorUserId, async (conn) => {
    await conn.query('CALL sp_assign_investigator(?, ?, ?, ?)', [caseId, body.userId, body.roleInCase, actorUserId]);
  });

  const [rows] = await pool.query<RowDataPacket[]>(
    `SELECT u.user_id, u.full_name, ci.role_in_case, ci.assigned_at
       FROM case_investigators ci JOIN users u ON ci.user_id = u.user_id
      WHERE ci.case_id = ? AND ci.user_id = ?`,
    [caseId, body.userId]
  );
  res.status(201).json({ data: rows[0] });
}

/** DELETE /api/cases/:caseId/investigators/:userId — soft-unassign
 * (sets unassigned_at rather than deleting the row, preserving history
 * of who was ever assigned to this case). No procedure exists for
 * this narrow action, so it is a direct, parameterized UPDATE. */
export async function unassignInvestigator(req: Request, res: Response): Promise<void> {
  const caseId = Number(req.params.caseId);
  const userId = Number(req.params.userId);
  const actorUserId = req.user!.userId;

  await withActorConnection(actorUserId, async (conn) => {
    const [result] = await conn.query<ResultSetHeader>(
      `UPDATE case_investigators SET unassigned_at = NOW()
        WHERE case_id = ? AND user_id = ? AND unassigned_at IS NULL`,
      [caseId, userId]
    );
    if (result.affectedRows === 0) {
      throw ApiError.notFound('This investigator is not currently assigned to this case.');
    }
    await conn.query(
      `INSERT INTO case_timeline (case_id, event_type, event_description, related_table, related_record_id, recorded_by)
       VALUES (?, 'other', CONCAT((SELECT full_name FROM users WHERE user_id = ?), ' was unassigned from the case.'), 'case_investigators', ?, ?)`,
      [caseId, userId, userId, actorUserId]
    );
  });

  res.status(204).send();
}
