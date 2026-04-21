## Context

ChromaDB is the semantic cache store. Each document represents a generalized (tone-neutral) response, identified by an auto-generated UUID. Currently, retrieval returns the single nearest neighbor below cosine distance 0.15 with no quality signal. There is no way to distinguish a frequently-validated response from one that was cached once and never rated.

The system already uses aiosqlite for request logging and Celery + Redis for background tasks, so both are available without new infrastructure.

## Goals / Non-Goals

**Goals:**
- Surface a `response_id` to callers so they can submit feedback
- Persist per-entry score and hit-count inside ChromaDB metadata (no separate DB required)
- Rank multi-match results by score at retrieval time
- Automatically evict entries that decay below a floor
- Log every feedback submission with org/department attribution to SQLite
- Show score distribution in the admin stats TUI

**Non-Goals:**
- Real-time score propagation to running workers (eventual consistency is fine)
- ML-based quality scoring (pure thumbs-up / thumbs-down)
- Public feedback API authentication beyond the existing API-key middleware

## Decisions

### D1 — Store score + hit_count inside ChromaDB metadata

**Decision:** Attach `score: float` and `hit_count: int` directly to each ChromaDB document's metadata dict rather than a separate SQLite table.

**Rationale:** ChromaDB documents already carry arbitrary metadata. A separate table would require a join on `response_id` on every cache hit, adding latency and a second write path. Keeping it co-located with the embedding means the ranker has score available without extra I/O.

**Alternative:** SQLite side-table keyed by `response_id`. Rejected: extra round-trip per cache hit, schema migration overhead, two sources of truth to keep in sync.

### D2 — Score arithmetic: +1 positive; first negative → immediate delete; floor −5.0

**Decision:** Each positive rating adds 1.0 to score. The **first** negative rating immediately deletes the entry from ChromaDB (no score decrement, no waiting for the beat). Subsequent negative ratings on surviving entries (e.g., after a positive rebound) subtract 2.0; entries with score < −5.0 are evicted by the beat. Starting score is 0.0. `negative_count` metadata field tracks how many negative ratings an entry has received.

**Rationale:** A single negative rating is a strong signal that the response is wrong or harmful. Waiting up to 30 minutes for the beat to evict it risks serving the bad response many more times. Immediate delete on first negative eliminates that window entirely. Subsequent negatives use the score system because a positive rating in between suggests the entry is controversial, not clearly bad.

**Alternative:** Configurable weights via env vars. Deferred — can add later without API changes.

### D3 — Ranking: sort by score within cosine-threshold window

**Decision:** When `get_cache()` returns multiple candidates within distance ≤ 0.15, sort by `score` descending and return the top result. Current single-result fast-path is preserved when only one candidate exists.

**Rationale:** ChromaDB supports `n_results > 1` already. Fetching top-5 within threshold adds negligible latency vs. a single-result query on a local HTTP client.

### D4 — Periodic eviction via Celery beat (not request-time)

**Decision:** A Celery beat task runs every 30 minutes to scan and delete sub-floor entries. Eviction does not happen at request time.

**Rationale:** Request-time eviction would add latency on every cache miss scan. Celery beat is already available; a 30-minute lag on eviction is acceptable for a quality signal that accumulates over hours/days.

**Alternative:** Evict lazily on cache hit when the returned entry's score is below floor. Rejected: a sub-floor entry could still be served once before eviction.

### D5 — `response_id` surfaced as HTTP response header; encodes namespace + doc_id

**Decision:** `response_id` is returned in the `X-DejaQ-Response-Id` HTTP response header (not the JSON body). Format: `<namespace>:<doc_id>` where `doc_id` is the 16-char hex string computed by `store_interaction()` (SHA256 of normalized query, first 16 chars). Example: `acme__eng:a3f2b1c9d7e4f8a2`. The feedback endpoint splits on the first `:` to recover namespace and doc_id, then calls `get_memory_service(namespace)`.

**Rationale:** Using a header works identically for both streaming and non-streaming responses — headers are sent before any body content, so the client always has `response_id` available. Putting it in the JSON body would require modifying streaming SSE chunks. The `doc_id` is a deterministic hash of the normalized query, so the same normalized query always maps to the same `response_id` — feedback on any response for that query affects the shared cache entry, which is the correct behavior.

**Alternative:** Embed `response_id` in the JSON body for non-streaming and in a final SSE chunk for streaming. Rejected: two separate code paths, more complex client handling.

**Alternative:** Store `(doc_id → namespace)` in the `requests` SQLite log and look it up on feedback. Rejected: adds a DB round-trip on every feedback POST.

### D6 — Feedback attribution via SQLite `feedback_log` table

**Decision:** Every feedback submission is logged to a new `feedback_log` table in the existing `dejaq_stats.db` SQLite database with columns: `id` (PK), `ts` (ISO-8601 UTC), `response_id` (text), `org` (text), `department` (text), `rating` (text), `comment` (text, nullable). The write is fire-and-forget via `asyncio.create_task`, same pattern as `request_logger`.

**Rationale:** `org` is available via `request.state.org_slug` (set by middleware). `department` is not set by middleware — the feedback endpoint reads it from the `X-DejaQ-Department` header directly, same pattern as `openai_compat.py`. Logging them costs nothing extra and enables per-org/dept analytics.

**Alternative:** Store attribution in ChromaDB metadata alongside the score. Rejected: ChromaDB metadata is per-document, not per-feedback-event; storing a list of events in metadata is awkward and not queryable.

## Risks / Trade-offs

- **Metadata update contention** — ChromaDB `update()` is not atomic; `increment_hit_count()` and `update_score()` use a read-modify-write pattern (get metadata → apply delta → write back) that can lose concurrent updates. → Mitigation: Feedback is low-frequency; eventual consistency is acceptable. Redis-based locking is the upgrade path if needed.
- **Deterministic `doc_id`** — `doc_id` is SHA256 of the normalized query (first 16 hex chars), so the same normalized query always maps to the same cache entry and `response_id`. Feedback on any response for that query affects the shared entry — this is intentional.
- **Score manipulation** — A caller could spam positive feedback on their own cached entries. → Mitigation: Feedback requires a valid API key (existing middleware); rate limiting can be added in a follow-up.
- **ChromaDB scan cost for eviction** — Fetching all documents to filter by score could be slow if the collection grows large. → Mitigation: ChromaDB `where` filter on metadata supports `$lt` comparisons; only sub-floor documents are fetched, not the full collection.
- **`response_id` staleness** — If an entry is evicted between a chat response and the client's feedback POST, the feedback endpoint receives an unknown ID. → Mitigation: Return a 404 with a clear error message; no silent failure.

## Migration Plan

1. Deploy new code — existing ChromaDB entries lack `score`/`hit_count` metadata. The retrieval code treats missing fields as defaults (0.0 / 0). No migration script needed.
2. New entries written after deploy carry the fields from the start.
3. Celery beat schedule added to `celery_app.py`; workers must be restarted to pick up the new beat entry.
4. `request_logger` adds `response_id` column via an `ALTER TABLE ... ADD COLUMN` guarded by `IF NOT EXISTS` on startup.

**Rollback:** Remove the feedback router, revert `memory_chromaDB.py` to single-result retrieval, remove the beat entry. Existing metadata fields in ChromaDB are ignored harmlessly.

## Open Questions

- Should negative feedback trigger immediate re-normalization of the query (re-cache with a different response) or just eviction? — Deferred; eviction-only is simpler for v1.
- Stats TUI: aggregate score distribution only (no per-entry rows).
