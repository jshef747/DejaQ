# Data Model: Cache Feedback Loop

**Feature**: 001-cache-feedback-loop
**Date**: 2026-02-19

---

## Entities

### 1. Cache Entry (extended)

Stored in: **ChromaDB** (`dejaq_default` collection, `metadatas` field)

Existing fields (unchanged):
| Field | Type | Description |
|-------|------|-------------|
| `generalized_answer` | str | Tone-neutral answer stored by Phi-3.5 |
| `original_query` | str | The raw user query at time of storage |
| `user_id` | str | User who triggered the cache store |
| `stored_at` | str | ISO8601 timestamp of storage |

New fields (added by this feature):
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `feedback_score` | int | `0` | Net quality score: +1 per positive rating, -1 per negative |
| `flagged` | bool | `False` | True when score crosses `FLAG_THRESHOLD`; entry is never served when True |

Notes:
- `doc_id` (ChromaDB document ID) is `sha256(normalized_query)[:16]` — unchanged.
- ChromaDB metadata values must be scalar. `feedback_score` is stored as int; `flagged` as `0`/`1` (ChromaDB does not support Python bool natively — use int `0`/`1` and coerce on read).
- Updated via `collection.update(ids=[id], metadatas=[{...full metadata dict...}])` — ChromaDB requires the full metadata dict on update (no partial-field update support).

---

### 2. Feedback Event

Stored in: **Redis** key `feedback:{entry_id}`

Structure: JSON-encoded list, appended with `RPUSH`, read with `LRANGE 0 -1`.

```json
[
  { "direction": "positive", "timestamp": "2026-02-19T12:00:00Z" },
  { "direction": "negative", "timestamp": "2026-02-19T12:01:30Z" }
]
```

Each event:
| Field | Type | Values |
|-------|------|--------|
| `direction` | str | `"positive"` or `"negative"` |
| `timestamp` | str | ISO8601 UTC string |

Notes:
- No TTL on history keys — events persist as long as Redis data persists.
- History is append-only. Events are never modified or deleted individually.
- If Redis is unavailable, the score update in ChromaDB still proceeds; only the event log is lost for that rating.

---

### 3. Storage Suppression Flag

Stored in: **Redis** key `skip:{doc_id}`

| Property | Value |
|----------|-------|
| Key format | `skip:{sha256(clean_query)[:16]}` |
| Value | `"1"` (arbitrary, only presence matters) |
| TTL | `DEJAQ_SUPPRESSION_TTL` seconds (default: 300) |

Used by: `generalize_and_store_task` (Celery) and `_generalize_and_store` (in-process fallback).
Set by: `FeedbackService.submit_feedback()` when `value="negative"` and the entry does not yet exist in ChromaDB (cache miss case).

---

## Pydantic Schemas

### `app/schemas/feedback.py` (new file)

```python
class FeedbackRequest(BaseModel):
    value: Literal["positive", "negative"]
    conversation_id: Optional[str] = None

class FeedbackResponse(BaseModel):
    entry_id: str
    feedback_score: int
    flagged: bool
    deleted: bool
    status: str  # "ok" | "suppressed" | "not_found_suppressed"

class FeedbackEvent(BaseModel):
    direction: str
    timestamp: datetime

class FeedbackHistoryResponse(BaseModel):
    entry_id: str
    feedback_score: int
    flagged: bool
    events: list[FeedbackEvent]
```

### `app/schemas/chat.py` (modified)

Add to `ChatResponse`:
```python
cache_entry_id: Optional[str] = Field(None, description="ID of the cache entry for feedback submission")
```

---

## State Transitions

### Cache Entry lifecycle with feedback

```
STORED (score=0, flagged=False)
    │
    ├─► positive rating → score += 1
    │   score >= TRUSTED_THRESHOLD → served with relaxed similarity
    │
    ├─► negative rating → score -= 1
    │   score < FLAG_THRESHOLD → flagged=True (entry not served)
    │   score < AUTO_DELETE_THRESHOLD → entry deleted from ChromaDB
    │
    └─► flagged=True → never served; future negative ratings may delete
```

### Suppression lifecycle

```
cache miss response sent
    │
    ├─► client submits negative feedback within TTL
    │   → skip:{doc_id} set in Redis with TTL
    │   → generalize_and_store_task checks key → storage cancelled
    │
    └─► TTL expires (or positive feedback / no feedback)
        → storage proceeds normally
```

---

## Threshold Configuration

All thresholds are set in `app/config.py`, overridable via environment variables:

| Env Var | Default | Type | Meaning |
|---------|---------|------|---------|
| `DEJAQ_TRUSTED_THRESHOLD` | `3` | int | Min score for relaxed similarity |
| `DEJAQ_FLAG_THRESHOLD` | `-3` | int | Score that triggers flagged=True |
| `DEJAQ_AUTO_DELETE_THRESHOLD` | `-5` | int | Score that triggers deletion |
| `DEJAQ_TRUSTED_SIMILARITY` | `0.20` | float | Cosine distance ceiling for trusted entries |
| `DEJAQ_SUPPRESSION_TTL` | `300` | int | Seconds to hold suppression keys |

---

## Redis Connection

`FeedbackService` uses a synchronous `redis.Redis` client (from `redis-py`, already a Celery dependency). Connection is established once at service instantiation using `REDIS_URL` from `app/config.py`.

```python
import redis
_redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
```

`DEJAQ_USE_CELERY=false` mode: Redis may not be running. `FeedbackService` must handle `redis.exceptions.ConnectionError` gracefully — log a warning, skip event history, proceed with ChromaDB score update only.
