# FORGE-X REST API v1 (FORGE-X 2.0 Phase 10)

A **read-only** JSON API over the same data as the website. The full, always-current reference is generated from the code:

* **Developer API** in the sidebar (`/developers`): human-readable.
* **`/api/v1/openapi.json`**: OpenAPI 3.0, for tools such as Postman or code generators.

## Authentication

| Method | Use |
|---|---|
| Browser session | Already signed in on the website: the API works in the same browser |
| Personal token | Scripts: `Authorization: Bearer fx_…` |

**Tokens** are created under **My account → API tokens**.
* A token is shown **once**. FORGE-X stores only its SHA-256.
* Tokens expire after 7, 30 or 90 days. Each user can have up to 5 active tokens.
* A token can be revoked at any time. Deactivating the account stops all its tokens immediately.
* A token sees **exactly what its owner sees** on the website: investigators only their assigned cases.

## Endpoints

| Path | Returns |
|---|---|
| `/me` | Who you are authenticated as, and your scope |
| `/cases`, `/cases/{reference}` | Cases (same filters as the case list); one case with investigators and related codes |
| `/evidence`, `/evidence/{code}` | Evidence (Evidence Vault filters); one item with integrity and stored-file details. **File content is never returned** |
| `/evidence/{code}/custody` | That item's chain of custody |
| `/chain-of-custody` | Custody entries and integrity checks (custody log filters) |
| `/examinations`, `/examinations/{code}` | Examinations; one with its evidence and artifacts |
| `/reports`, `/reports/{code}` | Reports; one with version history and cited examinations (the PDF stays on the website) |
| `/indicators` | Recorded indicators: matches from each item's latest completed YARA scan, artifact SHA-256 values, network-indicator artifacts. Nothing inferred |
| `/openapi.json` | The OpenAPI document |

## Conventions

* **Lists:** `?page=1&per_page=25` (at most 100). The response is `{"data": [...], "page", "per_page", "total", "pages"}`.
* **One record:** `{"data": {...}}`.
* **Times:** ISO 8601 with the lab offset, e.g. `2026-10-09T19:39:00+05:30` (decision U8). Dates are `YYYY-MM-DD`.
* **Errors** are JSON `{"status", "error", "message"}`:

| Status | Meaning |
|---|---|
| 401 | Not signed in, or the token is unknown, expired or revoked (`WWW-Authenticate: Bearer`) |
| 403 | The account must change its password on the website first |
| 404 | Doesn't exist, **or isn't visible to you**. The API never says which |
| 405 | Not GET: v1 is read-only |
| 429 | Rate limit; wait for `Retry-After` seconds |

## Security

* **Fixed field lists.** Every resource is built from a fixed list of fields, so internal values (storage object IDs, password and token hashes, settings) can't appear. A test checks the lists.
* **Rate limits:** `API_RATE_LIMIT_PER_MINUTE` (120 per user) and `API_FAILED_AUTH_PER_MINUTE` (20 failed token attempts per address, after which the address waits). The counters are per server process.
* **Audited:** token creation and revocation, and failed token attempts. Failed attempts record only the token's public prefix, never the secret.
* **Why read-only:** changes stay in the web workflows, which enforce custody rules, typed confirmations and independent review. Writing over the API would need those rules re-implemented a second time.

## Example

```cmd
curl -H "Authorization: Bearer fx_…" "http://127.0.0.1:5000/api/v1/evidence?case=FX-2026-0002&integrity=Failed"
```
