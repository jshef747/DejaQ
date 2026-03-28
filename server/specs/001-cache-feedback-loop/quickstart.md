# Quickstart: Cache Feedback Loop

**Feature**: 001-cache-feedback-loop
**Date**: 2026-02-19

This guide explains how to use the feedback API once the feature is implemented.

---

## How It Works

Every chat response now includes a `cache_entry_id`. Use this ID to submit a thumbs up or thumbs down rating. Over time, ratings shape the cache:

- **Thumbs up** → entry's quality score increases; high-score entries match more broadly
- **Thumbs down** → quality score decreases; low-score entries get flagged and removed

---

## Step-by-Step

### 1. Send a chat request (unchanged)

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user-001",
    "message": "What is the capital of France?",
    "department_id": "general"
  }'
```

**Response** (new field highlighted):
```json
{
  "sender": "bot",
  "message": "The capital of France is Paris.",
  "cache_hit": false,
  "cached": true,
  "conversation_id": "conv-abc123",
  "cache_entry_id": "a1b2c3d4e5f6a7b8"
}
```

### 2. Rate the response

```bash
# Thumbs up
curl -X POST http://localhost:8000/cache/entries/a1b2c3d4e5f6a7b8/feedback \
  -H "Content-Type: application/json" \
  -d '{"value": "positive", "conversation_id": "conv-abc123"}'

# Thumbs down
curl -X POST http://localhost:8000/cache/entries/a1b2c3d4e5f6a7b8/feedback \
  -H "Content-Type: application/json" \
  -d '{"value": "negative", "conversation_id": "conv-abc123"}'
```

**Response**:
```json
{
  "entry_id": "a1b2c3d4e5f6a7b8",
  "feedback_score": 1,
  "flagged": false,
  "deleted": false,
  "status": "ok"
}
```

### 3. Check feedback history

```bash
curl http://localhost:8000/cache/entries/a1b2c3d4e5f6a7b8/feedback
```

**Response**:
```json
{
  "entry_id": "a1b2c3d4e5f6a7b8",
  "feedback_score": 1,
  "flagged": false,
  "events": [
    {"direction": "positive", "timestamp": "2026-02-19T12:00:00Z"}
  ]
}
```

---

## Special Cases

### Negative feedback on a fresh response (before it's cached)

If you rate a cache miss negatively, storage is cancelled:

```bash
# Rate a fresh (uncached) response negatively
curl -X POST http://localhost:8000/cache/entries/a1b2c3d4e5f6a7b8/feedback \
  -H "Content-Type: application/json" \
  -d '{"value": "negative"}'
```

**Response** (`status: "suppressed"` means storage was cancelled):
```json
{
  "entry_id": "a1b2c3d4e5f6a7b8",
  "feedback_score": 0,
  "flagged": false,
  "deleted": false,
  "status": "suppressed"
}
```

### Entry auto-deleted after persistent negative feedback

When the quality score drops below the auto-delete threshold:
```json
{
  "entry_id": "a1b2c3d4e5f6a7b8",
  "feedback_score": -5,
  "flagged": true,
  "deleted": true,
  "status": "ok"
}
```

---

## Default Thresholds

| Threshold | Default | Effect |
|-----------|---------|--------|
| Trusted (positive) | +3 | Entry matches queries with cosine ≤ 0.20 (up from 0.15) |
| Flag | -3 | Entry marked unreliable, no longer served |
| Auto-delete | -5 | Entry removed from cache entirely |

Override via environment variables: `DEJAQ_TRUSTED_THRESHOLD`, `DEJAQ_FLAG_THRESHOLD`, `DEJAQ_AUTO_DELETE_THRESHOLD`.

---

## New Endpoints Summary

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/cache/entries/{id}/feedback` | Submit a rating |
| `GET` | `/cache/entries/{id}/feedback` | Get feedback history |