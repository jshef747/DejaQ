> **Endpoint inventory lives elsewhere.** This spec states behavioral requirements for the management surface; it is deliberately not a route list, and endpoints added later are not enumerated here. The authoritative, complete inventory of `/admin/v1/*` endpoints is the "Endpoints" section of [CLAUDE.md](../../../CLAUDE.md). Per-capability endpoint contracts belong to that capability's own spec - for example `openspec/specs/workspace-llm-config/spec.md` owns `GET|PUT /admin/v1/workspaces/{slug}/llm-config`, the pipeline-role model overrides, and their validation against the installed-model catalog.

## ADDED Requirements

### Requirement: Management endpoints have a single dev-admin caller
The system SHALL serve every management action from one unauthenticated dev-admin context with full access to every workspace. There is no per-caller scoping: the surface is protected by loopback binding (`AdminLoopbackMiddleware`), not by a credential or a membership model, so no management endpoint SHALL deny a request on authorization grounds. Unknown resources SHALL return HTTP 404. Collection endpoints SHALL return every resource.

#### Scenario: Every workspace is reachable
- **WHEN** a client calls `GET /admin/v1/departments?workspace=globex`
- **THEN** the system returns the departments of `globex`, whatever the caller

#### Scenario: Collections list everything
- **WHEN** a client calls `GET /admin/v1/workspaces`
- **THEN** the response includes every workspace

#### Scenario: CLI and HTTP see the same data
- **WHEN** the CLI calls the shared admin service
- **THEN** the service returns resources across all workspaces, identical to the HTTP surface

## MODIFIED Requirements

### Requirement: Admin endpoints are mounted under /admin/v1

The system SHALL expose all management endpoints under the `/admin/v1` URL prefix, separate from the gateway `/v1` namespace. Every endpoint SHALL return JSON with `Content-Type: application/json` and SHALL use standard HTTP status codes (`200`, `201`, `204`, `404`, `409`, `422`). Request parsing, schema, and query validation errors SHALL return HTTP 422.

#### Scenario: Admin namespace is reachable

- **WHEN** the FastAPI app is started
- **THEN** `GET /admin/v1/workspaces` returns HTTP 200 and a JSON array of every workspace, via the unauthenticated dev-admin context

#### Scenario: Gateway namespace is unaffected

- **WHEN** the admin router is mounted
- **THEN** `POST /v1/chat/completions` and `POST /v1/feedback` continue to authenticate via the existing workspace-key middleware

### Requirement: Whoami probe endpoint

The system SHALL expose `GET /admin/v1/whoami` returning HTTP 200 for the unauthenticated dev-admin context. The response SHALL include `{authorized: true, actor_type: "system", email: "<email>", workspaces: []}`. The `workspaces` list is always empty: the dev-admin context carries no per-caller workspace list, because its access is unconditional and implied by `actor_type: "system"`. The field is retained for response-shape stability.

#### Scenario: Probe returns the dev-admin context

- **WHEN** a client calls `GET /admin/v1/whoami`
- **THEN** the response is HTTP 200 with `authorized: true`
- **THEN** the response includes the dev-admin email and an empty `workspaces` list

#### Scenario: Probe response has stable identity fields

- **WHEN** a client calls `GET /admin/v1/whoami`
- **THEN** the response includes `actor_type`, `email`, and `workspaces`
- **THEN** `actor_type` is `"system"` and `workspaces` is an empty array

### Requirement: Workspace management endpoints

The system SHALL expose workspace CRUD endpoints with one-to-one parity with `dejaq-admin workspace` subcommands:
- `GET /admin/v1/workspaces` — list every workspace as `[{id, name, slug, created_at}]`.
- `POST /admin/v1/workspaces` — create workspace from `{name}`; return HTTP 201 with the new workspace. Duplicate slug SHALL return HTTP 409.
- `DELETE /admin/v1/workspaces/{slug}` — delete a workspace and cascade departments, API keys, and LLM config; return HTTP 200 with `{"deleted": true, "departments_removed": <int>}`. Unknown slug SHALL return HTTP 404.

#### Scenario: List workspaces

- **WHEN** a client calls `GET /admin/v1/workspaces`
- **THEN** the response is HTTP 200 with a JSON array of every workspace

#### Scenario: CLI lists the same workspaces

- **WHEN** the CLI calls the workspace listing service
- **THEN** every workspace is returned

#### Scenario: Create workspace with duplicate name

- **WHEN** a client posts a name whose derived slug already exists
- **THEN** the response is HTTP 409 with `{"detail": "Workspace slug already exists"}`

#### Scenario: Delete unknown workspace

- **WHEN** a client calls `DELETE /admin/v1/workspaces/does-not-exist`
- **THEN** the response is HTTP 404

#### Scenario: Delete workspace cascades departments

- **WHEN** a client deletes a workspace with three departments
- **THEN** the response includes `"departments_removed": 3` and all three departments plus the workspace's API keys and LLM config row are gone from the DB

### Requirement: Department management endpoints

The system SHALL expose department CRUD endpoints with one-to-one parity with `dejaq-admin dept`:
- `GET /admin/v1/departments?workspace=<slug>` — list departments; `workspace` query param optional. Without `workspace`, return departments across every workspace. With `workspace`, return departments for that workspace. Each item SHALL include `{id, workspace_slug, name, slug, cache_namespace, created_at}`.
- `POST /admin/v1/workspaces/{workspace_slug}/departments` — create from `{name}`; HTTP 201 on success. Unknown workspace → HTTP 404. Duplicate dept slug under the same workspace → HTTP 409.
- `DELETE /admin/v1/workspaces/{workspace_slug}/departments/{dept_slug}` — delete; HTTP 200 with `{"deleted": true, "cache_namespace": "<freed-ns>"}`. Unknown workspace or dept → HTTP 404.

#### Scenario: List departments scoped to a workspace

- **WHEN** a client calls `GET /admin/v1/departments?workspace=acme`
- **THEN** only departments belonging to workspace `acme` are returned

#### Scenario: List departments without workspace filter

- **WHEN** a client calls `GET /admin/v1/departments`
- **THEN** departments across every workspace are returned, each carrying its `workspace_slug`

#### Scenario: List departments for unknown workspace

- **WHEN** a client calls `GET /admin/v1/departments?workspace=does-not-exist`
- **THEN** the response is HTTP 200 with an empty array

#### Scenario: Create department under unknown workspace

- **WHEN** a client posts to `/admin/v1/workspaces/missing/departments`
- **THEN** the response is HTTP 404

#### Scenario: Delete department returns freed namespace

- **WHEN** a client deletes a department
- **THEN** the response includes the `cache_namespace` value the entry occupied

### Requirement: API key management endpoints

The system SHALL expose API-key endpoints with one-to-one parity with `dejaq-admin key`:
- `GET /admin/v1/workspaces/{workspace_slug}/keys` — list keys as `[{id, token_prefix, created_at, revoked_at}]`. The `token_prefix` SHALL be the first 12 chars followed by `...`; the full token SHALL NOT be returned. Unknown workspace → HTTP 404.
- `POST /admin/v1/workspaces/{workspace_slug}/keys?force=<bool>` — generate a new key. Without `force`, an existing active key SHALL cause HTTP 409. With `force=true`, the existing active key SHALL be revoked first. The response (HTTP 201) SHALL include the full token (one-time visibility). Unknown workspace → HTTP 404.
- `DELETE /admin/v1/keys/{key_id}` — revoke by id. Already-revoked keys SHALL return HTTP 200 with `{"revoked": true, "already_revoked": true}`. Unknown id SHALL return HTTP 404.

#### Scenario: List keys masks token

- **WHEN** a client calls `GET /admin/v1/workspaces/acme/keys`
- **THEN** each entry contains `token_prefix` only and never the full secret

#### Scenario: List keys for unknown workspace

- **WHEN** a client calls `GET /admin/v1/workspaces/does-not-exist/keys`
- **THEN** the response is HTTP 404

#### Scenario: Generate key without force when active key exists

- **WHEN** the workspace already has an active key and the client posts without `force=true`
- **THEN** the response is HTTP 409 with a message recommending `?force=true`

#### Scenario: Generate key with force rotates the key

- **WHEN** the client posts with `?force=true` and an active key exists
- **THEN** the existing key is revoked, a new key is created, and the response (HTTP 201) returns the new full token exactly once

#### Scenario: Revoke unknown key id

- **WHEN** a client calls `DELETE /admin/v1/keys/99999` on a non-existent id
- **THEN** the response is HTTP 404

### Requirement: Stats endpoints support optional date range filtering

The system SHALL expose stats aggregation endpoints:
- `GET /admin/v1/stats/workspaces?from=<ISO-8601 date>&to=<ISO-8601 date>` — totals per workspace plus a grand total across all workspaces.
- `GET /admin/v1/stats/workspaces/{workspace_slug}/departments?from=...&to=...` — totals per department for the given workspace.

Both endpoints SHALL accept optional `from` and `to` query parameters as ISO-8601 dates (`YYYY-MM-DD`), interpreted as UTC midnight inclusive (`from`) and UTC midnight exclusive (`to`). The service SHALL compare using the same UTC ISO timestamp representation stored in the request log: Python `datetime(..., tzinfo=timezone.utc).isoformat()` strings with `+00:00` offsets, not `Z` suffixes. Invalid date formats and `from > to` SHALL return HTTP 422.

`GET /admin/v1/stats/workspaces` SHALL return `{items: WorkspaceStats[], total: StatsMetrics}`. `WorkspaceStats` SHALL include `{workspace, workspace_name, requests, hits, misses, hit_rate, avg_latency_ms, est_tokens_saved, easy_count, hard_count, models_used}`. `StatsMetrics` SHALL include the aggregate metric fields without identity fields, aggregated over every workspace row.

`GET /admin/v1/stats/workspaces/{workspace_slug}/departments` SHALL return `{workspace, items: DepartmentStats[], total: StatsMetrics}`. `DepartmentStats` SHALL include `{workspace, department, department_name, requests, hits, misses, hit_rate, avg_latency_ms, est_tokens_saved, easy_count, hard_count, models_used}`. Unknown workspace SHALL return HTTP 404.

#### Scenario: Per-workspace stats with no date filter

- **WHEN** a client calls `GET /admin/v1/stats/workspaces`
- **THEN** the response is HTTP 200 with one row per workspace plus a `total` field aggregating every row

#### Scenario: Per-department stats for a single workspace

- **WHEN** a client calls `GET /admin/v1/stats/workspaces/acme/departments`
- **THEN** the response contains one row per department under `acme`

#### Scenario: Stats include every workspace

- **WHEN** requests exist for both `acme` and `globex`
- **THEN** `GET /admin/v1/stats/workspaces` includes both `acme` and `globex` stats

#### Scenario: Stats empty when no requests were logged

- **WHEN** a client calls `GET /admin/v1/stats/workspaces` against an empty request log
- **THEN** the response is HTTP 200 with an empty `items` array
- **THEN** the `total` field contains zero-valued metrics

#### Scenario: Date range filter is honored

- **WHEN** a client calls `GET /admin/v1/stats/workspaces?from=2026-04-01&to=2026-04-15`
- **THEN** only requests with `ts` in `[2026-04-01T00:00:00+00:00, 2026-04-15T00:00:00+00:00)` are aggregated

#### Scenario: Invalid date returns 422

- **WHEN** a client passes `?from=04/01/2026`
- **THEN** the response is HTTP 422

#### Scenario: Reversed date range returns 422

- **WHEN** a client passes `?from=2026-04-15&to=2026-04-01`
- **THEN** the response is HTTP 422

#### Scenario: Stats for unknown workspace

- **WHEN** a client calls `GET /admin/v1/stats/workspaces/missing/departments`
- **THEN** the response is HTTP 404

### Requirement: Feedback management endpoints

The system SHALL expose feedback management endpoints:
- `GET /admin/v1/feedback` — list feedback entries across every workspace, optionally filtered by `workspace`, `department`, or `response_id`.
- `POST /admin/v1/feedback` — create or record management feedback. Unknown workspace or response metadata SHALL return HTTP 404. Validation errors SHALL return HTTP 422.

Collection responses SHALL include resources from every workspace.

#### Scenario: List feedback includes every workspace

- **WHEN** feedback exists for both `acme` and `globex`
- **THEN** `GET /admin/v1/feedback` includes feedback associated with both

#### Scenario: Create feedback for unknown workspace

- **WHEN** a client posts feedback naming a workspace that does not exist
- **THEN** the response is HTTP 404

#### Scenario: CLI lists the same feedback

- **WHEN** the CLI or trusted service path lists feedback
- **THEN** feedback across all workspaces is returned

## REMOVED Requirements

### Requirement: Admin endpoints require a shared admin bearer token
**Reason**: Management API authorization moved from a single shared secret to loopback-bound, unauthenticated dev-admin access.

**Migration**: No credential is needed for `/admin/v1/*` — access is restricted by loopback binding instead. The CLI calls the shared admin service directly instead of using `DEJAQ_ADMIN_TOKEN`.

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

**Migration**: No configuration is needed — `require_management_auth` always returns the unauthenticated dev-admin context, and the surface is protected by loopback binding instead.

#### Scenario: DEJAQ_ADMIN_TOKEN is unset or blank

- **WHEN** the server starts with `DEJAQ_ADMIN_TOKEN` unset, empty, or whitespace-only and a client calls `GET /admin/v1/orgs` with any bearer token
- **THEN** the system returns HTTP 503 with `{"detail": "Admin API disabled: DEJAQ_ADMIN_TOKEN not configured"}`

#### Scenario: Startup warning is emitted

- **WHEN** the server starts with `DEJAQ_ADMIN_TOKEN` unset
- **THEN** a warning is logged via `dejaq.admin` indicating the admin API is disabled
