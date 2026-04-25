## 0. Contract Clarification & Test Harness

- [x] 0.1 Add an implementation-facing parity matrix documenting leaf Click command → service function → HTTP method/path → required options/query params → special behavior (token visibility, delete result data, force, idempotent revoke, CLI-only prompts)
- [x] 0.2 Lock exact admin route request/response shapes in schemas/spec before router work: stats identities and total object, feedback submit attribution, LLM config defaults/overrides, key create/list/revoke, delete responses
- [x] 0.3 Define validation outcomes for `from > to`, malformed `force`, empty `PUT /llm-config` (422), explicit `null` values, unknown feedback org/department filters (200 empty list), and namespace mismatches
- [x] 0.4 Create shared test fixtures with isolated org DB, isolated `DEJAQ_STATS_DB`, isolated admin-token config, migrations applied, SQLite foreign keys enabled, deterministic timestamps, and Chroma/cache feedback behavior mocked

## 1. Config & Auth Foundation

- [x] 1.1 Add admin-token configuration for `DEJAQ_ADMIN_TOKEN` with whitespace-only treated as unset; document that rotation requires process restart unless settings are later made dynamic
- [x] 1.2 Document `DEJAQ_ADMIN_TOKEN` in CLAUDE.md env-var table and all three Deployment Modes blocks, including trusted-network/same-origin/reverse-proxy guidance for `/admin/v1/*` and no wildcard admin CORS for browser deployments
- [x] 1.3 Create `app/dependencies/admin_auth.py` exposing `require_admin_token` FastAPI dependency: returns 503 when configured token is empty, 401 on missing/malformed/wrong token, validates with `hmac.compare_digest`
- [x] 1.4 Log a warning at FastAPI startup (`app/main.py` lifespan) when `DEJAQ_ADMIN_TOKEN` is empty, naming the env var
- [x] 1.5 Update existing org API-key middleware to skip `/admin/v1/*` before parsing or logging `Authorization`, so admin tokens are never treated as unknown org API keys
- [x] 1.6 Add early admin auth dependency tests for unset/empty/whitespace token → 503, missing/malformed token → 401, wrong token → 401, valid token → handler execution on the initial probe route

## 2. DB Layer for Org LLM Config

- [x] 2.1 Create `app/db/models/org_llm_config.py` (`OrgLlmConfig` ORM: `org_id` PK + FK CASCADE, `external_model`, `local_model`, `routing_threshold`, `updated_at`) and add an `Organization.llm_config` relationship with ORM cascade/delete-orphan
- [x] 2.2 Add Alembic migration creating `org_llm_config` table
- [x] 2.3 Ensure SQLite foreign keys are enabled for SQLAlchemy connections used by CLI, API, and tests
- [x] 2.4 Create `app/db/llm_config_repo.py` with `get_for_org(session, org_id)` and `upsert_for_org(session, org_id, payload, fields_set)` so omitted fields preserve values and explicit `null` clears overrides
- [x] 2.5 Create `app/services/llm_config_service.py` exposing `read_for_org(org_slug)` (returns effective config, `overrides`, `updated_at`, and `is_default`) and `update_for_org(org_slug, payload)` (raises `OrgNotFound` for unknown slug)
- [x] 2.6 Add idempotent SQLite indexes for stats/feedback log-table access patterns where those tables are initialized: `requests(ts)`, `requests(org, department, ts)`, `feedback_log(ts, id)`, `feedback_log(org, department)`, `feedback_log(response_id)`

## 3. Service Extraction (CLI ↔ API parity)

- [x] 3.1 Create `app/services/admin_service.py` with pure-data functions: `list_orgs`, `create_org(name)`, `delete_org(slug)`, `list_departments(org_slug=None)`, `create_department(org_slug, name)`, `delete_department(org_slug, dept_slug)`, `list_keys(org_slug)`, `generate_key(org_slug, force)`, `revoke_key(key_id)`. Each returns behavior-rich Pydantic models (`OrgDeleteResult`, `DeptDeleteResult`, `KeyCreated`, `KeyListItem`, `KeyRevokeResult`) or raises typed exceptions carrying resource context (`OrgNotFound`, `DeptNotFound`, `KeyNotFound`, `DuplicateSlug`, `ActiveKeyExists`)
- [x] 3.2 Create `app/services/stats_service.py` with `org_stats(from_date=None, to_date=None) -> OrgStatsReport` and `department_stats(org_slug, from_date=None, to_date=None) -> DepartmentStatsReport`. Move request-log SQL from `cli/stats.py` here. Define identity-bearing `OrgStats` / `DepartmentStats` models and aggregate `total` models with the spec's fields.
- [x] 3.2a Make `stats_service` own date-bound normalization using the same UTC ISO representation as stored request logs; reject `from_date > to_date`
- [x] 3.2b Ensure every sync persistence service called by HTTP (org/dept/key CRUD, LLM config, feedback mutation/listing, stats) is exposed through sync FastAPI handlers, run off the event loop (`asyncio.to_thread`), or replaced with async DB access
- [x] 3.2c Keep the CLI Cache Health panel CLI-owned unless a later cache-health API contract is added
- [x] 3.3 Refactor `cli/admin.py` so each Click command calls into `admin_service.*` and renders the returned data (no behavior change; preserve all spinners, panels, prompts)
- [x] 3.4 Refactor `cli/stats.py` `run()` to call `stats_service.org_stats()` and `stats_service.department_stats()` instead of inline `sqlite3` queries; rendering stays in CLI
- [x] 3.5 Extract existing feedback score mutation/logging into a shared feedback service with explicit caller context and attribution inputs; public `/v1/feedback` passes org-key-derived context, admin `/admin/v1/feedback` passes body-provided admin context; define `FeedbackResult`, `FeedbackNotFound`, `FeedbackNamespaceMismatch`, `FeedbackOrgNotFound`, and `FeedbackDeptNotFound`
- [x] 3.6 Run existing CLI smoke flow (`dejaq-admin org create`, `org list`, `dept create`, `dept list`, `key generate`, `key list`, `key revoke`, `org delete`, `stats`) and confirm output is identical to pre-refactor

## 4. Schemas

- [x] 4.1 Create `app/schemas/admin/__init__.py`
- [x] 4.2 Create `app/schemas/admin/orgs.py` (`OrgItem`, `OrgCreate`, `OrgDeleteResponse`)
- [x] 4.3 Create `app/schemas/admin/departments.py` (`DepartmentItem`, `DepartmentCreate`, `DepartmentDeleteResponse`)
- [x] 4.4 Create `app/schemas/admin/keys.py` (`KeyItem` with `token_prefix`, `KeyCreated` with full `token`, `KeyRevokeResponse`)
- [x] 4.5 Create `app/schemas/admin/stats.py` (`StatsMetrics`, `OrgStats` with org identity, `DepartmentStats` with org/department identity, `OrgStatsReport`, `DepartmentStatsReport`, `total: StatsMetrics`)
- [x] 4.6 Create `app/schemas/admin/llm_config.py` (`LlmConfigResponse` with effective values, `overrides`, `updated_at: datetime | None`, `is_default`, `LlmConfigUpdate` with all-optional/nullable fields and threshold validator; empty body rejected)
- [x] 4.7 Create `app/schemas/admin/feedback.py` (`AdminFeedbackRequest` with explicit org attribution, `FeedbackItem`, `FeedbackListResponse`)

## 5. Admin Router (HTTP Surface)

- [x] 5.1 Create `app/routers/admin/__init__.py` exporting an `APIRouter` mounted at `/admin/v1` with `Depends(require_admin_token)` applied router-wide
- [x] 5.2 Create `app/routers/admin/whoami.py` — `GET /whoami` returning `{authorized: True}`
- [x] 5.3 Create `app/routers/admin/orgs.py` — `GET /orgs`, `POST /orgs`, `DELETE /orgs/{slug}`; map `OrgNotFound` → 404, `DuplicateSlug` → 409
- [x] 5.4 Create `app/routers/admin/departments.py` — `GET /departments?org=...`, `POST /orgs/{org_slug}/departments`, `DELETE /orgs/{org_slug}/departments/{dept_slug}`; map errors as in spec
- [x] 5.5 Create `app/routers/admin/keys.py` — `GET /orgs/{org_slug}/keys`, `POST /orgs/{org_slug}/keys?force=...`, `DELETE /keys/{key_id}`. Mask token to first 12 chars + `...` on list; return full token on create.
- [x] 5.6 Create `app/routers/admin/stats.py` — `GET /stats/orgs`, `GET /stats/orgs/{org_slug}/departments`. Parse `from`/`to` as `date` (FastAPI Query type); return 422 on bad date or `from > to`, 404 on unknown org.
- [x] 5.7 Create `app/routers/admin/llm_config.py` — `GET /orgs/{org_slug}/llm-config`, `PUT /orgs/{org_slug}/llm-config`. Validate `routing_threshold ∈ [0.0, 1.0]` via Pydantic; omitted fields preserve, explicit `null` clears an override, empty body returns 422.
- [x] 5.8 Create `app/routers/admin/feedback.py` — `POST /feedback` with `{org, department?, response_id, rating, comment?}` via shared feedback service helper and `GET /feedback?org=&department=&response_id=&limit=&offset=`. `limit` capped at 500 via Pydantic `Field(le=500)`, ordered by `ts DESC, id DESC`, unknown org/department list filters return 200 empty results.
- [x] 5.9 Mount the admin router in `app/main.py` after the existing routers
- [x] 5.10 Add post-router auth matrix tests exercising every `/admin/v1/*` route for unset token → 503, missing/malformed token → 401, wrong token → 401, and valid token → handler execution

## 6. Tests

- [x] 6.1 Create `tests/test_admin_auth.py` — 503 when `DEJAQ_ADMIN_TOKEN` unset/empty/whitespace-only; 401 missing/malformed/wrong token; 200 valid token; whoami probe round-trip; every admin route inherits auth; admin requests bypass org-key middleware and do not log unknown-key warnings
- [x] 6.2 Create `tests/test_admin_orgs.py` — list/create/delete + cascade count + 409 on duplicate slug
- [x] 6.3 Create `tests/test_admin_departments.py` — list scoped + unscoped, 404 on unknown org, 409 on duplicate dept slug, freed-namespace in delete response
- [x] 6.4 Create `tests/test_admin_keys.py` — list masks token, generate without force → 409, with force rotates, revoke unknown → 404, revoke twice idempotent
- [x] 6.5 Create `tests/test_admin_stats.py` — seed `requests` table using `+00:00` UTC ISO timestamps, assert per-org and per-dept aggregates with identity fields and total object, date filter inclusion/exclusion at exact boundaries, 422 on bad date and `from > to`, 404 on unknown org
- [x] 6.6 Create `tests/test_admin_llm_config.py` — read defaults when no row (`is_default=True`, `updated_at=null`), all-null row returns `is_default=True` with row `updated_at`, partial update preserves untouched fields, explicit `null` clears override to default, empty PUT returns 422, 422 on out-of-range threshold, 404 on unknown org, cascade delete with org
- [x] 6.7 Create `tests/test_admin_feedback.py` — submit positive/negative parity with `/v1/feedback`, explicit org/department attribution, namespace mismatch error, list filters (org/dept/response_id), unknown list filters return 200 empty results, `limit` cap at 500, ordering by `ts DESC, id DESC`
- [x] 6.8 Create `tests/test_cli_api_parity.py` — assert the parity matrix is covered: every leaf Click command maps to a service and route where applicable; business behavior matches for duplicate org/dept, key generate/force/revoke, delete return values, and stats windows
- [x] 6.9 Create direct service tests for `admin_service`, `stats_service`, feedback service, and `llm_config_service` so CLI/API behavior is anchored below FastAPI routing
- [x] 6.10 Add route-boundary tests proving existing gateway auth behavior is unchanged while `/admin/v1/*` uses only admin-token auth
- [x] 6.11 Add async-safety tests or spies proving HTTP routes do not run blocking sync persistence work on the event loop

## 7. Docs & Deployment

- [x] 7.1 Update CLAUDE.md "Endpoints" section listing every `/admin/v1/*` route grouped by resource
- [x] 7.2 Update CLAUDE.md "Architecture" tree to include `app/routers/admin/`, `app/services/admin_service.py`, `app/services/stats_service.py`, `app/services/llm_config_service.py`, `app/db/models/org_llm_config.py`, `app/db/llm_config_repo.py`, `app/dependencies/admin_auth.py`
- [x] 7.3 Add a "Management API" subsection to CLAUDE.md describing the admin token model, middleware isolation, the 503-when-unset behavior, trusted deployment/CORS guidance, and the planned BW1 Supabase migration
- [x] 7.4 Run full test suite (`uv run pytest`) and confirm green
