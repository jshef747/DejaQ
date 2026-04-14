## 1. Dependencies

- [x] 1.1 Add `sqlalchemy`, `alembic`, `click`, and `rich` to `pyproject.toml` via `uv add sqlalchemy alembic click rich`

## 2. Database Setup

- [x] 2.1 Initialize Alembic: `uv run alembic init alembic` and configure `alembic.ini` to point at `sqlite:///dejaq.db`
- [x] 2.2 Create `app/db/base.py` with SQLAlchemy `DeclarativeBase` and `engine`/`SessionLocal` setup pointing at `dejaq.db`
- [x] 2.3 Create `app/db/models/org.py` with SQLAlchemy `Organization` ORM model (id INTEGER PK, name TEXT NOT NULL, slug TEXT UNIQUE NOT NULL, created_at DATETIME DEFAULT now)
- [x] 2.4 Create `app/db/models/department.py` with SQLAlchemy `Department` ORM model (id INTEGER PK, org_id FK → organizations.id ON DELETE CASCADE, name TEXT NOT NULL, slug TEXT NOT NULL, cache_namespace TEXT NOT NULL, created_at DATETIME DEFAULT now, UNIQUE(org_id, slug))
- [x] 2.5 Generate Alembic migration: `uv run alembic revision --autogenerate -m "add orgs and departments"`
- [x] 2.6 Apply migration: `uv run alembic upgrade head` and verify `dejaq.db` contains both tables

## 3. Pydantic Schemas

- [x] 3.1 Create `app/schemas/org.py` with `OrgCreate` (name) and `OrgRead` (id, name, slug, created_at) Pydantic models
- [x] 3.2 Create `app/schemas/department.py` with `DeptCreate` (org_slug, name) and `DeptRead` (id, org_id, name, slug, cache_namespace, created_at) Pydantic models

## 4. Repository Layer

- [x] 4.1 Create `app/db/session.py` with `get_session()` context manager returning a `Session`
- [x] 4.2 Create `app/db/org_repo.py` with functions: `create_org(session, name) → OrgRead`, `list_orgs(session) → list[OrgRead]`, `get_org_by_slug(session, slug) → OrgRead | None`, `delete_org(session, slug) → int` (returns dept count deleted)
- [x] 4.3 Create `app/db/dept_repo.py` with functions: `create_dept(session, org_slug, name) → DeptRead`, `list_depts(session, org_slug=None) → list[DeptRead]`, `get_dept(session, org_slug, dept_slug) → DeptRead | None`, `delete_dept(session, org_slug, dept_slug) → DeptRead` — `create_dept` computes `cache_namespace` as `"{org_slug}__{dept_slug}"`

## 5. CLI

- [x] 5.1 Create `cli/__init__.py` (empty) and `cli/admin.py` with a root Click group `cli`
- [x] 5.2 Add `[project.scripts]` entry to `pyproject.toml`: `dejaq-admin = "cli.admin:cli"`
- [x] 5.3 Create `cli/ui.py` with Rich helpers: `console = Console()`, `print_header()` (renders a styled DejaQ banner with version using `rich.panel.Panel` + gradient text), `print_table(title, columns, rows)` (styled `rich.table.Table` with colored headers and alternating row shading), `print_success(msg)` (green checkmark), `print_error(msg)` (red X), `print_warning(msg)` (yellow warning, used for cascade deletes)
- [x] 5.4 Wire `print_header()` to fire on every command invocation via a Click `@cli.result_callback` or root group `invoke_without_command=True` block
- [x] 5.5 Implement `org create --name TEXT` (spinner during DB write via `rich.progress.Progress`; on success print panel showing id, name, slug)
- [x] 5.6 Implement `org list` (Rich table: ID / Name / Slug / Created; empty state prints styled "No organizations yet" message)
- [x] 5.7 Implement `org delete --slug TEXT` (print cascade warning as a Rich Panel listing affected dept slugs; prompt confirmation with `rich.prompt.Confirm`; spinner on delete; success message)
- [x] 5.8 Implement `dept create --org TEXT --name TEXT` (spinner; on success print panel showing id, name, slug, and cache_namespace highlighted in cyan)
- [x] 5.9 Implement `dept list [--org TEXT]` (Rich table: ID / Org / Name / Slug / Cache Namespace / Created; cache_namespace column styled in dim cyan)
- [x] 5.10 Implement `dept delete --org TEXT --slug TEXT` (confirm prompt; spinner; print cache_namespace that was freed)

## 6. Interactive TUI (optional stretch)

- [x] 6.1 Add `uv add textual` and create `cli/tui.py` — a Textual app (`dejaq-admin tui`) with a sidebar listing orgs and a main panel showing departments for the selected org
- [x] 6.2 Keyboard shortcuts: `n` = new org/dept, `d` = delete selected, `q` = quit; all mutations go through the same repo layer
- [x] 6.3 Add `dejaq-admin-tui = "cli.tui:run"` script entry to `pyproject.toml`

## 7. Verification

- [x] 7.1 Run `uv run dejaq-admin org create --name "Test Org"` and confirm row exists in `dejaq.db`
- [x] 7.2 Run `uv run dejaq-admin dept create --org "test-org" --name "Support Bot"` and confirm cache_namespace is `"test-org__support-bot"`
- [x] 7.3 Run `uv run dejaq-admin org list` and `uv run dejaq-admin dept list` — confirm Rich tables render correctly
- [x] 7.4 Run `uv run dejaq-admin org delete --slug "test-org"` — confirm cascade warning appears and department row is removed
- [x] 7.5 Verify error paths: duplicate org slug, missing parent org, delete non-existent slug — all show styled error panel and exit non-zero
