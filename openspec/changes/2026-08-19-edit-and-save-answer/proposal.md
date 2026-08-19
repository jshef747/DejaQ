## Why

A user who spots a wrong answer has only two blunt controls today: 👍 adds `+1.0` to the cache
entry's score, 👎 deletes it outright. Neither lets the person who *knows* the right answer put it
into the system. The correction either never happens, or it happens through 👎 → escalation, which
re-asks a bigger model and hopes.

Edit & Save closes that gap. The user rewrites the answer in place and hits Save; the edited text
becomes the cached answer for that question, served to the next person in their department who asks
it. Mechanically the Save **is** the Like — the same `/v1/feedback` call, the same `+1.0` — plus an
answer overwrite that happens first, so the score lands on the human text rather than on the answer
it replaced.

The hard requirement is that the model's answer is **discarded**, not merely outranked. In this
codebase that is not one write: the old text can survive in an entry's own metadata, in every alias
that holds a byte-copy of it, in a background store task still in flight, and — on the way out — in
the context adjuster's paraphrase of it. Each has to be closed separately.

## What Changes

- `POST /v1/feedback` accepts an optional `edited_answer`, valid only with `rating: "positive"` and
  an `interaction_id`. Existing payloads are untouched.
- The response gains `edit_status` (`saved` | `created` | `not_cached` | `message_mismatch`) and the
  `response_id` the edit actually landed on.
- A new `MemoryService.overwrite_answer` replaces an entry's answer in place — keeping its score,
  hit counts and any attachment fingerprints — redirecting an alias-served id to its root and
  cascading the new text to every alias, exactly as `delete_entry` cascades deletions.
- Entries written this way carry `authored="human"`, which makes them: stored verbatim (no
  generalizer), skipped by the context adjuster on serve, refused by the background store task, and
  exempt from score eviction. A thumbs-down still deletes them.
- When no entry exists (the cache filter refused the query, or the background store has not landed),
  the server re-derives the cache key from the hash-verified message replay and creates it. This is
  the one place `cache_filter` is deliberately not consulted.
- Attachment turns are overwrite-only: the client withholds `messages` for them, so a blind replay
  can never produce an ungated text entry — the rule escalation already follows.
- A cache hit on a human entry reports `x-dejaq-answer-authored: human`.
- `feedback_log` gains an `edited` column so a save is distinguishable from a plain thumbs-up.
- The chat app grows an Edit affordance on the assistant turn, an inline editor that inherits the
  reading column's exact type metrics, and Save/Cancel controls.

## Capabilities

### New Capabilities

- `human-authored-cache-entries`: a cache entry can hold an answer a person wrote, and is protected
  from every mechanism that would replace, paraphrase or evict it

### Modified Capabilities

- `response-feedback`: positive feedback may carry the corrected answer text, applied before scoring

## Impact

- `server/app/services/answer_edit.py` — new; overwrite-or-create, and the refusals
- `server/app/services/workspace_overrides.py` — new; the per-workspace lookups previously private
  to `escalation.py`, now shared with `answer_edit.py`
- `server/app/services/memory_chromaDB.py` — `overwrite_answer`, `authored` on store/alias/lookup,
  eviction guard
- `server/app/services/feedback_service.py`, `server/app/routers/feedback.py`,
  `server/app/schemas/feedback.py` — the request/response contract and the ordering against scoring
- `server/app/tasks/cache_tasks.py`, `server/app/routers/openai_compat.py` — the two store guards,
  the adjuster skip, the new header
- `server/app/services/request_logger.py` — the `edited` column
- `chat/` — `edit-draft.ts` (new), `ChatMessage.tsx`, `ChatApp.tsx`, `chat-api.ts`, the feedback and
  chat proxy routes

## Non-goals

- Editing from the dashboard cache viewer
- An edit history or per-entry authorship attribution beyond the `authored` flag
- Image or file **alias** learning, which remains tracked separately
