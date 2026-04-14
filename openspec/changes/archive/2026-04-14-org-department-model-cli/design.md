## Context

DejaQ is a single-tenant FastAPI + ChromaDB platform with no user/org concepts today. The next major milestone — API keys, per-tenant usage tracking, and a dashboard — all require knowing which organization a request belongs to. This change introduces `Organization` and `Department` as persistent entities backed by SQLite (via SQLAlchemy), and a CLI for operators to manage them. No runtime request path changes in this iteration.

## Goals / Non-Goals

**Goals:**
- SQLAlchemy ORM models for `organizations` and `departments` tables in a local SQLite file (`dejaq.db`)
- Alembic migration that creates both tables
- Pydantic schemas mirroring the ORM models for use across the codebase
- `dejaq-admin` CLI (Click-based, `uv run dejaq-admin`) with commands: `org create`, `org list`, `org delete`, `dept create`, `dept list`, `dept delete`
- Each department has a `cache_namespace` (slug-derived) that will scope future ChromaDB queries

**Non-Goals:**
- Wiring `cache_namespace` into the live chat/cache pipeline (follow-on change)
- API key management (depends on this change, but separate)
- Auth or multi-user access control
- Web UI or HTTP endpoints for org/dept management
- Migrating to Postgres/Supabase (follow-on; SQLAlchemy makes this a config swap)

## Decisions

### 1. SQLite + SQLAlchemy over Supabase for now

**Decision:** Use a local SQLite file (`dejaq.db`) managed by SQLAlchemy Core/ORM + Alembic.

**Rationale:** Zero external dependencies — no Supabase project, no env vars, no network required to get started. SQLAlchemy abstracts the dialect so switching to Postgres later is a one-line connection string change. Alembic handles schema migrations the same way regardless of backend.

**Alternatives considered:**
- Supabase immediately: requires provisioning a project and credential management before any code runs; adds friction for local dev.
- Raw sqlite3: no ORM, no migration tooling, harder to evolve schema.

### 2. CLI via Click, not a new HTTP endpoint

**Decision:** Expose org/dept management as a CLI (`uv run dejaq-admin`) rather than adding REST endpoints.

**Rationale:** This is an operator-level bootstrapping tool. Adding HTTP endpoints now would require auth (chicken-and-egg with API keys). A CLI invoked with `uv run` keeps the blast radius small and avoids adding unauthenticated admin routes.

**Alternatives considered:**
- FastAPI admin endpoints: deferred — after API key auth lands, a protected admin API makes sense.

### 3. `cache_namespace` derived from slug, stored in DB

**Decision:** `cache_namespace` = `"{org_slug}__{dept_slug}"` — computed at department creation, persisted as a column.

**Rationale:** Makes namespaces human-readable and deterministic. Avoids UUIDs in ChromaDB collection names. Storing it means downstream consumers never need to re-derive it and the value is stable even if derivation logic changes.

**Alternatives considered:**
- UUID-based namespace: opaque, harder to debug cache entries.
- Computed at query time: fragile if derivation logic changes.

### 4. Cascade delete on org → departments

**Decision:** `departments.org_id` has `ON DELETE CASCADE`. Deleting an org removes all its departments automatically.

**Rationale:** Simpler operator UX — no need to manually clean up departments first. CLI prints a warning listing affected departments before executing the delete.

### 5. SQLAlchemy session as a context manager, not a FastAPI dependency

**Decision:** `app/db/session.py` exposes a `get_session()` context manager. CLI and future HTTP routes both use this module.

**Rationale:** Keeps the session reusable without coupling it to FastAPI's `Depends()` system prematurely. Wrapping in `Depends` is trivial when HTTP endpoints are added.

## Risks / Trade-offs

- **SQLite write concurrency**: SQLite serializes writes; fine for a CLI tool, would be a bottleneck under concurrent HTTP load. → Mitigation: acceptable for v1; Postgres swap resolves it when needed.
- **No soft-delete**: Org cascade delete permanently removes departments. ChromaDB entries for deleted namespaces become orphaned. → Mitigation: CLI prints cascade warning before executing; ChromaDB cleanup is a follow-on task.
- **Slug immutability**: Once a `cache_namespace` is stored and referenced by ChromaDB, changing the slug would break cache lookups. → Mitigation: Slugs are immutable after creation; no update command exposed in the CLI.
- **Slug uniqueness enforcement**: Org slug globally unique; dept slug unique per org. Both enforced by DB unique constraints; CLI surfaces a friendly error on violation.

## Migration Plan

1. `uv add sqlalchemy alembic click`
2. `uv run alembic init alembic` and configure `alembic.ini` to point at `dejaq.db`
3. Generate and apply migration: `uv run alembic revision --autogenerate -m "add orgs and departments"` → `uv run alembic upgrade head`
4. Run `uv run dejaq-admin org list` to verify DB connectivity

**Rollback:** `uv run alembic downgrade -1` drops both tables. Remove `cli/` and `app/db/` additions. No existing services modified.
