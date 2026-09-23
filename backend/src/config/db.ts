import mysql, { Pool, PoolConnection, ResultSetHeader, RowDataPacket } from 'mysql2/promise';
import { env } from './env';

/**
 * Single connection pool for the whole process. Points at the SAME
 * forge_x database built in Steps 1-5 (01_create_database.sql through
 * 09_seed_data.sql) — this backend never creates or migrates a second
 * database of its own.
 *
 * All queries are parameterized ("?" placeholders, values passed
 * separately) everywhere in this codebase. This is the backend's SQL
 * injection defense: user input is never concatenated into a SQL
 * string.
 */
export const pool: Pool = mysql.createPool({
  host: env.db.host,
  port: env.db.port,
  user: env.db.user,
  password: env.db.password,
  database: env.db.database,
  connectionLimit: env.db.connectionLimit,
  waitForConnections: true,
  namedPlaceholders: false,
  dateStrings: false,
  charset: 'UTF8MB4_GENERAL_CI',
});

/** Plain pool query — fine for reads and single-statement writes that
 * don't need to attribute an acting user to a trigger (e.g. SELECTs). */
export async function query<T extends RowDataPacket[] | ResultSetHeader>(
  sql: string,
  params: unknown[] = []
): Promise<T> {
  const [rows] = await pool.query<T>(sql, params);
  return rows;
}

/**
 * FORGE-X's triggers (08_triggers.sql) read a session variable,
 * @forgex_actor_id, to attribute automatically-generated audit_logs /
 * chain_of_custody rows to the application user who caused them
 * (rather than the shared DB service account). A MySQL session
 * variable is tied to one physical connection, so this helper:
 *   1. checks out a single dedicated connection from the pool,
 *   2. sets @forgex_actor_id on it,
 *   3. runs the caller's callback using THAT SAME connection for every
 *      statement in the operation (so the SET actually applies),
 *   4. always resets the session variable and releases the connection
 *      back to the pool afterwards, even if the callback throws.
 *
 * Every write endpoint that should be attributed to the logged-in user
 * (which is most of them) goes through this helper instead of the
 * plain pool.
 */
export async function withActorConnection<T>(
  actorUserId: number,
  fn: (conn: PoolConnection) => Promise<T>
): Promise<T> {
  const conn = await pool.getConnection();
  try {
    await conn.query('SET @forgex_actor_id = ?', [actorUserId]);
    const result = await fn(conn);
    return result;
  } finally {
    try {
      await conn.query('SET @forgex_actor_id = NULL');
    } finally {
      conn.release();
    }
  }
}

export type { RowDataPacket, ResultSetHeader, PoolConnection };
