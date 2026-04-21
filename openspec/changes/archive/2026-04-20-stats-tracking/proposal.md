## Why

DejaQ routes and caches LLM requests but currently has no visibility into how those savings manifest — there's no way to see cache hit rates, latency trends, or model routing distribution per org or department. Usage stats are the core value proof for any cost-optimization platform.

## What Changes

- Every request through the chat pipeline (HTTP + WebSocket) is recorded to a local SQLite database with org, department, timestamp, latency, cache outcome, and routing metadata
- A new `stats` CLI command renders a Rich TUI showing per-department and org-wide summaries: total requests, cache hit rate, avg latency, estimated tokens saved, easy/hard miss breakdown with models used
- Tables are color-coded: hits in green, misses in amber, errors in red
- SQLite is used (no new infrastructure; PostgreSQL migration is already planned separately)

## Capabilities

### New Capabilities

- `request-logging`: Records each gateway request to SQLite — org, department, timestamp, latency ms, cache hit/miss, difficulty classification (easy/hard), and model used on misses
- `stats-cli`: CLI command `dejaq stats` that queries the SQLite log and renders a Rich TUI dashboard with per-department rows and an org-wide total row

### Modified Capabilities

- `openai-chat-completions`: Chat pipeline (HTTP POST /chat and WS /ws/chat) must emit a log record after each request completes, capturing all required fields

## Impact

- **New files**: `app/services/request_logger.py`, `app/cli/stats.py` (or `cli.py` entry point), `app/db/stats.db` (runtime artifact)
- **Modified**: `app/routers/chat.py` — instrument both HTTP and WebSocket handlers to call the logger after each response
- **Dependencies**: `rich` (already likely present or trivial to add); `aiosqlite` for async SQLite writes
- **No breaking changes** — purely additive instrumentation + new CLI entry point
