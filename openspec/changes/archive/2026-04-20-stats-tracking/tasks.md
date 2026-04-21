## 1. Dependencies & Config

- [x] 1.1 Add `aiosqlite` and `rich` to `pyproject.toml` via `uv add aiosqlite rich`
- [x] 1.2 Add `DEJAQ_STATS_DB` env var to `app/config.py` (default: `dejaq_stats.db`)

## 2. Request Logger Service

- [x] 2.1 Create `app/services/request_logger.py` with a `RequestLogger` class that holds an `aiosqlite` connection
- [x] 2.2 Implement `RequestLogger.init()` async method: opens/creates the DB and runs `CREATE TABLE IF NOT EXISTS requests (...)` with the full schema
- [x] 2.3 Implement `RequestLogger.log(org, department, latency_ms, cache_hit, difficulty, model_used)` async method that inserts one row
- [x] 2.4 Implement `RequestLogger.close()` async method for clean shutdown
- [x] 2.5 Expose a module-level singleton `request_logger = RequestLogger()` and initialize it in `app/main.py` startup / shutdown hooks

## 3. Instrument Chat Handlers

- [x] 3.1 In `app/routers/chat.py` HTTP handler (`POST /chat`): capture `start = time.monotonic()` before pipeline, compute `latency_ms` before returning, then `asyncio.create_task(request_logger.log(...))`
- [x] 3.2 In `app/routers/chat.py` WebSocket handler (`WS /ws/chat`): same instrumentation per message turn
- [x] 3.3 Extract `org` and `department` from `request.state` if present (set by API key middleware), else default to `"default"`
- [x] 3.4 Pass `difficulty` and `model_used` from the router's existing routing decision variables into the log call (use `None` for cache hits)

## 4. Stats CLI

- [x] 4.1 Create `app/cli/` directory and `app/cli/__init__.py`
- [x] 4.2 Create `app/cli/stats.py` with a `__main__` block that reads `DEJAQ_STATS_DB` path
- [x] 4.3 Implement sync SQLite query (via `sqlite3` stdlib — no async needed in CLI) to aggregate: total requests, hits, misses, avg latency, easy/hard miss counts, distinct models used, per `(org, department)` group
- [x] 4.4 Build Rich `Table` with columns: Department, Requests, Hit Rate, Avg Latency (ms), Est. Tokens Saved, Easy Misses, Hard Misses, Models Used
- [x] 4.5 Populate one row per `(org, department)` pair; color each row green if hit rate ≥ 50%, yellow otherwise
- [x] 4.6 Append a bold Total row aggregating all departments with the same color logic
- [x] 4.7 Handle edge cases: DB not found (print error + exit 1), zero rows (print "No requests recorded yet")
- [x] 4.8 Render the table via `rich.console.Console().print(table)`

## 5. Verification

- [x] 5.1 Start the server, send 5+ chat requests via `index.html` or curl, then run `uv run python -m app.cli.stats` and confirm rows appear
- [x] 5.2 Verify cache hits show green and `difficulty=NULL` in the DB
- [x] 5.3 Verify cache misses show amber and correct `difficulty`/`model_used` values
- [x] 5.4 Confirm latency on the hot path is not meaningfully increased (eyeball the response time in the UI)
