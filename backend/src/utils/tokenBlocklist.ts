/**
 * JWT logout support.
 *
 * JWTs are stateless by design, so "logging out" a still-valid,
 * unexpired token requires the server to remember that it was
 * explicitly revoked. Every issued token carries a unique `jti`
 * (JWT ID) claim; POST /api/auth/logout adds the caller's own jti to
 * this store, and authenticate() (middleware/authenticate.ts) rejects
 * any token whose jti is present here, even though the token's
 * signature and expiry are otherwise still valid.
 *
 * PRODUCTION NOTE (documented deliberately, not glossed over): this
 * implementation is an in-memory Set, scoped to a single Node process.
 * It is correct and sufficient for this project (one server instance,
 * a demo/class deployment) but does NOT survive a server restart and
 * does NOT work across multiple server instances behind a load
 * balancer. A real multi-instance deployment would back this with a
 * shared store with per-key TTL support (Redis's `SET key val EX ttl`
 * is the standard choice), keyed the same way, so every instance sees
 * the same revocation immediately. The interface below is intentionally
 * small enough that swapping the in-memory Map for a Redis client later
 * touches only this one file, not any call site.
 */

interface RevokedEntry {
  expiresAtEpochSeconds: number;
}

const revoked = new Map<string, RevokedEntry>();

/** Revoke a token's jti until its own natural expiry (no need to keep
 * it in memory any longer than the token itself would have been valid
 * for). */
export function revokeToken(jti: string, expiresAtEpochSeconds: number): void {
  revoked.set(jti, { expiresAtEpochSeconds });
  sweepExpired();
}

export function isRevoked(jti: string): boolean {
  return revoked.has(jti);
}

/** Drop entries whose underlying token would have expired anyway --
 * keeps this Set from growing without bound over a long-running
 * process. Called opportunistically on every revoke rather than on a
 * timer, which is sufficient at this project's scale. */
function sweepExpired(): void {
  const now = Math.floor(Date.now() / 1000);
  for (const [jti, entry] of revoked) {
    if (entry.expiresAtEpochSeconds <= now) {
      revoked.delete(jti);
    }
  }
}
