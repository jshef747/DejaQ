## Why

The semantic cache stores responses indefinitely without any signal about quality. A bad or hallucinated response can be served repeatedly to future users with no mechanism to surface or remove it. Adding a thumbs-up / thumbs-down feedback loop lets the cache self-improve over time: good responses rise in priority, bad ones decay and eventually get evicted.

## What Changes

- New `POST /v1/feedback` endpoint — accepts `response_id`, a `rating` (`positive` / `negative`), and optional free-text comment
- Each cached entry in ChromaDB gains a `score` metadata field (float, starts at 0.0) and a `hit_count` field
- On cache hit, `hit_count` increments; on positive feedback `score` increases; on negative feedback `score` decreases
- Cache retrieval sorts candidates by score (descending) when multiple entries fall within the cosine-similarity threshold
- Background Celery task `evict_low_score_entries` runs periodically and deletes entries whose score drops below a configurable floor (default −5.0)
- `dejaq-admin stats` dashboard gains a **Cache Health** panel showing score distribution and eviction counts
- `request_logger` stores `response_id` so the client can pass it back to the feedback endpoint

## Capabilities

### New Capabilities

- `response-feedback`: Endpoint + logic for submitting thumbs-up / thumbs-down feedback on a cached response; updates score metadata in ChromaDB
- `cache-score-ranking`: When multiple cached entries match a query, rank by score so the highest-quality response is returned first
- `cache-eviction`: Periodic background task that evicts entries whose score falls below the configured floor

### Modified Capabilities

- `request-logging`: Must store and return `response_id` (the ChromaDB document ID) so clients can reference it in feedback submissions

## Impact

- **`app/routers/`** — new `feedback.py` router
- **`app/services/memory_chromaDB.py`** — score/hit_count metadata r/w; ranked retrieval
- **`app/tasks/cache_tasks.py`** — new `evict_low_score_entries` periodic Celery task
- **`app/services/request_logger.py`** — add `response_id` column to SQLite log
- **`app/main.py`** — register new router; schedule periodic eviction beat
- **`cli/stats.py`** — Cache Health panel
- **`app/schemas/`** — new `FeedbackRequest` schema
- **No breaking changes** to existing `/v1/chat/completions` contract; `response_id` is additive in the response body
