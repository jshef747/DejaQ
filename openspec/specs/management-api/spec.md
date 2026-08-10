## ADDED Requirements

### Requirement: Management endpoints enforce organization membership
The system SHALL authorize organization-scoped management actions against the caller's management auth context. A user actor SHALL only see, read, update, or delete resources for organizations where that user has a membership row. A system actor SHALL have full access to every organization.

When an authenticated user actor requests an existing org-scoped resource outside their memberships, the system SHALL return HTTP 403. Unknown resources SHALL return HTTP 404. Collection endpoints SHALL omit inaccessible organizations and resources from the response.

#### Scenario: User cannot access another org
- **WHEN** a user who belongs only to org `acme` calls `GET /admin/v1/departments?org=globex`
- **THEN** the system returns HTTP 403

#### Scenario: Collections omit inaccessible orgs
- **WHEN** a user belongs to `acme` but not `globex`
- **THEN** `GET /admin/v1/orgs` returns `acme`
- **THEN** the response does not include `globex`

#### Scenario: System actor sees all orgs
- **WHEN** the CLI calls the shared admin service with a system auth context
- **THEN** the service returns resources across all organizations

## MODIFIED Requirements

### Requirement: Admin endpoints are mounted under /admin/v1

The system SHALL expose all management endpoints under the `/admin/v1` URL prefix, separate from the gateway `/v1` namespace. Every endpoint SHALL return JSON with `Content-Type: application/json` and SHALL use standard HTTP status codes (`200`, `201`, `204`, `401`, `403`, `404`, `409`, `422`, `503`). Request parsing, schema, and query validation errors SHALL return HTTP 422.

#### Scenario: Admin namespace is reachable

- **WHEN** the FastAPI app is started with valid Supabase SDK configuration
- **THEN** `GET /admin/v1/orgs` with a valid Supabase bearer token returns HTTP 200 and a JSON array scoped to the caller's org memberships

#### Scenario: Gateway namespace is unaffected

- **WHEN** the admin router is mounted
- **THEN** `POST /v1/chat/completions` and `POST /v1/feedback` continue to authenticate via the existing org-key middleware

### Requirement: Whoami probe endpoint

The system SHALL expose `GET /admin/v1/whoami` returning HTTP 200 when the bearer token is a valid Supabase access JWT. The response SHALL include `{authorized: true, actor_type: "user", supabase_user_id: "<id>", email: "<email>", orgs: [{id, name, slug, created_at}]}` where `orgs` contains the organizations accessible to the caller. For a system context used outside HTTP routing, equivalent service-level identity helpers SHALL report system actor status and full access.

#### Scenario: Probe with valid token

- **WHEN** a client calls `GET /admin/v1/whoami` with a valid Supabase access JWT
- **THEN** the response is HTTP 200 with `authorized: true`
- **THEN** the response includes the caller's Supabase user id, email, and accessible org list

#### Scenario: Probe with unknown local membership

- **WHEN** a valid Supabase user with no org memberships calls `GET /admin/v1/whoami`
- **THEN** the response is HTTP 200 with `authorized: true`
- **THEN** the response includes an empty org list

#### Scenario: Probe response has stable identity fields

- **WHEN** a valid Supabase user calls `GET /admin/v1/whoami`
- **THEN** the response includes `actor_type`, `supabase_user_id`, `email`, and `orgs`
- **THEN** each org item includes `id`, `name`, `slug`, and `created_at`

### Requirement: Org management endpoints

The system SHALL expose org CRUD endpoints with one-to-one parity with `dejaq-admin org` subcommands, while HTTP requests are scoped to the authenticated user's organization memberships:
- `GET /admin/v1/orgs` — list organizations accessible to the caller as `[{id, name, slug, created_at}]`; system actors list all orgs.
- `POST /admin/v1/orgs` — create org from `{name}`; return HTTP 201 with the new org. Duplicate slug SHALL return HTTP 409. For a user actor, the creator SHALL automatically receive membership in the new org.
- `DELETE /admin/v1/orgs/{slug}` — delete an accessible org and cascade departments, API keys, LLM config, and memberships; return HTTP 200 with `{"deleted": true, "departments_removed": <int>}`. Unknown slug SHALL return HTTP 404. Existing but inaccessible slug SHALL return HTTP 403.

#### Scenario: List orgs

- **WHEN** an authorized user calls `GET /admin/v1/orgs`
- **THEN** the response is HTTP 200 with a JSON array of organizations the user belongs to

#### Scenario: System actor lists all orgs

- **WHEN** the CLI calls the org listing service as the system actor
- **THEN** every organization is returned

#### Scenario: Create org with duplicate name

- **WHEN** an authorized client posts a name whose derived slug already exists
- **THEN** the response is HTTP 409 with `{"detail": "Organization slug already exists"}`

#### Scenario: Create org grants membership to creator

- **WHEN** an authenticated user posts `{"name": "Acme Corp"}` to `POST /admin/v1/orgs`
- **THEN** the org is created
- **THEN** a user-org membership is created for that user and org in the same database transaction

#### Scenario: Delete unknown org

- **WHEN** an authorized client calls `DELETE /admin/v1/orgs/does-not-exist`
- **THEN** the response is HTTP 404

#### Scenario: Delete inaccessible org

- **WHEN** a user who does not belong to `globex` calls `DELETE /admin/v1/orgs/globex`
- **THEN** the response is HTTP 403

#### Scenario: Delete org cascades departments

- **WHEN** an authorized client deletes an accessible org with three departments
- **THEN** the response includes `"departments_removed": 3` and all three departments plus the org's API keys, LLM config row, and membership rows are gone from the DB

### Requirement: Department management endpoints

The system SHALL expose department CRUD endpoints with one-to-one parity with `dejaq-admin dept`, while HTTP requests are scoped to the authenticated user's organization memberships:
- `GET /admin/v1/departments?org=<slug>` — list departments; `org` query param optional. Without `org`, return departments only for accessible organizations. With `org`, return departments for that org only when it is accessible. Each item SHALL include `{id, org_slug, name, slug, cache_namespace, created_at}`.
- `POST /admin/v1/orgs/{org_slug}/departments` — create from `{name}` under an accessible org; HTTP 201 on success. Unknown org → HTTP 404. Existing but inaccessible org → HTTP 403. Duplicate dept slug under the same org → HTTP 409.
- `DELETE /admin/v1/orgs/{org_slug}/departments/{dept_slug}` — delete under an accessible org; HTTP 200 with `{"deleted": true, "cache_namespace": "<freed-ns>"}`. Unknown org or dept → HTTP 404. Existing but inaccessible org → HTTP 403.

#### Scenario: List departments scoped to an org

- **WHEN** an authorized user who belongs to `acme` calls `GET /admin/v1/departments?org=acme`
- **THEN** only departments belonging to org `acme` are returned

#### Scenario: List departments without org filter

- **WHEN** an authorized user calls `GET /admin/v1/departments`
- **THEN** departments across the user's accessible orgs are returned, each carrying its `org_slug`

#### Scenario: List departments for inaccessible org

- **WHEN** a user who does not belong to `globex` calls `GET /admin/v1/departments?org=globex`
- **THEN** the response is HTTP 403

#### Scenario: Create department under unknown org

- **WHEN** an authorized client posts to `/admin/v1/orgs/missing/departments`
- **THEN** the response is HTTP 404

#### Scenario: Create department under inaccessible org

- **WHEN** a user who does not belong to `globex` posts to `/admin/v1/orgs/globex/departments`
- **THEN** the response is HTTP 403

#### Scenario: Delete department returns freed namespace

- **WHEN** an authorized client deletes a department under an accessible org
- **THEN** the response includes the `cache_namespace` value the entry occupied

### Requirement: API key management endpoints

The system SHALL expose API-key endpoints with one-to-one parity with `dejaq-admin key`, while HTTP requests are scoped to the authenticated user's organization memberships:
- `GET /admin/v1/orgs/{org_slug}/keys` — list keys for an accessible org as `[{id, token_prefix, created_at, revoked_at}]`. The `token_prefix` SHALL be the first 12 chars followed by `...`; the full token SHALL NOT be returned. Unknown org → HTTP 404. Existing but inaccessible org → HTTP 403.
- `POST /admin/v1/orgs/{org_slug}/keys?force=<bool>` — generate a new key for an accessible org. Without `force`, an existing active key SHALL cause HTTP 409. With `force=true`, the existing active key SHALL be revoked first. The response (HTTP 201) SHALL include the full token (one-time visibility). Unknown org → HTTP 404. Existing but inaccessible org → HTTP 403.
- `DELETE /admin/v1/keys/{key_id}` — revoke by id when the key belongs to an accessible org. Already-revoked keys SHALL return HTTP 200 with `{"revoked": true, "already_revoked": true}`. Unknown id SHALL return HTTP 404. Existing key in an inaccessible org SHALL return HTTP 403.

#### Scenario: List keys masks token

- **WHEN** an authorized user calls `GET /admin/v1/orgs/acme/keys` for an accessible org
- **THEN** each entry contains `token_prefix` only and never the full secret

#### Scenario: List keys for inaccessible org

- **WHEN** a user who does not belong to `globex` calls `GET /admin/v1/orgs/globex/keys`
- **THEN** the response is HTTP 403

#### Scenario: Generate key without force when active key exists

- **WHEN** the accessible org already has an active key and the client posts without `force=true`
- **THEN** the response is HTTP 409 with a message recommending `?force=true`

#### Scenario: Generate key with force rotates the key

- **WHEN** the client posts with `?force=true` for an accessible org and an active key exists
- **THEN** the existing key is revoked, a new key is created, and the response (HTTP 201) returns the new full token exactly once

#### Scenario: Revoke unknown key id

- **WHEN** an authorized client calls `DELETE /admin/v1/keys/99999` on a non-existent id
- **THEN** the response is HTTP 404

#### Scenario: Revoke key for inaccessible org

- **WHEN** a user who does not belong to a key's org calls `DELETE /admin/v1/keys/{key_id}` for that key
- **THEN** the response is HTTP 403

### Requirement: Stats endpoints support optional date range filtering

The system SHALL expose stats aggregation endpoints scoped to the authenticated user's organization memberships:
- `GET /admin/v1/stats/orgs?from=<ISO-8601 date>&to=<ISO-8601 date>` — totals per accessible org plus a grand total for accessible orgs only.
- `GET /admin/v1/stats/orgs/{org_slug}/departments?from=...&to=...` — totals per department for the given org when it is accessible.

Both endpoints SHALL accept optional `from` and `to` query parameters as ISO-8601 dates (`YYYY-MM-DD`), interpreted as UTC midnight inclusive (`from`) and UTC midnight exclusive (`to`). The service SHALL compare using the same UTC ISO timestamp representation stored in the request log: Python `datetime(..., tzinfo=timezone.utc).isoformat()` strings with `+00:00` offsets, not `Z` suffixes. Invalid date formats and `from > to` SHALL return HTTP 422.

`GET /admin/v1/stats/orgs` SHALL return `{items: OrgStats[], total: StatsMetrics}`. `OrgStats` SHALL include `{org, org_name, requests, hits, misses, hit_rate, avg_latency_ms, est_tokens_saved, easy_count, hard_count, models_used}`. `StatsMetrics` SHALL include the aggregate metric fields without identity fields and SHALL aggregate only accessible org rows for user actors.

`GET /admin/v1/stats/orgs/{org_slug}/departments` SHALL return `{org, items: DepartmentStats[], total: StatsMetrics}`. `DepartmentStats` SHALL include `{org, department, department_name, requests, hits, misses, hit_rate, avg_latency_ms, est_tokens_saved, easy_count, hard_count, models_used}`. Unknown org SHALL return HTTP 404. Existing but inaccessible org SHALL return HTTP 403.

#### Scenario: Per-org stats with no date filter

- **WHEN** an authorized user calls `GET /admin/v1/stats/orgs`
- **THEN** the response is HTTP 200 with one row per accessible org plus a `total` field aggregating accessible rows

#### Scenario: Per-department stats for a single org

- **WHEN** an authorized user calls `GET /admin/v1/stats/orgs/acme/departments` for an accessible org
- **THEN** the response contains one row per department under `acme`

#### Scenario: Stats omit inaccessible orgs

- **WHEN** a user belongs to `acme` but not `globex`
- **THEN** `GET /admin/v1/stats/orgs` includes `acme` stats
- **THEN** the response does not include `globex` stats

#### Scenario: Stats empty for user with no memberships

- **WHEN** a user with no org memberships calls `GET /admin/v1/stats/orgs`
- **THEN** the response is HTTP 200 with an empty `items` array
- **THEN** the `total` field contains zero-valued metrics

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

#### Scenario: Stats for inaccessible org

- **WHEN** a user who does not belong to `globex` calls `GET /admin/v1/stats/orgs/globex/departments`
- **THEN** the response is HTTP 403

### Requirement: Org LLM config endpoints

The system SHALL expose org LLM configuration endpoints scoped to the authenticated user's organization memberships:
- `GET /admin/v1/orgs/{org_slug}/llm-config` — return routing configuration for an accessible org. Unknown org SHALL return HTTP 404. Existing but inaccessible org SHALL return HTTP 403.
- `PUT /admin/v1/orgs/{org_slug}/llm-config` — update routing configuration for an accessible org. Unknown org SHALL return HTTP 404. Existing but inaccessible org SHALL return HTTP 403. Validation errors SHALL return HTTP 422.

#### Scenario: Read LLM config for accessible org

- **WHEN** an authorized user calls `GET /admin/v1/orgs/acme/llm-config` for an accessible org
- **THEN** the response is HTTP 200 with the org's LLM routing configuration

#### Scenario: Update LLM config for inaccessible org

- **WHEN** a user who does not belong to `globex` calls `PUT /admin/v1/orgs/globex/llm-config`
- **THEN** the response is HTTP 403

#### Scenario: LLM config for unknown org

- **WHEN** an authorized user calls `GET /admin/v1/orgs/missing/llm-config`
- **THEN** the response is HTTP 404

### Requirement: Feedback management endpoints

The system SHALL expose feedback management endpoints scoped to the authenticated user's organization memberships:
- `GET /admin/v1/feedback` — list feedback entries only for organizations accessible to the caller; system actors list all feedback.
- `POST /admin/v1/feedback` — create or record management feedback only for an accessible org when an org is specified by request body or associated response metadata. Unknown org or response metadata SHALL return HTTP 404. Existing but inaccessible org SHALL return HTTP 403. Validation errors SHALL return HTTP 422.

Collection responses SHALL include only resources from accessible organizations for user actors. System actors SHALL retain full access.

#### Scenario: List feedback omits inaccessible orgs

- **WHEN** a user belongs to `acme` but not `globex`
- **THEN** `GET /admin/v1/feedback` includes feedback associated with `acme`
- **THEN** the response does not include feedback associated with `globex`

#### Scenario: Create feedback for inaccessible org

- **WHEN** a user who does not belong to `globex` posts feedback associated with `globex`
- **THEN** the response is HTTP 403

#### Scenario: System actor lists all feedback

- **WHEN** the CLI or trusted service path lists feedback with a system auth context
- **THEN** feedback across all organizations is returned

## REMOVED Requirements

### Requirement: Admin endpoints require a shared admin bearer token
**Reason**: Management API authorization is moving from a single shared secret to per-user Supabase authentication and local user-org memberships.

**Migration**: Configure the official Supabase Python SDK and send Supabase access JWTs to `/admin/v1/*`. Use the system actor path for CLI commands instead of `DEJAQ_ADMIN_TOKEN`.

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
**Reason**: `DEJAQ_ADMIN_TOKEN` is no longer the management API authentication mechanism.

**Migration**: Configure Supabase SDK values instead. Missing Supabase SDK configuration disables HTTP management auth with HTTP 503.

#### Scenario: DEJAQ_ADMIN_TOKEN is unset or blank

- **WHEN** the server starts with `DEJAQ_ADMIN_TOKEN` unset, empty, or whitespace-only and a client calls `GET /admin/v1/orgs` with any bearer token
- **THEN** the system returns HTTP 503 with `{"detail": "Admin API disabled: DEJAQ_ADMIN_TOKEN not configured"}`

#### Scenario: Startup warning is emitted

- **WHEN** the server starts with `DEJAQ_ADMIN_TOKEN` unset
- **THEN** a warning is logged via `dejaq.admin` indicating the admin API is disabled
