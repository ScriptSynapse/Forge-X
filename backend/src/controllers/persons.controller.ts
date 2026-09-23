import { Request, Response } from 'express';
import { pool, withActorConnection, RowDataPacket, ResultSetHeader } from '../config/db';
import { ApiError } from '../utils/ApiError';
import { parsePagination, paginatedResponse } from '../utils/pagination';
import { CreatePersonInput, LinkPersonToCaseInput } from '../validators/persons.validators';

/** GET /api/persons — uses idx_persons_name (04_indexes.sql) for the search path. */
export async function listPersons(req: Request, res: Response): Promise<void> {
  const pagination = parsePagination(req.query as Record<string, unknown>);
  const { search } = req.query as { search?: string };

  const where: string[] = [];
  const params: unknown[] = [];
  if (search) {
    where.push('(last_name LIKE ? OR first_name LIKE ? OR national_id_number LIKE ?)');
    params.push(`%${search}%`, `%${search}%`, `%${search}%`);
  }
  const whereClause = where.length ? `WHERE ${where.join(' AND ')}` : '';

  const [countRows] = await pool.query<RowDataPacket[]>(`SELECT COUNT(*) AS total FROM persons ${whereClause}`, params);
  const [rows] = await pool.query<RowDataPacket[]>(
    `SELECT person_id, first_name, last_name, date_of_birth, national_id_number, gender, phone_number, email
       FROM persons ${whereClause} ORDER BY last_name, first_name LIMIT ? OFFSET ?`,
    [...params, pagination.pageSize, pagination.offset]
  );

  res.status(200).json(paginatedResponse(rows, countRows[0]?.total ?? 0, pagination));
}

/** GET /api/persons/:id — includes every case this person is linked to. */
export async function getPerson(req: Request, res: Response): Promise<void> {
  const personId = Number(req.params.id);
  const [rows] = await pool.query<RowDataPacket[]>('SELECT * FROM persons WHERE person_id = ?', [personId]);
  if (!rows[0]) throw ApiError.notFound(`Person ${personId} not found.`);

  const [caseLinks] = await pool.query<RowDataPacket[]>(
    `SELECT c.case_id, c.case_number, c.case_title, cp.person_role, cp.notes, cp.linked_at
       FROM case_persons cp JOIN cases c ON cp.case_id = c.case_id
      WHERE cp.person_id = ? ORDER BY cp.linked_at DESC`,
    [personId]
  );

  res.status(200).json({ data: { ...rows[0], cases: caseLinks } });
}

/** POST /api/persons — no dedicated procedure; a plain insert into a
 * standalone entity table with no lifecycle logic to orchestrate. */
export async function createPerson(req: Request, res: Response): Promise<void> {
  const body = req.body as CreatePersonInput;
  const [result] = await pool.query<ResultSetHeader>(
    `INSERT INTO persons (first_name, last_name, date_of_birth, national_id_number, gender, phone_number, email, address)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
    [body.firstName, body.lastName, body.dateOfBirth ?? null, body.nationalIdNumber ?? null,
      body.gender ?? 'unknown', body.phoneNumber ?? null, body.email ?? null, body.address ?? null]
  );
  const [rows] = await pool.query<RowDataPacket[]>('SELECT * FROM persons WHERE person_id = ?', [result.insertId]);
  res.status(201).json({ data: rows[0] });
}

/** POST /api/cases/:caseId/persons — links a person to a case
 * (case_persons junction). Writes its own audit_logs row since no
 * trigger watches this table. */
export async function linkPersonToCase(req: Request, res: Response): Promise<void> {
  const caseId = Number(req.params.caseId);
  const actorUserId = req.user!.userId;
  const body = req.body as LinkPersonToCaseInput;

  await withActorConnection(actorUserId, async (conn) => {
    await conn.query(
      `INSERT INTO case_persons (case_id, person_id, person_role, notes) VALUES (?, ?, ?, ?)`,
      [caseId, body.personId, body.personRole, body.notes ?? null]
    );
    await conn.query(
      `INSERT INTO audit_logs (user_id, table_name, record_id, action_type, new_values)
       VALUES (?, 'case_persons', ?, 'INSERT', ?)`,
      [actorUserId, body.personId, JSON.stringify({ caseId, ...body })]
    );
  });

  res.status(201).json({ data: { caseId, ...body } });
}
