import { Request, Response } from 'express';
import { pool, withActorConnection, RowDataPacket, ResultSetHeader } from '../config/db';
import { ApiError } from '../utils/ApiError';
import { CreateHashInput } from '../validators/evidenceHashes.validators';

/** GET /api/evidence/:evidenceId/hashes */
export async function listHashes(req: Request, res: Response): Promise<void> {
  const evidenceId = Number(req.params.evidenceId);
  const [rows] = await pool.query<RowDataPacket[]>(
    `SELECT eh.hash_id, eh.hash_algorithm, eh.hash_value, eh.is_original, eh.computed_at,
            u.full_name AS computed_by
       FROM evidence_hashes eh JOIN users u ON eh.computed_by = u.user_id
      WHERE eh.evidence_id = ? ORDER BY eh.computed_at DESC`,
    [evidenceId]
  );
  res.status(200).json({ data: rows });
}

/** POST /api/evidence/:evidenceId/hashes — logs an initial/reference
 * hash at acquisition time. (Re-verification against an EXISTING
 * reference goes through POST /api/evidence/:id/verify ->
 * sp_verify_evidence instead — this endpoint is for the first hash
 * logged on a piece of evidence, which sp_register_evidence does not
 * do on the caller's behalf since the hash is computed by a separate
 * tool after acquisition.) */
export async function createHash(req: Request, res: Response): Promise<void> {
  const evidenceId = Number(req.params.evidenceId);
  const actorUserId = req.user!.userId;
  const body = req.body as CreateHashInput;

  const evidence = await pool.query<RowDataPacket[]>('SELECT evidence_id FROM evidence WHERE evidence_id = ?', [evidenceId]);
  if (!evidence[0][0]) throw ApiError.notFound(`Evidence ${evidenceId} not found.`);

  const hashId = await withActorConnection(actorUserId, async (conn) => {
    const [result] = await conn.query<ResultSetHeader>(
      `INSERT INTO evidence_hashes (evidence_id, hash_algorithm, hash_value, computed_by, is_original)
       VALUES (?, ?, ?, ?, ?)`,
      [evidenceId, body.hashAlgorithm, body.hashValue, actorUserId, body.isOriginal === false ? 0 : 1]
    );
    return result.insertId;
  });

  const [rows] = await pool.query<RowDataPacket[]>('SELECT * FROM evidence_hashes WHERE hash_id = ?', [hashId]);
  res.status(201).json({ data: rows[0] });
}
