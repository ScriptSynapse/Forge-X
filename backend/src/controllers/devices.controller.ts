import { Request, Response } from 'express';
import { pool, withActorConnection, RowDataPacket, ResultSetHeader } from '../config/db';
import { ApiError } from '../utils/ApiError';
import { parsePagination, paginatedResponse } from '../utils/pagination';
import { CreateDeviceInput, UpdateDeviceInput } from '../validators/devices.validators';

const DEVICE_SELECT = `
  d.device_id, d.case_id, dt.type_name AS device_type, d.owner_person_id, d.serial_number,
  d.make, d.model, d.imei_number, d.storage_capacity_gb, d.seized_at,
  d.seized_location_id, d.current_location_id, d.device_status
`;

/** GET /api/devices — uses idx_devices_serial_number / idx_devices_imei_number
 * (04_indexes.sql) for the lookup paths. */
export async function listDevices(req: Request, res: Response): Promise<void> {
  const pagination = parsePagination(req.query as Record<string, unknown>);
  const { caseId, serialNumber, imei } = req.query as { caseId?: string; serialNumber?: string; imei?: string };

  const where: string[] = [];
  const params: unknown[] = [];
  if (caseId) { where.push('d.case_id = ?'); params.push(Number(caseId)); }
  if (serialNumber) { where.push('d.serial_number = ?'); params.push(serialNumber); }
  if (imei) { where.push('d.imei_number = ?'); params.push(imei); }
  const whereClause = where.length ? `WHERE ${where.join(' AND ')}` : '';

  const [countRows] = await pool.query<RowDataPacket[]>(`SELECT COUNT(*) AS total FROM devices d ${whereClause}`, params);
  const [rows] = await pool.query<RowDataPacket[]>(
    `SELECT ${DEVICE_SELECT} FROM devices d JOIN device_types dt ON d.device_type_id = dt.device_type_id
      ${whereClause} ORDER BY d.device_id LIMIT ? OFFSET ?`,
    [...params, pagination.pageSize, pagination.offset]
  );

  res.status(200).json(paginatedResponse(rows, countRows[0]?.total ?? 0, pagination));
}

/** GET /api/devices/:id — includes the evidence items sourced from this device. */
export async function getDevice(req: Request, res: Response): Promise<void> {
  const deviceId = Number(req.params.id);
  const [rows] = await pool.query<RowDataPacket[]>(
    `SELECT ${DEVICE_SELECT} FROM devices d JOIN device_types dt ON d.device_type_id = dt.device_type_id
      WHERE d.device_id = ?`,
    [deviceId]
  );
  if (!rows[0]) throw ApiError.notFound(`Device ${deviceId} not found.`);

  const [evidenceRows] = await pool.query<RowDataPacket[]>(
    `SELECT evidence_id, evidence_number, integrity_status FROM evidence WHERE device_id = ?`,
    [deviceId]
  );

  res.status(200).json({ data: { ...rows[0], evidenceItems: evidenceRows } });
}

/** POST /api/devices — plain insert; devices have no orchestration
 * procedure since intake here is a single-table write (evidence
 * extraction FROM a device is the workflow that needs a procedure,
 * and that is sp_register_evidence). */
export async function createDevice(req: Request, res: Response): Promise<void> {
  const body = req.body as CreateDeviceInput;

  if (!(await caseExists(body.caseId))) throw ApiError.badRequest('caseId does not exist.');

  const [result] = await pool.query<ResultSetHeader>(
    `INSERT INTO devices (case_id, device_type_id, owner_person_id, serial_number, make, model,
                           imei_number, storage_capacity_gb, seized_at, seized_location_id, current_location_id)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, NOW(), ?, ?)`,
    [body.caseId, body.deviceTypeId, body.ownerPersonId ?? null, body.serialNumber ?? null,
      body.make ?? null, body.model ?? null, body.imeiNumber ?? null, body.storageCapacityGb ?? null,
      body.seizedLocationId ?? null, body.seizedLocationId ?? null]
  );

  const [rows] = await pool.query<RowDataPacket[]>(
    `SELECT ${DEVICE_SELECT} FROM devices d JOIN device_types dt ON d.device_type_id = dt.device_type_id WHERE d.device_id = ?`,
    [result.insertId]
  );
  res.status(201).json({ data: rows[0] });
}

/** PUT /api/devices/:id — status/location/owner updates. */
export async function updateDevice(req: Request, res: Response): Promise<void> {
  const deviceId = Number(req.params.id);
  const actorUserId = req.user!.userId;
  const body = req.body as UpdateDeviceInput;

  await withActorConnection(actorUserId, async (conn) => {
    const [existing] = await conn.query<RowDataPacket[]>('SELECT device_id FROM devices WHERE device_id = ? FOR UPDATE', [deviceId]);
    if (!existing[0]) throw ApiError.notFound(`Device ${deviceId} not found.`);

    const fields: string[] = [];
    const values: unknown[] = [];
    if (body.deviceStatus !== undefined) { fields.push('device_status = ?'); values.push(body.deviceStatus); }
    if (body.currentLocationId !== undefined) { fields.push('current_location_id = ?'); values.push(body.currentLocationId); }
    if (body.ownerPersonId !== undefined) { fields.push('owner_person_id = ?'); values.push(body.ownerPersonId); }

    await conn.query(`UPDATE devices SET ${fields.join(', ')} WHERE device_id = ?`, [...values, deviceId]);
    await conn.query(
      `INSERT INTO audit_logs (user_id, table_name, record_id, action_type, new_values) VALUES (?, 'devices', ?, 'UPDATE', ?)`,
      [actorUserId, deviceId, JSON.stringify(body)]
    );
  });

  const [rows] = await pool.query<RowDataPacket[]>(
    `SELECT ${DEVICE_SELECT} FROM devices d JOIN device_types dt ON d.device_type_id = dt.device_type_id WHERE d.device_id = ?`,
    [deviceId]
  );
  res.status(200).json({ data: rows[0] });
}

async function caseExists(caseId: number): Promise<boolean> {
  const [rows] = await pool.query<RowDataPacket[]>('SELECT 1 FROM cases WHERE case_id = ?', [caseId]);
  return rows.length > 0;
}
