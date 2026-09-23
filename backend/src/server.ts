import { createApp } from './app';
import { env } from './config/env';
import { pool } from './config/db';

async function main(): Promise<void> {
  // Fail fast and loud if the database isn't reachable at startup,
  // rather than accepting requests that will all 500.
  try {
    const conn = await pool.getConnection();
    await conn.query('SELECT 1');
    conn.release();
    // eslint-disable-next-line no-console
    console.log(`Connected to MySQL database "${env.db.database}" at ${env.db.host}:${env.db.port}.`);
  } catch (err) {
    // eslint-disable-next-line no-console
    console.error('FATAL: could not connect to the forge_x database. Check your .env DB_* settings.', err);
    process.exit(1);
  }

  const app = createApp();
  app.listen(env.port, () => {
    // eslint-disable-next-line no-console
    console.log(`FORGE-X backend listening on http://localhost:${env.port} (${env.nodeEnv})`);
  });
}

main();
