# Session Handoff — DejaQ

## Goal

Fix department delete/recreate stale stats bug: when a department is deleted and recreated with the same name, the dashboard was showing the previous department's statistics.

---

## Current Progress — COMPLETE (pending user verification)

### What was diagnosed

1. **Stats SQLite (`server/dejaq_stats.db`)** — `requests`, `feedback_log`, and `response_interactions` rows were never deleted on department delete. All three tables key by plain `org`/`department` slug strings with no FK/cascade. `slugify_name` is deterministic, so recreating a dept with the same name resurfaces all old rows.
2. **ChromaDB** — `_delete_chroma_namespace` already deleted collections on dept delete but swallowed all exceptions silently, so silent failures left the old namespace intact.
3. **Pre-existing orphans** — The user's specific symptom (dept `demo|demo`, requests dated 2026-05-06/07, still showing today) was caused by rows from a dept deleted *before* the cleanup code existed. The delete-side fix alone wouldn't catch these.

### What was shipped

Two rounds of edits to **`server/app/services/admin_service.py`**:

**Round 1 (delete-side fix):**
- Added `_delete_dept_stats(org_slug, dept_slug)` helper — sync `sqlite3` connection to `STATS_DB_PATH`, DELETEs from `requests` (keyed `org`/`department`), `feedback_log` (same), and `response_interactions` (keyed `org_slug`/`department`). Best-effort, logs warning on failure.
- `delete_department` now calls `_delete_chroma_namespace(namespace)` then `_delete_dept_stats(org_slug, dept_slug)` after the DB delete.
- `delete_org` now carries `(dept_slug, cache_namespace)` pairs per child dept and calls both cleanups in the loop.
- `_delete_chroma_namespace` now does a post-delete re-check and logs `error` if the collection still exists after delete.

**Round 2 (idempotent create — the actual fix for current user symptom):**
- `create_department` now also calls `_delete_chroma_namespace(item.cache_namespace)` and `_delete_dept_stats(org_slug, item.slug)` *after* the session commits. This wipes any orphan state from prior incarnations on every create — no-op when nothing exists.
- Session block restructured: `item = _dept_item(dept, org_slug)` captured inside the `with`, cleanup called after `with` block exits, then `return item`.

### Current DB state

As of this session: `demo|demo` rows (4 requests, 2 feedback) are still in the DB because the user hasn't deleted + recreated the dept yet under the new code. The fix will wipe them on the next `POST /admin/v1/orgs/demo/departments` for a dept named "demo".

---

## What Worked

- Adding defensive wipe on `create_department` — handles pre-existing orphans even if the delete never ran the cleanup
- Sync `sqlite3` in an otherwise-sync admin service — simple, no async bridge needed
- Reusing `_delete_chroma_namespace` pattern exactly for consistency

## What Didn't Work / Decisions Made

- **Delete-side fix alone was insufficient** — the user's orphans pre-dated the fix, so delete-on-create was needed as the true idempotency guarantee
- **Did not add a CLI `clean-orphan-stats` command** — the create-side wipe makes it unnecessary for normal operations; if ever needed for bulk cleanup it would be a future addition

---

## Next Steps

### Verify the fix works

1. In the dashboard, delete the `demo` dept and recreate it with the same name.
2. Confirm stats show zero:
   ```bash
   cd server
   sqlite3 dejaq_stats.db "SELECT COUNT(*) FROM requests WHERE org='demo' AND department='demo';"
   sqlite3 dejaq_stats.db "SELECT COUNT(*) FROM feedback_log WHERE org='demo' AND department='demo';"
   sqlite3 dejaq_stats.db "SELECT COUNT(*) FROM response_interactions WHERE org_slug='demo' AND department='demo';"
   ```
   All should return `0`.
3. Confirm uvicorn log shows:
   ```
   Cleared stats rows for demo/demo
   ```

### Remaining items from previous session (Responses API)

The previous session shipped `POST /v1/responses`. Still pending:

- **Smoke test** the Responses API end-to-end — stack was not running during that session.
- **Add tests** for `/v1/responses` — non-streaming shape, streaming event sequence, `previous_response_id` rejection, `instructions` → system message mapping. Mirror `tests/test_openai_compat_smoke.py`.
- **Frontend badge** — `DepartmentsClient.tsx:305` shows a static `POST /v1/chat/completions` label; update to show both endpoints.

---

## Key Files

| File | Role |
|------|------|
| `server/app/services/admin_service.py` | `_delete_dept_stats`, `_delete_chroma_namespace` (tightened), `delete_department`, `delete_org`, `create_department` — all modified |
| `server/dejaq_stats.db` | Live stats SQLite — `requests`, `feedback_log`, `response_interactions` tables |
| `server/app/services/request_logger.py` | Stats DB schema reference |
| `server/app/services/response_registry.py` | `response_interactions` table schema (uses `org_slug` col, not `org`) |
| `server/app/services/stats_service.py` | `department_stats()` — reads from `requests` by `org`/`department` slug |
| `server/app/routers/openai_responses.py` | Responses API router (previous session) |
| `server/app/schemas/openai_responses.py` | Responses API Pydantic models (previous session) |
| `server/app/routers/openai_compat.py` | Shared `run_chat_pipeline()` (previous session) |
