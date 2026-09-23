/**
 * DEV/DEMO ONLY. Sets every seeded user's password to a single known
 * demo password so the API (and anyone grading it) can log in without
 * needing to know the placeholder hash baked into 09_seed_data.sql.
 * NEVER run this against anything but a local/demo database.
 */
const bcrypt = require('bcryptjs');
const mysql = require('mysql2/promise');
require('dotenv').config({ path: require('path').resolve(__dirname, '../.env') });

const DEMO_PASSWORD = 'ForgeX@Demo2026';

async function main() {
  const conn = await mysql.createConnection({
    host: process.env.DB_HOST,
    port: Number(process.env.DB_PORT),
    user: process.env.DB_USER,
    password: process.env.DB_PASSWORD,
    database: process.env.DB_NAME,
  });

  const hash = await bcrypt.hash(DEMO_PASSWORD, Number(process.env.BCRYPT_SALT_ROUNDS || 12));
  const [result] = await conn.query('UPDATE users SET password_hash = ?', [hash]);
  console.log(`Updated ${result.affectedRows} users' password_hash.`);
  console.log(`Demo password for every seeded user: ${DEMO_PASSWORD}`);
  console.log(`Example usernames: asharma, rverma, pnair, kiyer, mjoshi, areddy, dmenon, srao, nkulkarni, vsingh`);
  await conn.end();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
