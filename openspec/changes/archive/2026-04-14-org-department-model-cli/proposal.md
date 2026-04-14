## Why

DejaQ currently runs as a single-tenant system — all orgs, caches, and LLM traffic share one global context. Before API keys, usage tracking, or a dashboard can be built, the platform needs a first-class concept of who is using it. Orgs and departments are that foundation.

## What Changes

- Introduce `Organization` as a top-level tenant entity stored in Supabase
- Introduce `Department` as a sub-unit of an org (team, product, or bot) with its own isolated cache namespace
- ChromaDB cache queries will be scoped to a department's namespace so entries never bleed across departments
- Add a `dejaq-admin` CLI tool (Python, invoked via `uv run`) for CRUD operations: create/list/delete orgs and departments
- No existing HTTP API endpoints change in this iteration — tenant isolation is introduced at the data layer only

## Capabilities

### New Capabilities
- `org-management`: Create, list, and delete organizations in Supabase; each org has an id, name, slug, and timestamps
- `department-management`: Create, list, and delete departments under an org; each department has an id, org_id, name, slug, and a cache_namespace that scopes ChromaDB queries

### Modified Capabilities
<!-- None — existing cache, normalizer, enricher, and classifier services are not modified in this change -->

## Impact

- **New dependencies**: `sqlalchemy`, `alembic`, `click`
- **New files**: `cli/` directory with admin CLI entry point; `app/db/models/org.py`, `app/db/models/department.py`; `alembic/` for schema migrations; `dejaq.db` SQLite file (gitignored)
- **Existing services**: unmodified — cache namespace wiring to live services is out of scope for this change
- **Storage**: local SQLite (`dejaq.db`); no external service required; SQLAlchemy makes a future Postgres swap a one-line config change
