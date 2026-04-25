## Context

DejaQ has two operational surfaces today: the OpenAI-compatible gateway (`/v1/*`, authed by per-org API keys) and the `dejaq-admin` Click CLI (direct DB access via `app.db.*` repos). Every operator workflow lives in the CLI: org/dept CRUD, API-key issuance and revocation, stats reading, and ad-hoc DB inspection. The CLI calls `app.db.*_repo` modules directly through synchronous SQLAlchemy sessions. Stats lives in `cli/stats.py` as a self-contained `sqlite3.connect(...)` script. Feedback already has a public submit endpoint (`/v1/feedback`) authed by the org key.

The web dashboard scheduled for BW1 will run as a separate frontend (Supabase-authed in production) and needs an HTTP surface to read and mutate the same data. We do not want the dashboard to grow a "shadow backend" of Python helpers, and we do not want to commit to Supabase auth before BW1 starts.

## Goals / Non-Goals

**Goals:**
- One-to-one HTTP coverage of every `dejaq-admin` subcommand under a stable `/admin/v1/*` namespace.
- All admin endpoints behind a single shared bearer token (`DEJAQ_ADMIN_TOKEN`) so the dashboard can call them in dev without a user-auth system.
- Stats and CRUD logic extracted into reusable services so CLI and API stay equivalent for business behavior while each surface keeps its own presentation.
- Pydantic schemas everywhere; standard HTTP status codes; JSON-only responses.
- Additive change: zero impact on `/v1/chat/completions`, `/v1/feedback` (existing), or current CLI ergonomics.

**Non-Goals:**
- Supabase / OAuth / per-user RBAC (BW1 follow-up).
- Audit log of admin mutations (BW1 follow-up).
- Pagination beyond simple `limit`/`offset` on the feedback list.
- Streaming endpoints, websockets, or server-sent events.
- Backwards-compatible removal of CLI commands — CLI stays exactly as it is.

## Decisions

### Single shared bearer token, not per-admin keys
Use one `DEJAQ_ADMIN_TOKEN` env var checked as `Authorization: Bearer <token>` by a FastAPI dependency. Rejected alternatives: (a) reusing the org API-key middleware — wrong trust model since admin acts across all orgs; (b) building a real admin-user table now — Supabase will replace it in weeks, so the work would be thrown away. Mitigation for the obvious downside: if `DEJAQ_ADMIN_TOKEN` is unset, the admin router returns `503 Service Unavailable` on every request rather than allowing access — this fails closed and makes misconfiguration impossible to miss.

`/admin/v1/*` is a separate trust surface. The existing org API-key middleware must skip this path prefix before parsing or logging `Authorization`, so a valid admin token is never treated as an unknown org API key and never appears in org-key warning logs. The admin-token lifecycle is process-scoped: token rotation requires process restart unless a later settings system makes it dynamic. Empty or whitespace-only tokens count as unset.

During this pre-BW1 phase, the admin API is intended for trusted dashboard deployments only: same-origin development, a reverse proxy/VPN boundary, or an explicit admin CORS allowlist. It must not rely on the bearer token alone as the only protection for an internet-exposed browser dashboard, and browser deployments must not expose admin routes through wildcard CORS.

### Mount under `/admin/v1/*` not `/v1/admin/*`
`/v1/*` is the OpenAI-compatible client surface; mixing internal admin routes there muddies API documentation and complicates future versioning of either surface. `/admin/v1/*` makes the boundary obvious to operators reading nginx logs and to the dashboard's HTTP client.

### Extract stats into a service, do not call the CLI from HTTP
`cli/stats.py` opens its own `sqlite3` connection and renders Rich tables. Calling it from FastAPI would mean parsing rendered ANSI or refactoring around `Console`. Instead, move the SQL aggregation into `app/services/stats_service.py` returning typed dataclasses/Pydantic models; the CLI keeps owning rendering and the router owns serialization. Same code path, two presentations.

The shared stats service owns timestamp normalization. Request-log timestamps are UTC ISO strings produced with Python `datetime(..., tzinfo=timezone.utc).isoformat()` (for example `2026-04-01T00:00:00+00:00`); date filters are converted to UTC midnight bounds in that exact `+00:00` representation before SQL filtering. `from > to` is a validation error. HTTP handlers must not run blocking persistence work directly on the event loop: sync SQLite/SQLAlchemy services are exposed through sync FastAPI route handlers, wrapped with `asyncio.to_thread`, or replaced with async DB access.

The shared service covers request-log aggregates only. The CLI's Cache Health panel remains CLI-owned unless a later change defines a ChromaDB cache-health API contract.

### Extract CLI business logic into services
Today `cli/admin.py` calls `org_repo.delete_org(...)` directly and prints results. The router cannot reuse that. Move the orchestration (e.g., "delete org cascades to N depts; surface the count") into `app/services/admin_service.py` with pure-data return values. CLI keeps its prompts/spinners; router maps return values into responses. This is the only refactor required to keep CLI/API in sync.

Parity is tracked with an explicit matrix: leaf Click command → service function → HTTP method/path → required options/query params → special behavior. The matrix is about business effects and result data, not terminal-only presentation. Destructive CLI preview/prompt flows remain CLI-owned unless the dashboard later needs explicit preview endpoints.

### LLM config is a new table, not env-var-only
Per-org LLM config (e.g., external model name, easy/hard threshold) currently lives in process-wide env vars, so "read config per org" has no source. Add a small `org_llm_config` table (one row per org, FK to `organizations`) with sensible columns: `external_model`, `local_model`, `routing_threshold`, `updated_at`. Reading falls back to global defaults from `app.config` if no row exists. Updating upserts the row. This is the smallest schema change that makes the endpoint coherent without inventing a config DSL.

Update semantics are explicit: omitted fields preserve the current stored value, explicit JSON `null` clears that org-level override and falls back to the global default, and non-null fields set an override. Reads return the effective values, whether each value is default-backed via an `overrides` object, `is_default`, and `updated_at` (`null` when no row exists).

### Stats date filtering uses ISO-8601 query params
`GET /admin/v1/stats?from=2026-04-01&to=2026-04-25`. Both optional. Server parses as `date` (UTC midnight start, UTC midnight end-exclusive). Invalid date → 422. Avoids epoch-millis/timezone ambiguity.

### Feedback list uses simple `limit`/`offset`, default 100/0
The `feedback_log` table is small (one row per user feedback action). Cursor pagination is over-engineering for a dashboard that will mostly show "last 50". Filters: `org`, `department`, `response_id`, all optional, AND-combined.

Admin feedback submission cannot infer org/department from org API-key auth, so `POST /admin/v1/feedback` requires explicit `org` and accepts optional `department` (default `default`) alongside `response_id`, `rating`, and `comment`. The feedback service validates that the org/department exists and that the target response/cache entry belongs to that namespace; namespace mismatch returns a client error instead of silently logging `anonymous/default`.

Feedback listing is deterministic: `ORDER BY ts DESC, id DESC`, with `total` counting rows matching the filters before `limit`/`offset`.

### Errors use FastAPI `HTTPException` with stable shape
`{"detail": "..."}` only — same shape FastAPI produces by default. No custom error envelope; the dashboard maps status codes directly. Validation errors produced by Pydantic remain `422` with the default body.

## Risks / Trade-offs

- **Single shared admin token is a high-blast-radius secret** → Treat it as a deployment secret (env var, not committed). Fail closed when unset (return 503). Document rotation as "redeploy with new value." Real auth lands in BW1 before any external exposure.
- **CLI/API drift over time** → Mitigated by routing both through shared services and a parity matrix test. Route-existence introspection is only a smoke alarm; service and contract tests cover duplicate slugs, key rotation, delete results, revoke idempotency, stats windows, and token visibility.
- **`org_llm_config` schema may grow** → Keep it deliberately narrow now (4 scalar columns). Adding a column later is a one-line Alembic migration; locking the shape in now would invent fields we do not have requirements for.
- **Stats query on a large `requests` table could get slow** → Add idempotent indexes for the new dashboard access patterns (`requests(ts)`, `requests(org, department, ts)`, `feedback_log(ts, id)`, `feedback_log(org, department)`, `feedback_log(response_id)`) when the SQLite log tables are initialized.
- **Admin router 503'ing when token unset will surprise local devs** → Print a clear startup log line ("DEJAQ_ADMIN_TOKEN not set; /admin/v1/* disabled") and document the env var in CLAUDE.md and all three Deployment Modes sections.

## Migration Plan

1. Land contract/test-harness scaffolding and admin-auth isolation first: token config/dependency, `/admin/v1/*` middleware bypass, startup warning, and early auth tests.
2. Land `org_llm_config` table via additive Alembic migration and log-table indexes. No backfill — endpoint reads return defaults until a row exists.
3. Land schema and service refactor (`admin_service`, `stats_service`, feedback service, LLM config service) without changing CLI behavior. Run existing CLI smoke tests and new service tests.
4. Land admin router and full route-inheritance auth matrix. Mount under `/admin/v1`.
5. Update CLAUDE.md and Deployment Modes blocks with `DEJAQ_ADMIN_TOKEN`.
6. Rollback strategy: revert the router mount line and the env var docs. The `org_llm_config` table and log-table indexes are additive and harmless if left in place.

## Open Questions

- Should `POST /admin/v1/orgs/{slug}/keys` return the full token in the response body (matching CLI behavior, one-time visibility) or only a token prefix? Defaulting to **full token in response** since the dashboard is the only consumer and it needs to display/copy it once. Rotation flow uses `?force=true` mirroring the CLI.
