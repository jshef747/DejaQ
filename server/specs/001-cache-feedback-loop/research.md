# Research: Cache Feedback Loop

**Feature**: 001-cache-feedback-loop
**Date**: 2026-02-19

---

## Decision 1: Where to store `feedback_score` and `flagged`

**Decision**: Store `feedback_score` (int) and `flagged` (bool) in ChromaDB document metadata. Do not use Redis for scores.

**Rationale**:
- ChromaDB already stores arbitrary key-value metadata alongside each document. Adding `feedback_score` and `flagged` requires no new infrastructure.
- Scores are read during `check_cache` at query time — the ChromaDB `.query()` result already returns `metadatas` in the same round-trip. Adding `include=["metadatas"]` gives us the score with zero extra lookups.
- Scores must survive service restarts: ChromaDB PersistentClient persists to disk automatically. Redis data is typically in-memory and would be lost on restart unless persistence is explicitly configured.
- ChromaDB supports partial metadata updates via `collection.update(ids=[id], metadatas=[{...}])`. This is synchronous but fast (no model inference involved, sub-millisecond).

**Alternatives considered**:
- Redis for scores: Faster atomic increments (`INCR`), but requires a second data store for the same fact. Scores and entries would need manual sync. Rejected because it adds complexity with no meaningful performance benefit at this scale.
- Separate PostgreSQL table: Planned but not yet implemented in the project. Out of scope for this feature.

---

## Decision 2: Where to store feedback event history

**Decision**: Store feedback event history in Redis as a JSON-encoded list under key `feedback:{entry_id}`. Use `RPUSH` to append events, `LRANGE` to retrieve all.

**Rationale**:
- Redis is already in the stack (Celery broker/backend). No new infrastructure needed.
- Feedback history is read-heavy for the `/feedback` GET endpoint and append-only for writes. Redis lists map naturally to this access pattern.
- History is diagnostic/operational data — acceptable to lose on Redis restart in a dev environment. In production, Redis persistence (AOF/RDB) can be enabled.
- Storing history in ChromaDB metadata is impractical: ChromaDB metadata values must be scalar types (string, int, float, bool). A list of events cannot be stored natively.

**Alternatives considered**:
- Serialize event list to a JSON string in ChromaDB metadata: works but gets unwieldy as event count grows; ChromaDB metadata is not designed for large string blobs.
- In-process list (Python dict): Lost on restart, violates FR-014. Rejected.

---

## Decision 3: Dynamic similarity threshold per entry

**Decision**: During `check_cache`, after the query result is returned, read `feedback_score` from the matched entry's metadata. If `feedback_score >= TRUSTED_THRESHOLD` AND the entry is not flagged, use `RELAXED_SIMILARITY` (0.20) instead of `SIMILARITY_THRESHOLD` (0.15).

**Implementation note**: ChromaDB `.query()` must include `metadatas` in the `include` list. The threshold comparison runs after the distance is known but before returning the answer.

**Rationale**:
- Trusted entries (consistently positive ratings) have proven their value. Widening their match window directly improves cache hit rate — the primary success metric.
- The check is a simple conditional on data already in memory (metadata returned with the query). No extra I/O.

**Threshold values** (configurable via env vars):
| Config Key | Default | Meaning |
|------------|---------|---------|
| `DEJAQ_TRUSTED_THRESHOLD` | `3` | Minimum net-positive score to trigger relaxed matching |
| `DEJAQ_FLAG_THRESHOLD` | `-3` | Score at which entry is flagged (no longer served) |
| `DEJAQ_AUTO_DELETE_THRESHOLD` | `-5` | Score at which entry is deleted from ChromaDB |
| `DEJAQ_TRUSTED_SIMILARITY` | `0.20` | Cosine distance ceiling for trusted entries |
| `DEJAQ_SUPPRESSION_TTL` | `300` | Seconds to hold suppression key in Redis |

---

## Decision 4: Suppression of pending storage (FR-009)

**Decision**: When negative feedback arrives for a cache miss response, write `skip:{doc_id}` to Redis with a TTL of `SUPPRESSION_TTL` seconds. The `generalize_and_store_task` (Celery) and the in-process `_generalize_and_store` fallback both check for this key before calling `store_interaction`. If the key exists, they skip storage and return early.

**Rationale**:
- The doc_id is deterministic: `hashlib.sha256(clean_query.encode()).hexdigest()[:16]` — the same formula used by `MemoryService.store_interaction`. It can be pre-computed in the router without calling ChromaDB.
- The suppression window (default 5 min) covers typical Phi-3.5 inference time + network round-trip for the feedback call. After the TTL, the key auto-expires and the decision no longer matters (storage already happened or was never triggered).
- This is a best-effort mechanism. If feedback arrives after the TTL, the entry was already stored and the normal negative feedback flow (decrement score, flag if needed) applies — explicitly handled by US4 acceptance scenario 2.

**Flagged as potentially over-engineered**: The suppression window is narrow. Phi-3.5 inference takes a few seconds; a human submitting feedback will rarely beat it. However, the implementation is minimal (one Redis SETEX + one GET per task) and preserves the spec requirement. Keeping it in scope.

---

## Decision 5: Score updates are synchronous in the feedback endpoint

**Decision**: `feedback_score` updates (ChromaDB metadata update + Redis event append) happen synchronously inside the POST `/cache/entries/{id}/feedback` handler. They are NOT dispatched to Celery.

**Rationale**:
- The caller is waiting for the updated score in the response. Deferring the update would mean the response contains stale data, making the endpoint misleading.
- ChromaDB metadata updates are fast (no inference, no network, sub-millisecond disk write).
- Dispatching to Celery adds overhead (serialization, broker roundtrip, worker pickup) for an operation that is faster than the overhead itself.
- Constitution Principle II ("Non-Blocking User Experience") applies to the *chat* response latency, not to utility endpoints. A feedback endpoint that takes a few milliseconds to update metadata is acceptable.

**Over-engineering avoided**: Celery task for score updates is rejected. Inline update is correct.

---

## Decision 6: `check_cache` return type change

**Decision**: Change `MemoryService.check_cache()` return type from `Optional[str]` to `Optional[tuple[str, str]]` — `(generalized_answer, entry_id)`. Return `None` for cache miss (unchanged).

**Rationale**:
- The router needs the entry_id to include `cache_entry_id` in ChatResponse (FR-001).
- On cache hit, the entry_id comes from ChromaDB query results. On cache miss, the entry_id can be pre-computed from the clean_query hash.
- Callers in `chat.py` already do `if cached_answer is not None:` — the tuple unpack `cached_answer, entry_id = memory.check_cache(...)` is a minimal change.
- Internal change: no public API surface affected (MemoryService is not exposed to clients).

---

## Decision 7: `cache_entry_id` in ChatResponse for cache misses

**Decision**: For cache misses, pre-compute `doc_id = hashlib.sha256(clean_query.encode()).hexdigest()[:16]` in the router and include it in the ChatResponse as `cache_entry_id`. This is the same ID the background storage task will use.

**Rationale**:
- The client needs to know which ID to use for feedback, even before the entry is stored.
- The doc_id is deterministic from `clean_query`, so the router can compute it independently.
- If the cache filter decides NOT to cache (`will_cache=False`), `cache_entry_id` is still returned — negative feedback on non-cached responses is a no-op (no entry to update), which the feedback service handles gracefully.

---

## Decision 8: Flagging vs immediate bypass on cache hit negative rating

**Decision**: A single negative rating does NOT immediately bypass the cache. Bypassing only happens when `feedback_score` drops below `FLAG_THRESHOLD` (sets `flagged=True`). A flagged entry is never served regardless of similarity distance.

**Rationale**:
- A single negative rating could reflect user preference or question framing, not a fundamentally wrong answer. Threshold-based flagging is more robust.
- This is consistent with spec FR-006/FR-007: "if confidence_score drops below a defined threshold."
- FR-008 ("force cache miss after negatively rated cache hit") is satisfied: once an entry accumulates enough negative ratings to cross the threshold and get flagged, ALL future queries that would match it are treated as misses.

---

## Codebase integration summary

| Existing Component | Change Required |
|--------------------|-----------------|
| `memory_chromaDB.py` | Add `feedback_score`, `flagged` to stored metadata; update `check_cache` to return `(answer, id)` and apply dynamic threshold + flagged check; add `get_entry_metadata`, `update_entry_metadata` |
| `schemas/chat.py` | Add `cache_entry_id: Optional[str]` to ChatResponse |
| `routers/chat.py` | Unpack `(answer, entry_id)` from `check_cache`; compute doc_id for miss case; include `cache_entry_id` in both responses |
| `tasks/cache_tasks.py` | Add suppression check (`skip:{doc_id}` Redis key) before calling `store_interaction` |
| `config.py` | Add threshold constants |
| `celery_app.py` | No changes needed |
| `main.py` | Register new feedback router |
