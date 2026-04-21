## 1. Schema & Config

- [x] 1.1 Add `FeedbackRequest` Pydantic schema to `app/schemas/` (`response_id: str`, `rating: Literal["positive", "negative"]`, `comment: str | None`)
- [x] 1.2 Add `DEJAQ_EVICTION_FLOOR` to `app/config.py` as `EVICTION_FLOOR = float(os.getenv("DEJAQ_EVICTION_FLOOR", "-5.0"))` with try/except fallback logging a warning on invalid value

## 2. ChromaDB — Score, Hit-Count & negative_count Support

- [x] 2.1 Update `memory_chromaDB.py` `store()` to write `score: 0.0`, `hit_count: 0`, and `negative_count: 0` into metadata on every new document
- [x] 2.2 Update `memory_chromaDB.py` `get_cache()` to fetch top-5 candidates (instead of 1), filter to cosine ≤ 0.15, sort by `score` descending (absent score treated as 0.0), return best match
- [x] 2.3 Add `increment_hit_count(doc_id: str)` method to `memory_chromaDB.py` — reads current `hit_count`, writes back +1
- [x] 2.4 Add `update_score(doc_id: str, delta: float) -> float` method to `memory_chromaDB.py` — reads current `score` and `negative_count`, applies delta to score, increments `negative_count`, writes back, returns new score; raises `KeyError` if doc not found
- [x] 2.5 Add `get_negative_count(doc_id: str) -> int` method — returns `negative_count` metadata field (0 if absent); raises `KeyError` if doc not found
- [x] 2.6 Add `delete_entry(doc_id: str)` method — deletes a single document by ID; raises `KeyError` if not found
- [x] 2.7 Add `evict_below_floor(floor: float) -> int` method to `memory_chromaDB.py` — uses ChromaDB `where` filter `{"score": {"$lt": floor}}`, deletes matching docs, returns count deleted

## 3. Request Logging — response_id Column

- [x] 3.1 Update `request_logger.py` `_CREATE_TABLE` to include `response_id TEXT` column; add `ALTER TABLE requests ADD COLUMN response_id TEXT` on startup guarded by `PRAGMA table_info` check or catching `OperationalError`
- [x] 3.2 Update `log()` signature to accept optional `response_id: str | None = None`; include in INSERT
- [x] 3.3 Update `generalize_and_store_task` in `cache_tasks.py` to return `doc_id` from `store_interaction()` in its result dict — `store_interaction()` must also be updated to return the computed `doc_id`
- [x] 3.4 Update `openai_compat.py` to build `response_id = f"{cache_namespace}:{doc_id}"` and pass it to `log()` on cache hit and on stored cache miss; pass `None` when filter blocks

## 4. response_id as HTTP Response Header

- [x] 4.1 In `openai_compat.py`, add `X-DejaQ-Response-Id: <namespace>:<doc_id>` response header on cache hit and stored cache miss for both streaming and non-streaming responses; omit header when filter blocks
- [x] 4.2 Update CLAUDE.md env var table to document `X-DejaQ-Response-Id` header behavior

## 5. Feedback Log (SQLite)

- [x] 5.1 Add `feedback_log` table initialization to `request_logger.py` startup — columns: `id` (PK autoincrement), `ts` (text), `response_id` (text), `org` (text), `department` (text), `rating` (text), `comment` (text nullable)
- [x] 5.2 Add `log_feedback(response_id, org, dept, rating, comment)` async function to `request_logger.py` — fire-and-forget via `asyncio.create_task`

## 6. Feedback Router

- [x] 6.1 Create `app/routers/feedback.py` with `POST /v1/feedback` endpoint — parse `response_id` by splitting on first `:` into `(namespace, doc_id)` (return 422 if malformed); call `get_memory_service(namespace)`; read `department` from `X-DejaQ-Department` header (default `"default"`), `org` from `request.state.org_slug`; call `log_feedback()` fire-and-forget; on negative: if `get_negative_count()==0` call `delete_entry()` return `{"status":"deleted"}`; else call `update_score(-2.0)` return `{"status":"ok","new_score":<float>}`; on positive call `update_score(+1.0)`; return 404 on `KeyError`
- [x] 6.2 Register `feedback` router in `app/main.py`

## 7. Cache Hit — Increment hit_count

- [x] 7.1 In `openai_compat.py` cache-hit branch, call `increment_hit_count(doc_id)` as a fire-and-forget `asyncio.create_task` (non-blocking)

## 8. Celery — Eviction Beat Task

- [x] 8.1 Add `evict_low_score_entries` Celery task to `app/tasks/cache_tasks.py` — iterates all namespaces via `_pool` keys, calls `evict_below_floor(config.EVICTION_FLOOR)` on each, logs total deleted count at INFO
- [x] 8.2 Add `beat_schedule` to `celery_app.conf.update()` in `app/celery_app.py` — import `crontab` from `celery.schedules`, schedule `evict_low_score_entries` every 30 minutes

## 9. Stats TUI — Cache Health Panel

- [x] 9.1 Add **Cache Health** panel to the Rich TUI showing: total cached entries, score distribution buckets (< 0, 0, > 0), count of entries below eviction floor

## 10. Verification

- [x] 10.1 Manual smoke test: send a chat request, verify `X-DejaQ-Response-Id` header present; POST positive feedback, verify score increments; POST first negative feedback, verify immediate deletion; verify `feedback_log` row written with correct org/dept; repeat with streaming mode and confirm header is present
- [x] 10.2 Verify `dejaq-admin stats` renders Cache Health panel without errors  
- [x] 10.3 Verify existing DB without `response_id` column is auto-migrated on startup
