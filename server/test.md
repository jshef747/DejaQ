# DejaQ Server — Test Suite

## Running Tests

```bash
# Install test dependencies
uv sync --group test

# Run all tests (loads all ML models, ~25s)
uv run pytest

# Run only fast tests (no model loading, <1s)
uv run pytest -m no_model

# Run tests for a specific model/service
uv run pytest -m qwen          # Normalizer + Context Enricher
uv run pytest -m phi            # Context Adjuster (generalize)
uv run pytest -m qwen_1_5b     # Context Adjuster (adjust)
uv run pytest -m llama          # LLM Router
uv run pytest -m deberta        # Difficulty Classifier

# Run a single test file
uv run pytest tests/test_cache_filter.py

# HTML report (generated automatically)
# Open: test_reports/report.html
```

## Test Files and What They Cover

### `tests/test_cache_filter.py` (32 tests) — marker: `no_model`
Tests `app/services/cache_filter.py` — the heuristic filter that decides whether a response is worth caching.

| Test Case | What It Verifies |
|-----------|-----------------|
| Short queries rejected (1 word, 2 words) | Queries below `MIN_WORD_COUNT` (3) are skipped |
| 3+ word queries accepted | Queries meeting the minimum word count pass |
| Filler words rejected (24 variants parametrized) | Conversational filler like "ok", "thanks", "hello", "lol", etc. are caught |
| Filler with punctuation | "thanks!" still matches as filler |
| Filler case insensitive | "THANKS" still matches as filler |
| Vague enriched queries rejected | Short enriched queries (<3 words) are flagged as too vague |
| Normal questions pass all filters | Real questions like "What is the capital of France?" pass through |

### `tests/test_conversation_store.py` (12 tests) — marker: `no_model`
Tests `app/services/conversation_store.py` — in-memory multi-turn conversation history.

| Test Case | What It Verifies |
|-----------|-----------------|
| get_or_create: new conversation | Generates a UUID when no ID provided |
| get_or_create: specific ID | Uses the provided ID |
| get_or_create: existing ID | Returns the same ID without creating a duplicate |
| get_history: empty | New conversation has empty history |
| get_history: nonexistent | Returns `[]` for unknown conversation IDs |
| add_message: user + assistant | Messages are stored in order with correct role/content |
| add_message: trim at max_history (20) | Oldest messages are dropped when limit is exceeded |
| add_message: preview | Preview is set from the first user message |
| list_conversations: empty | Returns `[]` when no conversations exist |
| list_conversations: multiple | Returns all conversations |
| list_conversations: newest-first | Sorted by `created_at` descending |
| delete_conversation: existing/nonexistent | Returns `True` if deleted, `False` if not found |

### `tests/test_memory_chromadb.py` (9 tests) — marker: `no_model`
Tests `app/services/memory_chromaDB.py` — ChromaDB semantic cache (uses a temp directory per test, no shared state).

| Test Case | What It Verifies |
|-----------|-----------------|
| Store then cache hit | Exact match returns the stored generalized answer |
| Cache miss for unrelated query | Unrelated query returns `None` |
| Count: empty = 0 | Fresh collection has zero documents |
| Count: after store = 1 | Count increments after storing |
| Upsert same key still = 1 | Same normalized query upserts (no duplicates) |
| get_all_entries: empty = [] | Empty collection returns empty list |
| get_all_entries: returns stored entries | Stored entry appears with correct fields |
| delete_entry: existing = True, count drops to 0 | Deletion works and updates count |
| delete_entry: nonexistent = False | Returns `False` for unknown IDs |

### `tests/test_normalizer.py` (5 tests) — marker: `qwen`
Tests `app/services/normalizer.py` — query normalization via Qwen 0.5B. Real model inference.

| Test Case | What It Verifies |
|-----------|-----------------|
| Strips casual tone (quantum) | "hey can you explain quantum mechanics like I'm 5" keeps "quantum" |
| Strips casual tone (france) | "yo what's the capital of france lol" keeps "france" |
| Preserves photosynthesis | Verbose polite query preserves "photosynthesis" |
| Returns non-empty string | Output is always a non-empty string |
| Clean query passes through | "capital of Japan" stays relevant |

### `tests/test_context_enricher.py` (3 tests) — marker: `qwen`
Tests `app/services/context_enricher.py` — rewrites follow-up messages into standalone questions. Real model inference.

| Test Case | What It Verifies |
|-----------|-----------------|
| No history returns original | Without history, the message is returned unchanged (no inference) |
| Resolves pronouns with history | "Tell me more about its features" + Python history mentions "python" or "feature" |
| Standalone query stays relevant | Unrelated follow-up ("capital of France?") stays on its own topic |

### `tests/test_context_adjuster.py` (6 tests) — markers: `phi`, `qwen_1_5b`
Tests `app/services/context_adjuster.py` — generalize (strip tone via Phi-3.5) and adjust (add tone via Qwen 1.5B). Real model inference.

| Test Case | What It Verifies |
|-----------|-----------------|
| generalize: strips casual tone | Slang input produces output with "gravity" or "force" |
| generalize: neutral input passes through | Already-neutral text keeps "photosynthesis" |
| generalize: returns non-empty | Output is always a non-empty string |
| adjust: matches casual tone | Produces a response for a casual query |
| adjust: matches formal tone | Produces a response for a formal query |
| adjust: returns non-empty | Output is always a non-empty string |

### `tests/test_llm_router.py` (3 tests) — marker: `llama`
Tests `app/services/llm_router.py` — routes queries to local Llama 3.2 1B or external API stub. Real model inference for "easy".

| Test Case | What It Verifies |
|-----------|-----------------|
| Easy complexity: real LLM response | Returns a non-empty string from the local model |
| Easy with conversation history | History is passed through and response is non-empty |
| Hard complexity: stub response | Returns "Simulated response for: ..." placeholder |

### `tests/test_classifier.py` (6 tests) — marker: `deberta`
Tests `app/services/classifier.py` — NVIDIA DeBERTa prompt complexity classifier. Real model inference.

| Test Case | What It Verifies |
|-----------|-----------------|
| Returns expected keys | Output dict has `complexity`, `score`, `task_type` |
| Complexity is "easy" or "hard" | Valid enum value |
| Score is float in [0, 1] | Score is bounded |
| Task type is non-empty string | Task type label exists |
| Simple query leans easy | "What is 2 + 2?" classified as easy |
| Complex query scores higher | Multi-part analytical prompt scores higher than simple factual query |

## Future Tests

As the project progresses, these areas will need test coverage:

### Database Integration (PostgreSQL)
- Conversation persistence (store, retrieve, delete)
- Cache entry persistence and migration from ChromaDB
- Connection pooling and error handling
- Data integrity across restarts

### API Endpoints (HTTP + WebSocket)
- `POST /chat` — full pipeline end-to-end (cache hit path, cache miss path)
- `POST /normalize` — HTTP normalization endpoint
- `POST /generalize` — HTTP generalization endpoint
- `WS /ws/chat` — WebSocket connection lifecycle, message flow, conversation_id handling
- `GET /cache/entries` — cache viewer pagination and filtering
- `DELETE /cache/entries/{id}` — cache entry deletion via API
- Conversation CRUD endpoints (`GET /conversations`, `DELETE /conversations/{id}`)
- `GET /health` — health check returns expected shape
- Error handling (invalid input, missing fields, malformed WebSocket messages)

### Celery Task Queue
- `generalize_and_store_task` executes correctly as a Celery task
- Task retry behavior on failure
- Fallback to in-process when `DEJAQ_USE_CELERY=false`
- Task result serialization (JSON round-trip)

### External LLM APIs (GPT/Gemini)
- Hard-complexity queries routed to external API (once stub is replaced)
- API error handling, timeouts, and fallback behavior
- Response format validation from external providers

### Full Pipeline Integration
- Cache miss → generalize → store → subsequent cache hit (round-trip)
- Context enricher → normalizer → cache check → LLM → response (full chain)
- Multi-turn conversation: history correctly influences enrichment and LLM responses
- Cache filter correctly prevents trivial messages from being stored end-to-end

### Performance and Concurrency
- Multiple concurrent WebSocket connections
- Model inference under parallel requests (thread safety of ModelManager singleton)
- ChromaDB concurrent read/write behavior

### React Frontend (when built)
- API contract tests (request/response schemas match frontend expectations)
- WebSocket message format compatibility
