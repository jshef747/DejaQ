## Context

DejaQ's chat pipeline (HTTP `POST /chat` and `WS /ws/chat`) already tracks cache outcomes and routing decisions internally but discards them after the response. The request logger needs to tap into these decision points — which live inside `app/routers/chat.py` — and persist them durably without adding latency to the hot path.

Currently no CLI exists. The entry point will be a new `dejaq` command (or `uv run python -m app.cli stats`) that reads the SQLite log and renders a Rich table TUI.

## Goals / Non-Goals

**Goals:**
- Zero-latency impact on the hot path: writes happen asynchronously via `aiosqlite`
- Single SQLite file for portability (no new infra)
- Rich TUI with per-department rows + org total, color-coded by outcome
- Captures: org, department, timestamp, latency_ms, cache_hit (bool), difficulty (`easy`/`hard`/`null`), model_used
- Works for both HTTP and WebSocket chat paths

**Non-Goals:**
- Real-time streaming updates to the TUI (static snapshot on invocation)
- PostgreSQL or multi-node storage (planned separately)
- Token counting via actual tokenizer (use heuristic: avg tokens ≈ words × 1.3)
- Per-user breakdown (org/department only)
- Auth or access control on the stats CLI

## Decisions

### SQLite via `aiosqlite`
**Decision**: Use `aiosqlite` for async writes inside the FastAPI event loop.  
**Rationale**: No new infrastructure. SQLite is sufficient for single-node dev/staging. Writes are fire-and-forget (no `await` blocking the response path — use `asyncio.create_task`).  
**Alternative considered**: Write to Redis and aggregate on CLI read. Rejected — Redis is ephemeral and already used for other purposes; SQLite gives durable queryable history.

### Single table schema
```sql
CREATE TABLE IF NOT EXISTS requests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,          -- ISO-8601 UTC
    org         TEXT NOT NULL,
    department  TEXT NOT NULL,
    latency_ms  INTEGER NOT NULL,
    cache_hit   INTEGER NOT NULL,       -- 0 or 1
    difficulty  TEXT,                  -- 'easy' | 'hard' | NULL (cache hits)
    model_used  TEXT                   -- model name | NULL (cache hits)
);
```
**Rationale**: One table is trivially queryable for all required aggregations. No joins needed.

### RequestLogger as a singleton service
**Decision**: `app/services/request_logger.py` exposes a module-level `RequestLogger` singleton initialized at FastAPI startup (same pattern as ModelManager).  
**Rationale**: Consistent with existing singleton patterns; avoids passing a logger instance through call chains.

### CLI entry point
**Decision**: `app/cli/stats.py` with a `__main__` block; invoked as `uv run python -m app.cli.stats`.  
**Rationale**: No new packaging needed. Rich is the rendering library — it's lightweight and already aligns with the project's Python-native stack. Textual (full TUI framework) is unnecessary for a static table view.

### Latency measurement
**Decision**: Measure wall-clock time from start of handler to just before returning the response.  
**Rationale**: Captures end-to-end gateway latency including enrichment, normalization, cache lookup, and LLM call. Excludes network I/O (measured at server boundary).

### Estimated tokens saved
**Decision**: Heuristic — for each cache hit, estimate `tokens_saved = len(response.split()) * 1.3`. Displayed as a sum in the TUI.  
**Rationale**: Actual tokenizer adds dependency weight. Heuristic is sufficient for dashboard-level estimates; label it "est." in the UI.

## Risks / Trade-offs

- **SQLite write contention under concurrent load** → Mitigation: `aiosqlite` serializes writes; acceptable for single-node deployment. If concurrency becomes an issue, switch to a write queue before PostgreSQL migration.
- **Fire-and-forget tasks can be silently dropped on crash** → Mitigation: Log errors from the task; accept minor data loss during crashes as a known limitation of the non-critical instrumentation path.
- **`org`/`department` fields depend on request context** → Mitigation: Extract from `ChatRequest` fields (already planned in org API key work). For requests without org/department, default to `"default"` / `"default"`.
- **SQLite file grows unboundedly** → Mitigation: Document a manual vacuum/truncate procedure; automatic pruning is out of scope.

## Migration Plan

1. Add `aiosqlite` to `pyproject.toml` via `uv add aiosqlite`
2. Add `rich` if not already present via `uv add rich`
3. `RequestLogger` creates the `requests` table on first connection (idempotent `CREATE TABLE IF NOT EXISTS`)
4. No existing data to migrate — purely additive
5. Rollback: remove the `asyncio.create_task(logger.log(...))` calls from the router; the table remains but is inert
