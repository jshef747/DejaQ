## ADDED Requirements

### Requirement: Admin endpoints are mounted under /admin/v1

The system SHALL expose all management endpoints under the `/admin/v1` URL prefix, separate from the gateway `/v1` namespace. Every endpoint SHALL return JSON with `Content-Type: application/json` and SHALL use standard HTTP status codes (`200`, `201`, `204`, `401`, `404`, `409`, `422`, `503`). Request parsing, schema, and query validation errors SHALL return HTTP 422.

#### Scenario: Admin namespace is reachable

- **WHEN** the FastAPI app is started with a valid `DEJAQ_ADMIN_TOKEN`
- **THEN** `GET /admin/v1/orgs` with a valid bearer token returns HTTP 200 and a JSON array

#### Scenario: Gateway namespace is unaffected

- **WHEN** the admin router is mounted
- **THEN** `POST /v1/chat/completions` and `POST /v1/feedback` continue to authenticate via the existing org-key middleware

### Requirement: Admin endpoints require a shared admin bearer token

The system SHALL validate every request to `/admin/v1/*` against the value of the `DEJAQ_ADMIN_TOKEN` environment variable, supplied as `Authorization: Bearer <token>`. Requests with a missing, malformed, or non-matching `Authorization` header SHALL receive HTTP 401. Validation SHALL use a constant-time string comparison.

The system SHALL keep `/admin/v1/*` isolated from org API-key authentication. Requests under `/admin/v1/*` SHALL bypass org API-key middleware before that middleware parses or logs `Authorization`, SHALL NOT resolve org/dept state from the bearer token, and SHALL NOT log the admin bearer token as an unknown org API key.

#### Scenario: Valid admin token is accepted

- **WHEN** a client calls `GET /admin/v1/orgs` with `Authorization: Bearer <DEJAQ_ADMIN_TOKEN>`
- **THEN** the request is authorized and the handler runs

#### Scenario: Missing Authorization header

- **WHEN** a client calls any `/admin/v1/*` endpoint without an `Authorization` header
- **THEN** the system returns HTTP 401 with `{"detail": "Admin token required"}`

#### Scenario: Wrong admin token

- **WHEN** a client calls any `/admin/v1/*` endpoint with `Authorization: Bearer wrong`
- **THEN** the system returns HTTP 401 with `{"detail": "Invalid admin token"}`

#### Scenario: Admin token is not processed as an org API key

- **WHEN** a client calls `/admin/v1/whoami` with a valid admin bearer token
- **THEN** the org API-key middleware is not invoked for token lookup and no unknown API-key warning is logged for that token

### Requirement: Admin router fails closed when no admin token is configured

The system SHALL refuse all requests to `/admin/v1/*` with HTTP 503 when `DEJAQ_ADMIN_TOKEN` is unset, empty, or whitespace-only, regardless of the `Authorization` header. The system SHALL log a clear warning at startup when the variable is unset.

#### Scenario: DEJAQ_ADMIN_TOKEN is unset or blank

- **WHEN** the server starts with `DEJAQ_ADMIN_TOKEN` unset, empty, or whitespace-only and a client calls `GET /admin/v1/orgs` with any bearer token
- **THEN** the system returns HTTP 503 with `{"detail": "Admin API disabled: DEJAQ_ADMIN_TOKEN not configured"}`

#### Scenario: Startup warning is emitted

- **WHEN** the server starts with `DEJAQ_ADMIN_TOKEN` unset
- **THEN** a warning is logged via `dejaq.admin` indicating the admin API is disabled

### Requirement: Whoami probe endpoint

The system SHALL expose `GET /admin/v1/whoami` returning HTTP 200 with `{"authorized": true}` when the bearer token matches `DEJAQ_ADMIN_TOKEN`. This endpoint SHALL follow the same auth rules as all other admin endpoints.

#### Scenario: Probe with valid token

- **WHEN** a client calls `GET /admin/v1/whoami` with the correct admin bearer token
- **THEN** the response is HTTP 200 with `{"authorized": true}`

### Requirement: Org management endpoints

The system SHALL expose org CRUD endpoints with one-to-one parity with `dejaq-admin org` subcommands:
- `GET /admin/v1/orgs` — list all orgs as `[{id, name, slug, created_at}]`.
- `POST /admin/v1/orgs` — create org from `{name}`; return HTTP 201 with the new org. Duplicate slug SHALL return HTTP 409.
- `DELETE /admin/v1/orgs/{slug}` — delete org and cascade departments, API keys, and LLM config; return HTTP 200 with `{"deleted": true, "departments_removed": <int>}`. Unknown slug SHALL return HTTP 404.

#### Scenario: List orgs

- **WHEN** an authorized client calls `GET /admin/v1/orgs`
- **THEN** the response is HTTP 200 with a JSON array of all orgs

#### Scenario: Create org with duplicate name

- **WHEN** an authorized client posts a name whose derived slug already exists
- **THEN** the response is HTTP 409 with `{"detail": "Organization slug already exists"}`

#### Scenario: Delete unknown org

- **WHEN** an authorized client calls `DELETE /admin/v1/orgs/does-not-exist`
- **THEN** the response is HTTP 404

#### Scenario: Delete org cascades departments

- **WHEN** an authorized client deletes an org with three departments
- **THEN** the response includes `"departments_removed": 3` and all three departments plus the org's API keys and LLM config row are gone from the DB

### Requirement: Department management endpoints

The system SHALL expose department CRUD endpoints with one-to-one parity with `dejaq-admin dept`:
- `GET /admin/v1/departments?org=<slug>` — list departments; `org` query param optional. Each item SHALL include `{id, org_slug, name, slug, cache_namespace, created_at}`.
- `POST /admin/v1/orgs/{org_slug}/departments` — create from `{name}`; HTTP 201 on success. Unknown org → HTTP 404. Duplicate dept slug under the same org → HTTP 409.
- `DELETE /admin/v1/orgs/{org_slug}/departments/{dept_slug}` — delete; HTTP 200 with `{"deleted": true, "cache_namespace": "<freed-ns>"}`. Unknown org or dept → HTTP 404.

#### Scenario: List departments scoped to an org

- **WHEN** an authorized client calls `GET /admin/v1/departments?org=acme`
- **THEN** only departments belonging to org `acme` are returned

#### Scenario: List departments without org filter

- **WHEN** an authorized client calls `GET /admin/v1/departments`
- **THEN** every department across all orgs is returned, each carrying its `org_slug`

#### Scenario: Create department under unknown org

- **WHEN** an authorized client posts to `/admin/v1/orgs/missing/departments`
- **THEN** the response is HTTP 404

#### Scenario: Delete department returns freed namespace

- **WHEN** an authorized client deletes a department
- **THEN** the response includes the `cache_namespace` value the entry occupied

### Requirement: API key management endpoints

The system SHALL expose API-key endpoints with one-to-one parity with `dejaq-admin key`:
- `GET /admin/v1/orgs/{org_slug}/keys` — list keys for the org as `[{id, token_prefix, created_at, revoked_at}]`. The `token_prefix` SHALL be the first 12 chars followed by `...`; the full token SHALL NOT be returned.
- `POST /admin/v1/orgs/{org_slug}/keys?force=<bool>` — generate a new key. Without `force`, an existing active key SHALL cause HTTP 409. With `force=true`, the existing active key SHALL be revoked first. The response (HTTP 201) SHALL include the full token (one-time visibility).
- `DELETE /admin/v1/keys/{key_id}` — revoke by id. Already-revoked keys SHALL return HTTP 200 with `{"revoked": true, "already_revoked": true}`. Unknown id SHALL return HTTP 404.

#### Scenario: List keys masks token

- **WHEN** an authorized client calls `GET /admin/v1/orgs/acme/keys`
- **THEN** each entry contains `token_prefix` only and never the full secret

#### Scenario: Generate key without force when active key exists

- **WHEN** the org already has an active key and the client posts without `force=true`
- **THEN** the response is HTTP 409 with a message recommending `?force=true`

#### Scenario: Generate key with force rotates the key

- **WHEN** the client posts with `?force=true` and an active key exists
- **THEN** the existing key is revoked, a new key is created, and the response (HTTP 201) returns the new full token exactly once

#### Scenario: Revoke unknown key id

- **WHEN** an authorized client calls `DELETE /admin/v1/keys/99999` on a non-existent id
- **THEN** the response is HTTP 404

### Requirement: Stats endpoints support optional date range filtering

The system SHALL expose stats aggregation endpoints:
- `GET /admin/v1/stats/orgs?from=<ISO-8601 date>&to=<ISO-8601 date>` — totals per org plus a grand total.
- `GET /admin/v1/stats/orgs/{org_slug}/departments?from=...&to=...` — totals per department for the given org.

Both endpoints SHALL accept optional `from` and `to` query parameters as ISO-8601 dates (`YYYY-MM-DD`), interpreted as UTC midnight inclusive (`from`) and UTC midnight exclusive (`to`). The service SHALL compare using the same UTC ISO timestamp representation stored in the request log: Python `datetime(..., tzinfo=timezone.utc).isoformat()` strings with `+00:00` offsets, not `Z` suffixes. Invalid date formats and `from > to` SHALL return HTTP 422.

`GET /admin/v1/stats/orgs` SHALL return `{items: OrgStats[], total: StatsMetrics}`. `OrgStats` SHALL include `{org, org_name, requests, hits, misses, hit_rate, avg_latency_ms, est_tokens_saved, easy_count, hard_count, models_used}`. `StatsMetrics` SHALL include the aggregate metric fields without identity fields.

`GET /admin/v1/stats/orgs/{org_slug}/departments` SHALL return `{org, items: DepartmentStats[], total: StatsMetrics}`. `DepartmentStats` SHALL include `{org, department, department_name, requests, hits, misses, hit_rate, avg_latency_ms, est_tokens_saved, easy_count, hard_count, models_used}`.

#### Scenario: Per-org stats with no date filter

- **WHEN** an authorized client calls `GET /admin/v1/stats/orgs`
- **THEN** the response is HTTP 200 with one row per org plus a `total` field aggregating all rows

#### Scenario: Per-department stats for a single org

- **WHEN** an authorized client calls `GET /admin/v1/stats/orgs/acme/departments`
- **THEN** the response contains one row per department under `acme`

#### Scenario: Date range filter is honored

- **WHEN** an authorized client calls `GET /admin/v1/stats/orgs?from=2026-04-01&to=2026-04-15`
- **THEN** only requests with `ts` in `[2026-04-01T00:00:00+00:00, 2026-04-15T00:00:00+00:00)` are aggregated

#### Scenario: Invalid date returns 422

- **WHEN** an authorized client passes `?from=04/01/2026`
- **THEN** the response is HTTP 422

#### Scenario: Reversed date range returns 422

- **WHEN** an authorized client passes `?from=2026-04-15&to=2026-04-01`
- **THEN** the response is HTTP 422

#### Scenario: Stats for unknown org

- **WHEN** an authorized client calls `GET /admin/v1/stats/orgs/missing/departments`
- **THEN** the response is HTTP 404
