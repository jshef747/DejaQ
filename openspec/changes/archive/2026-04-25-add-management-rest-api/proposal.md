## Why

The DejaQ admin CLI exposes every operation needed to run the platform — orgs, departments, API keys, stats, feedback — but the upcoming web dashboard has no HTTP surface to call. Building dashboard features today means reaching into Python repositories or shelling out to `dejaq-admin`, which couples the frontend to the backend's process model. Exposing the CLI surface as a REST API now lets the dashboard be pure UI work and unblocks BW1 without a second round of backend changes.

## What Changes

- Add a management REST API mounted under `/admin/v1/*` covering every CLI command:
  - Orgs: list, create, delete
  - Departments: list (org-scoped or global), create, delete
  - API keys: list per org, generate (with `force`), revoke by id
  - Stats: per-org and per-department aggregates with optional `from`/`to` date filtering
  - LLM config: read and update per org (new persisted setting, currently CLI-implicit)
  - Feedback: submit with explicit admin attribution (`org`, optional `department`) and list per org/dept/response_id
- Authenticate every management endpoint with a single shared admin token via `Authorization: Bearer <DEJAQ_ADMIN_TOKEN>`. Token comes from a new `DEJAQ_ADMIN_TOKEN` env var. Missing, malformed, or wrong token → `401`; unset/empty/whitespace-only server token → `503`.
- Keep the admin namespace isolated from existing org API-key auth: `/admin/v1/*` requests must bypass org-key middleware and must never log the admin bearer token as an unknown org API key.
- All requests/responses use Pydantic schemas; errors use standard HTTP status codes (`401` auth, `404` not found, `409` conflict on duplicate slug or active key, `422` request parsing/schema/query validation).
- Add `app/routers/admin/` package (`orgs.py`, `departments.py`, `keys.py`, `stats.py`, `llm_config.py`, `feedback.py`) and a shared `dependencies/admin_auth.py` guard.
- Refactor CLI commands to call the same service-layer helpers the API uses, so CLI and API stay one-to-one for business behavior without duplicating logic. Terminal-only presentation details (prompts, panels, spinners) remain CLI-owned.
- Document `DEJAQ_ADMIN_TOKEN` in CLAUDE.md env table and all three Deployment Modes blocks.
- Out of scope: Supabase session auth, per-user RBAC, audit log of admin actions — all deferred to BW1.

## Capabilities

### New Capabilities
- `management-api`: HTTP surface for org, department, API-key, stats, LLM-config, and feedback management secured by a shared admin bearer token.
- `org-llm-config`: Per-org LLM routing/config record (e.g., external model name, routing thresholds) readable and writable through the management API.

### Modified Capabilities
- `response-feedback`: Adds a list-feedback endpoint (currently submit-only) and admin-token auth path alongside existing org-key-authed `/v1/feedback`.
- `stats-cli`: Stats aggregation logic extracted into a reusable service used by both the CLI and the new `/admin/v1/stats` endpoints; adds optional `from`/`to` date filtering.

## Impact

- **New code**: `app/routers/admin/` package, `app/dependencies/admin_auth.py`, `app/services/stats_service.py` (extracted from `cli/stats.py`), `app/services/llm_config_service.py`, `app/db/models/org_llm_config.py`, `app/db/llm_config_repo.py`, Alembic migration for `org_llm_config` table, response schemas under `app/schemas/admin/`.
- **Modified code**: `cli/admin.py` and `cli/stats.py` switch to calling shared service helpers; `app/main.py` mounts the admin router; `app/config.py` adds admin-token configuration; `app/middleware/api_key.py` skips `/admin/v1/*`.
- **Routes**: New `/admin/v1/*` namespace. Existing gateway routes (`/v1/chat/completions`, `/v1/feedback`, and current department route mount) remain unchanged.
- **Config**: New `DEJAQ_ADMIN_TOKEN` env var (required for admin endpoints; if unset, admin router returns `503` to make misconfiguration obvious instead of silently allowing access).
- **DB**: One additive Alembic migration adding `org_llm_config` table (FK to `organizations`), plus idempotent indexes for stats/feedback query patterns where those SQLite log tables are initialized.
- **Deps**: No new packages. FastAPI, Pydantic, SQLAlchemy already present.
- **Tests**: New admin, service, and parity tests covering auth isolation, CRUD round-trips, stats date filtering, feedback attribution/list pagination, LLM config default/reset behavior, and CLI/API business parity.
