# Tasks: Cache Feedback Loop

**Input**: Design documents from `/specs/001-cache-feedback-loop/`
**Prerequisites**: plan.md ✅ | spec.md ✅ | research.md ✅ | data-model.md ✅ | contracts/ ✅ | quickstart.md ✅

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks in this phase)
- **[US#]**: User story this task delivers (maps to spec.md priorities)

---

## Phase 1: Setup

**Purpose**: Add configuration constants that every downstream phase depends on. No logic — just constants.

- [x] T001 Add 5 feedback threshold constants to `app/config.py`: `FEEDBACK_TRUSTED_THRESHOLD=3`, `FEEDBACK_FLAG_THRESHOLD=-3`, `FEEDBACK_AUTO_DELETE_THRESHOLD=-5`, `FEEDBACK_TRUSTED_SIMILARITY=0.20`, `FEEDBACK_SUPPRESSION_TTL=300` — each overridable via env var (pattern: `int(os.getenv("DEJAQ_X", "N"))`)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core data-layer changes that ALL user stories build on. No user story work can begin until this phase is complete.

**⚠️ CRITICAL**: Phases 3–7 are blocked until T002–T009 are all done.

- [x] T002 [P] Create `app/schemas/feedback.py` with four Pydantic v2 models: `FeedbackRequest(value: Literal["positive","negative"], conversation_id: Optional[str])`, `FeedbackResponse(entry_id, feedback_score: int, flagged: bool, deleted: bool, status: str)`, `FeedbackEvent(direction: str, timestamp: datetime)`, `FeedbackHistoryResponse(entry_id, feedback_score: int, flagged: bool, events: list[FeedbackEvent])`
- [x] T003 [P] Add `cache_entry_id: Optional[str] = Field(None, ...)` to `ChatResponse` in `app/schemas/chat.py`
- [x] T004 Update `MemoryService.store_interaction()` in `app/services/memory_chromaDB.py` to add `"feedback_score": 0` and `"flagged": 0` to the metadata dict passed to `_collection.upsert()`
- [x] T005 Update `MemoryService.check_cache()` in `app/services/memory_chromaDB.py`: add `include=["documents","metadatas","distances"]` to the query call; on a result within threshold, check `metadatas[0][0].get("flagged", 0) == 1` — if flagged, log and return `None`; change return type from `Optional[str]` to `Optional[tuple[str, str]]` and return `(answer, entry_id)` where `entry_id = results["ids"][0][0]`
- [x] T006 Add `get_entry_metadata(self, entry_id: str) -> Optional[dict]` method to `MemoryService` in `app/services/memory_chromaDB.py`: call `_collection.get(ids=[entry_id], include=["metadatas"])`, return `result["metadatas"][0]` if found, `None` if not
- [x] T007 Add `update_entry_metadata(self, entry_id: str, metadata: dict) -> bool` method to `MemoryService` in `app/services/memory_chromaDB.py`: call `_collection.update(ids=[entry_id], metadatas=[metadata])`; wrap in try/except; log on failure; return True/False
- [x] T008 Update HTTP `/chat` endpoint in `app/routers/chat.py`: add `import hashlib` and module-level helper `def _compute_doc_id(q): return hashlib.sha256(q.encode()).hexdigest()[:16]`; unpack `cache_result = memory.check_cache(clean_query)` as `(cached_answer, entry_id) = cache_result if cache_result else (None, None)`; on hit pass `cache_entry_id=entry_id`; on miss pass `cache_entry_id=_compute_doc_id(clean_query) if will_cache else None` — in both `ChatResponse` returns
- [x] T009 Apply the same `check_cache` unpacking and `cache_entry_id` inclusion to the WebSocket `/ws/chat` handler in `app/routers/chat.py` (mirrors T008 changes in the WebSocket response construction block)

**Checkpoint**: All cache responses now carry `cache_entry_id`. Foundation ready — user story phases can begin.

---

## Phase 3: User Story 1 — Submit Feedback on a Response (Priority: P1) 🎯 MVP

**Goal**: API consumers can POST a thumbs-up or thumbs-down rating tied to a response's `cache_entry_id`. The entry's `feedback_score` updates and the new score is returned.

**Independent Test**: Send a `/chat` request, note `cache_entry_id` in the response, POST to `/cache/entries/{id}/feedback` with `{"value":"positive"}`, verify the response contains `feedback_score: 1` and `status: "ok"`.

- [x] T010 Create `app/services/feedback_service.py` with `FeedbackService` class: `__init__` establishes `redis.Redis.from_url(REDIS_URL, decode_responses=True)` client; `submit_feedback(entry_id, value, conversation_id) -> FeedbackResponse` fetches full metadata via `memory.get_entry_metadata()`, computes `new_score = current + (1 if positive else -1)`, calls `memory.update_entry_metadata()` with the full updated dict, returns `FeedbackResponse(entry_id, feedback_score=new_score, flagged=False, deleted=False, status="ok")`; if entry not found returns `FeedbackResponse(status="not_found", feedback_score=0, flagged=False, deleted=False)`; add module-level `get_feedback_service()` singleton factory following the existing pattern in `app/services/`
- [x] T011 [P] Create `app/routers/feedback.py` with `router = APIRouter()`, module-level `feedback_svc = get_feedback_service()`, and `@router.post("/cache/entries/{entry_id}/feedback", response_model=FeedbackResponse)` endpoint that calls `feedback_svc.submit_feedback(entry_id, request.value, request.conversation_id)`; log at `logging.getLogger("dejaq.router.feedback")`
- [x] T012 Register the feedback router in `app/main.py`: add `from app.routers import feedback` and `app.include_router(feedback.router)` after the existing `app.include_router(chat.router)` line
- [x] T013 [P] Update `index.html`: (a) add `.feedback-btns`, `.feedback-btn`, `.feedback-btn:hover:not(:disabled)`, `.feedback-btn.selected-positive`, `.feedback-btn.selected-negative`, `.feedback-btn:disabled`, and `.feedback-score` CSS rules inside the `<style>` block after `.badge-hard`; (b) add `async function submitFeedback(entryId, value, thumbUpBtn, thumbDownBtn, scoreEl)` to the `<script>` block — immediately disables both buttons, POSTs to `/cache/entries/{entryId}/feedback`, applies `.selected-positive`/`.selected-negative` class on success and updates `scoreEl.textContent`, re-enables on failure; (c) in `ws.onmessage`, after the badges block, if `data.cache_entry_id` is truthy append a `.feedback-btns` div with a 👍 button, 👎 button, and score `<span>` to `wrapper`
- [x] T014 [P] Create `tests/test_feedback_service.py` with `pytestmark = pytest.mark.no_model`; add `TestScoreMechanics` class with: `test_positive_increments_score` (submit positive, assert score=1), `test_negative_decrements_score` (submit negative, assert score=-1), `test_score_starts_at_zero` (new entry stored via `store_interaction`, assert initial score=0), `test_multiple_ratings_accumulate` (2× positive + 1× negative = 1); use `tmp_path` for MemoryService, patch Redis with `unittest.mock.MagicMock`
- [x] T015 [P] Add `TestCheckCacheReturnType` class to `tests/test_memory_chromadb.py`: `test_check_cache_returns_tuple_on_hit` (assert isinstance(result, tuple) and len==2), `test_check_cache_returns_none_on_miss`, `test_flagged_entry_returns_none` (store entry, set `flagged=1` in metadata via `update_entry_metadata`, assert `check_cache` returns None for exact match)

**Checkpoint**: Feedback submission works end-to-end. Thumbs buttons appear in UI. US1 independently testable.

---

## Phase 4: User Story 2 — Trusted Entries Match More Broadly (Priority: P2)

**Goal**: Cache entries with `feedback_score >= FEEDBACK_TRUSTED_THRESHOLD` use a relaxed similarity ceiling (`FEEDBACK_TRUSTED_SIMILARITY = 0.20`) instead of the default 0.15, increasing cache hit rate for near-match queries.

**Independent Test**: Store an entry, submit 3 positive ratings to reach score=3, send a query that is semantically close but not exact — verify a cache hit is returned where it previously would have been a miss.

- [x] T016 Extend `MemoryService.check_cache()` in `app/services/memory_chromaDB.py`: after the flagged check (T005), read `feedback_score = int(meta.get("feedback_score", 0))`; set `threshold = FEEDBACK_TRUSTED_SIMILARITY if feedback_score >= FEEDBACK_TRUSTED_THRESHOLD else SIMILARITY_THRESHOLD`; replace the hardcoded `SIMILARITY_THRESHOLD` in the distance comparison with this dynamic `threshold`; import `FEEDBACK_TRUSTED_THRESHOLD` and `FEEDBACK_TRUSTED_SIMILARITY` from `app.config`
- [x] T017 [P] Add `TestDynamicThreshold` class to `tests/test_memory_chromadb.py`: `test_trusted_entry_uses_relaxed_threshold` (set `feedback_score=3` in metadata, assert entry is returned for a near-match distance above 0.15 but below 0.20 — mock the ChromaDB result to return distance=0.18); `test_neutral_entry_uses_default_threshold` (same distance=0.18 with `feedback_score=0`, assert `None` returned)

**Checkpoint**: US2 independently verifiable. US1 unaffected.

---

## Phase 5: User Story 3 — Low-Quality Entries Flagged and Removed (Priority: P3)

**Goal**: Entries that accumulate enough negative ratings are marked as unreliable (`flagged=True`) and removed from the cache, preventing bad answers from being served.

**Independent Test**: Store an entry, submit 3 negative ratings (score=-3), verify `flagged=True` in the response; submit 2 more (score=-5), verify `deleted=True`; confirm a subsequent `/chat` query that would match the entry returns a fresh LLM response.

- [x] T018 Extend `FeedbackService.submit_feedback()` in `app/services/feedback_service.py`: after computing `new_score`, add logic: if `new_score <= FEEDBACK_AUTO_DELETE_THRESHOLD` call `memory.delete_entry(entry_id)` and return `FeedbackResponse(..., flagged=True, deleted=True)`; elif `new_score <= FEEDBACK_FLAG_THRESHOLD` set `new_flagged = 1` in the metadata dict before calling `update_entry_metadata`; include `flagged=bool(new_flagged)` in the returned `FeedbackResponse`; import `FEEDBACK_FLAG_THRESHOLD` and `FEEDBACK_AUTO_DELETE_THRESHOLD` from `app.config`
- [x] T019 [P] Add `TestFlagging` class to `tests/test_feedback_service.py`: `test_score_at_flag_threshold_sets_flagged` (score hits -3, assert `FeedbackResponse.flagged == True`, `deleted == False`); `test_score_at_auto_delete_threshold_deletes_entry` (score hits -5, assert `FeedbackResponse.deleted == True`, `memory.get_entry_metadata` returns `None` after deletion); `test_flagged_entry_not_served_by_check_cache` (set `flagged=1`, assert `check_cache` returns `None`)

**Checkpoint**: US3 independently verifiable. US1 and US2 unaffected.

---

## Phase 6: User Story 4 — Negative Feedback Prevents Low-Quality Storage (Priority: P4)

**Goal**: Negative feedback submitted before a cache miss entry finishes background storage cancels that storage, preventing a known-bad response from entering the cache.

**Independent Test**: Send a `/chat` request (cache miss), immediately POST negative feedback for the `cache_entry_id` before Phi-3.5 generalization completes, wait and verify the entry never appears in `/cache/entries`.

- [x] T020 Extend `FeedbackService.submit_feedback()` in `app/services/feedback_service.py` to handle the missing-entry case: add `_set_suppression_flag(self, doc_id: str) -> None` private method that calls `self._redis.setex(f"skip:{doc_id}", FEEDBACK_SUPPRESSION_TTL, "1")`; in `submit_feedback`, when `get_entry_metadata` returns `None` and `value == "negative"`, call `_set_suppression_flag(entry_id)` and return `FeedbackResponse(entry_id=entry_id, feedback_score=0, flagged=False, deleted=False, status="suppressed")`; import `FEEDBACK_SUPPRESSION_TTL` from `app.config`
- [x] T021 [P] Add suppression check to `app/tasks/cache_tasks.py`: add module-level `_is_suppressed(clean_query: str) -> bool` function that imports `redis`, computes `doc_id = hashlib.sha256(clean_query.encode()).hexdigest()[:16]`, connects to Redis via `REDIS_URL`, checks `exists(f"skip:{doc_id}")`, returns `False` on `redis.exceptions.RedisError`; at the top of `generalize_and_store_task` body (before calling `_get_services()`), call `if _is_suppressed(clean_query): logger.info(...); return {"status": "suppressed", ...}`
- [x] T022 [P] Add the same `_is_suppressed` check to `_generalize_and_store()` fallback function in `app/routers/chat.py`: import `hashlib`; at the top of the function body add `if _is_suppressed(clean_query): logger.info(...); return` — reuse the same helper logic (or import from a shared location if preferred)
- [x] T023 [P] Add `TestSuppression` class to `tests/test_feedback_service.py`: `test_negative_feedback_on_missing_entry_sets_suppression_flag` (submit negative for nonexistent entry, assert Redis mock called with `setex(f"skip:{entry_id}", ...)` and `status=="suppressed"`); `test_positive_feedback_on_missing_entry_is_noop` (submit positive for nonexistent entry, assert no Redis setex call, assert `status=="not_found"`); `test_suppression_flag_key_format` (assert key is exactly `f"skip:{entry_id}"`)

**Checkpoint**: US4 independently verifiable. Cancellation only possible within the TTL window — documented as expected behavior.

---

## Phase 7: User Story 5 — Inspect Feedback History (Priority: P5)

**Goal**: Operators can retrieve a timestamped log of every rating submitted for a cache entry via GET `/cache/entries/{id}/feedback`.

**Independent Test**: Submit 3 ratings for an entry (2 positive, 1 negative); call `GET /cache/entries/{id}/feedback`; verify response contains exactly 3 events in chronological order with correct `direction` and `timestamp` fields.

- [x] T024 Extend `FeedbackService.submit_feedback()` in `app/services/feedback_service.py` to append a feedback event to Redis: after a successful `update_entry_metadata` call (or after suppression return), call `self._redis.rpush(f"feedback:{entry_id}", json.dumps({"direction": value, "timestamp": datetime.utcnow().isoformat() + "Z"}))`; wrap the rpush in `try/except redis.exceptions.RedisError` — log `logger.warning("Redis unavailable, skipping event history for %s", entry_id)` and continue (do not raise)
- [x] T025 Add `FeedbackService.get_feedback_history(entry_id: str) -> FeedbackHistoryResponse` method to `app/services/feedback_service.py`: call `memory.get_entry_metadata(entry_id)` — raise `HTTPException(404)` if None; fetch events via `self._redis.lrange(f"feedback:{entry_id}", 0, -1)`; parse each JSON string into `FeedbackEvent`; on `redis.exceptions.RedisError` log warning and use empty list; return `FeedbackHistoryResponse(entry_id=entry_id, feedback_score=int(meta.get("feedback_score",0)), flagged=bool(meta.get("flagged",0)), events=[...])`
- [x] T026 Add `@router.get("/cache/entries/{entry_id}/feedback", response_model=FeedbackHistoryResponse)` endpoint to `app/routers/feedback.py` that calls `feedback_svc.get_feedback_history(entry_id)`; propagate `HTTPException(404)` from the service
- [x] T027 Audit all Redis calls in `app/services/feedback_service.py` that are not yet wrapped (e.g., `__init__` connection establishment); ensure the constructor catches `redis.exceptions.RedisError` and logs a warning rather than crashing FastAPI startup — store `self._redis = None` on failure and add a `_redis_available()` guard before each Redis operation
- [x] T028 [P] Add `TestFeedbackHistory` class to `tests/test_feedback_service.py`: `test_history_returns_events_in_order` (submit 3 ratings, assert events list length=3 in submission order); `test_history_empty_for_no_feedback` (stored entry, no feedback, assert `events == []`); `test_history_404_for_nonexistent_entry` (assert HTTPException raised); add `TestRedisUnavailable` class: `test_score_update_succeeds_when_redis_down` (mock Redis to raise `RedisError`, assert `submit_feedback` still returns valid `FeedbackResponse`); `test_history_returns_empty_events_when_redis_down`

**Checkpoint**: All 5 user stories complete and independently testable.

---

## Phase 8: Polish & Cross-Cutting Concerns

- [x] T029 [P] Update `CLAUDE.md` Endpoints section with the two new endpoints (`POST /cache/entries/{id}/feedback`, `GET /cache/entries/{id}/feedback`) and update the Environment Variables table with the 5 new `DEJAQ_*` threshold vars
- [x] T030 Run the `quickstart.md` validation scenarios end-to-end: start Redis + Uvicorn + Celery worker, open `index.html`, send a message, click 👍 and 👎 on bot responses, verify score changes; hit the GET history endpoint; submit enough negatives to trigger flagging; confirm flagged entry no longer appears as a cache hit

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately
- **Phase 2 (Foundational)**: Depends on Phase 1 — **BLOCKS all user story phases**
- **Phase 3 (US1)**: Depends on Phase 2 completion — MVP deliverable
- **Phase 4 (US2)**: Depends on Phase 2 — can start in parallel with Phase 3
- **Phase 5 (US3)**: Depends on Phase 3 (extends `submit_feedback` built in T010)
- **Phase 6 (US4)**: Depends on Phase 3 (extends `submit_feedback` again)
- **Phase 7 (US5)**: Depends on Phase 6 (extends `submit_feedback` a final time; adds new method)
- **Phase 8 (Polish)**: Depends on all story phases complete

### User Story Dependencies

- **US1 (P1)**: Unblocked after Phase 2 — no story dependencies
- **US2 (P2)**: Unblocked after Phase 2 — independent of US1 (modifies `check_cache`, not `submit_feedback`)
- **US3 (P3)**: Depends on US1 — extends T010's `submit_feedback` method
- **US4 (P4)**: Depends on US1 — extends T010's `submit_feedback` method
- **US5 (P5)**: Depends on US4 — extends `submit_feedback` further; adds `get_feedback_history`

### Within Each Phase

- Models/schemas before services
- Services before routers
- Router registration before end-to-end testing
- Tests can be written any time after the component they test is complete

### Parallel Opportunities

- **Phase 2**: T002 and T003 can run in parallel (different schema files)
- **Phase 3**: T011 (router) and T013 (index.html) can run in parallel after T010; T014 and T015 (tests) can run in parallel with each other after T010/T005
- **Phase 6**: T021 (Celery task) and T022 (in-process fallback) can run in parallel after T020

---

## Parallel Example: Phase 3 (US1)

```
After T010 is complete:
  → T011: Create feedback router          (app/routers/feedback.py)
  → T013: Add UI buttons to index.html    (index.html)       ← parallel with T011
  → T014: Write score mechanic tests      (tests/)           ← parallel with T011, T013

After T011:
  → T012: Register router in main.py      (app/main.py)      ← sequential

After T012 + T013:
  → End-to-end test: open browser, send message, click 👍
```

---

## Implementation Strategy

### MVP First (US1 only)

1. Complete **Phase 1** (T001) — 5 minutes
2. Complete **Phase 2** (T002–T009) — foundation, blocks everything
3. Complete **Phase 3** (T010–T015) — US1 end-to-end including UI
4. **STOP AND VALIDATE**: POST feedback via curl and via browser thumbs buttons
5. Ship: feedback collection is live; cache quality improvements follow in subsequent stories

### Incremental Delivery

1. **Phases 1–3** → Feedback collection live (US1) — users can rate responses
2. **Phase 4** → Trusted entries match more broadly (US2) — cache hit rate improves
3. **Phase 5** → Low-quality entries purge themselves (US3) — cache self-cleans
4. **Phase 6** → Storage suppression (US4) — bad responses never reach cache
5. **Phase 7** → History endpoint (US5) — observability for operators
6. **Phase 8** → Polish and documentation

Each phase independently deployable. US2 can be deployed before US3 without any issues.

---

## Notes

- All `FeedbackService` tests use `@pytest.mark.no_model` — no ML model downloads required
- ChromaDB metadata stores `flagged` as `int` (0/1) since ChromaDB does not support Python `bool` natively; coerce with `bool(meta.get("flagged", 0))` on read
- `MemoryService.update_entry_metadata()` requires the **full** metadata dict — partial updates are not supported by ChromaDB's `.update()`. Always read first, then write the merged dict
- The `_is_suppressed` helper in `cache_tasks.py` and `chat.py` can be a shared two-liner or duplicated — either is acceptable given its simplicity
- Feedback buttons in `index.html` lose their event listeners after conversation switching (state preserved as HTML snapshot) — documented as acceptable v1 behavior