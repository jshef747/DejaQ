# OpenAI-Compatible API

DejaQ exposes `POST /v1/chat/completions` so OpenAI SDK clients can point at the gateway and receive semantic caching, local routing, and workspace-scoped external provider fallback.

## Base URL

```text
http://127.0.0.1:8000/v1
```

## Authentication

Gateway calls require a DejaQ workspace API key:

```text
Authorization: Bearer <dejaq-workspace-api-key>
```

Use `dejaq-admin key generate --workspace <slug>` or the dashboard key screen to create keys. `/admin/v1/*` authenticates separately: it always grants an unauthenticated dev-admin context, protected by loopback binding rather than a credential. An admin token is never accepted by the `/v1/*` gateway, which always uses workspace API keys.

Optional department isolation:

```text
X-DejaQ-Department: <department-slug>
```

## POST /v1/chat/completions

```json
{
  "model": "gpt-4o",
  "messages": [
    { "role": "system", "content": "You are a helpful assistant." },
    { "role": "user", "content": "Why is the sky blue?" }
  ],
  "stream": false,
  "max_tokens": 1024,
  "temperature": 0.7
}
```

| Field | Required | Notes |
| --- | --- | --- |
| `model` | yes | Accepted for OpenAI compatibility; DejaQ routes internally and returns the requested model in the OpenAI response body. |
| `messages` | yes | Last `user` message is the active query. Prior messages are history. |
| `stream` | no | `false` returns JSON; `true` returns SSE chunks. |
| `max_tokens` | no | Passed to generation providers where applicable. |
| `temperature` | no | Reaches the external provider **only when you send it** - omit it and DejaQ sends no `temperature` at all, because Claude Opus 4.7+/Sonnet 5 and the `gpt-5.x` models reject any non-default value. If you do send one and the provider rejects it by name, the call is retried once without it. The local model path uses its own fixed sampling and ignores this field. |

## Responses

Non-streaming responses use the OpenAI chat-completion shape:

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "created": 1713100000,
  "model": "gpt-4o",
  "choices": [
    {
      "index": 0,
      "message": { "role": "assistant", "content": "..." },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 12,
    "completion_tokens": 48,
    "total_tokens": 60
  }
}
```

Streaming responses emit OpenAI-style `data:` SSE chunks followed by `data: [DONE]`.

On a **cache miss** the deltas are the generator's own output as it produces it, not a finished
answer re-split after the fact: the response head (status + all the `x-dejaq-*` headers below)
is flushed before generation starts, so a client can name the route and model it is waiting on
seconds before the first content byte arrives. `finish_reason` / `status` and, on
`/v1/responses`, `usage` only settle once the stream is drained, so they ride the terminal
event rather than the head. A **cache hit** is unchanged - the answer already exists, so head
and body arrive together.

### `usage`: real counts vs. estimate

`usage` is not derived the same way on every route, because only one route has a real token
count to report:

| Route | `prompt_tokens` / `completion_tokens` |
| --- | --- |
| External (hard miss answered by the provider) | The provider's own counts, read straight off its API response. These are what you were actually billed for. |
| Local (easy miss) | Estimated as `words * 1.3`. Local generation returns no token count, so an estimate is all there is. |
| Cache hit | Prompt estimated the same way; completion is `0`, since no generation happened. |

An external call that errors falls back to the estimate along with the rest of the miss path.

`/v1/responses` reports the same numbers under `input_tokens` / `output_tokens`.

### `finish_reason` / `status`: truncation is reported, not hidden

`choices[0].finish_reason` is `"stop"`, or `"length"` when the token budget cut the answer off
mid-generation. It is never inferred from the shape of the text — it carries the generator's own
signal (Ollama's `done_reason` on the local route, the provider's own stop reason on the external
route, both collapsed to those two values). The final streaming chunk carries the same value. A
cache hit always reports `"stop"`.

`/v1/responses` reports the same fact as `status`: `"completed"`, or `"incomplete"` when the
answer was cut off — on the top-level response and on the output item, streaming and
non-streaming alike. An incomplete response also carries
`incomplete_details: {"reason": "max_output_tokens"}` (null when it completed), and a truncated
stream ends on a `response.incomplete` terminal event rather than `response.completed`, so a
client branching on the event type sees the truncation without reading the payload.

A truncated answer is never stored in the cache: a stored truncation is what every later match
would be served, and it never self-heals. The caller still receives the partial answer; it just
leaves no cache entry. Thumbs-down escalation answers follow the same rule.

Gateway headers:

| Header | Meaning |
| --- | --- |
| `x-dejaq-model-used` | `cache`, local model name, or external model name |
| `x-dejaq-conversation-id` | OpenAI-compatible response id |
| `x-dejaq-interaction-id` | Interaction id for feedback / escalation |
| `x-dejaq-tier` | Serving tier: `cache`, `local`, or `external` |
| `x-dejaq-response-id` | Cache entry response id when feedback can be submitted. On a **streaming** miss the header goes out before the answer exists, so it names the entry the request *intends* to store - see [Feedback](#feedback) |
| `x-dejaq-rag-chunks` | Present on a cache miss when the answer was **grounded** in the workspace knowledge base (RAG); value is the number of injected chunks. Absent when nothing was retrieved |
| `x-dejaq-answer-authored` | `human` when the served cache entry holds an answer a person wrote through [Edit & Save](#edit--save). Only ever set on a hit - a miss is by definition an answer nobody has corrected yet |

> `POST /v1/responses` (OpenAI Responses API, newer format) shares the same auth, headers, and
> pipeline. It is stateless: `previous_response_id` / `conversation` are rejected with HTTP 400.

> **Knowledge grounding (RAG):** on a cache miss, DejaQ retrieves relevant chunks from the
> workspace's admin-curated knowledge base and injects them into the prompt before the model
> answers — the request/response contract is unchanged (no new fields; the grounding is a
> server-side side channel, flagged only by `x-dejaq-rag-chunks`). Admins manage the knowledge
> base via the dashboard, `dejaq-admin rag`, or `/admin/v1/workspaces/{slug}/rag-documents`.
> See [rag-layer.md](rag-layer.md).

### Attachments — `/v1/responses` only

`/v1/responses` is the only endpoint that accepts attachments. A request may carry **one**
attachment: an `input_image` **or** an `input_file`, never both.

| Part | Field | Accepts |
| --- | --- | --- |
| `input_image` | `image_url` | `data:<mime>;base64,<payload>` |
| `input_file` | `file_data` (+ optional `filename`) | `data:<mime>;base64,<payload>` — PDF (`application/pdf`, `.pdf`) or DOCX (`.docx`) by MIME/extension, or any other file whose bytes decode as UTF-8 (Markdown, plain text, source/config files — no maintained extension list) |

Rejected with **HTTP 400**:

- a non-`data:` URL in `image_url` or `file_data` (`http(s):` is not fetched)
- more than one `input_image` — *"At most one image per request is supported."*
- more than one `input_file` — *"At most one file per request is supported."*
- one of each — *"Attach either an image or a file, not both."*
- either exceeding `DEJAQ_MAX_ATTACHMENT_BYTES` (default 10 MB)

**How an attachment changes serving.** It never enters the cache key — the text pipeline runs
unchanged — but a cache hit is served only if the relevant **gate** also confirms the stored
entry was anchored to the same attachment:

- **Image gate.** Confident OCR text → *document*, matched on OCR token overlap
  (`DEJAQ_CACHE_IMAGE_TEXT_MIN_JACCARD`, 0.85) with a shared-token floor
  (`DEJAQ_CACHE_IMAGE_TEXT_MIN_SHARED_TOKENS`, 4). Little or no readable text → *photo*,
  matched on CLIP distance **and** dHash hamming. At least
  `DEJAQ_CACHE_IMAGE_AMBIGUOUS_MIN_WORDS` (4) tokens read *below* the confidence floor is
  neither: never served, never stored; below that token count the image is treated as a
  photo and does take the pixel path. Kinds never mix, and a text-only request matches
  neither. Documents require the `tesseract` binary; without it they degrade to the photo path.
- **File gate.** Exact `sha256` of the whitespace-normalised extracted text — no thresholds,
  no fuzzy matching, false merges impossible by construction. For PDF/DOCX, where extraction
  can fail silently, text under `DEJAQ_CACHE_FILE_MIN_CHARS` (200) is never served and never
  stored (scanned, corrupt, or encrypted files land here); the answer still returns, uncached.
  Text/Markdown/code files have no such floor.

On a miss, attachment requests skip the difficulty classifier and route unconditionally to the
workspace's external provider (the local model is text-only). Attachment answers are stored
verbatim, so on an attachment-anchored hit the context adjuster is skipped — no tone was ever
stripped. Raw image bytes are never stored, only fingerprints.

Thresholds and their measured derivations: [image-gate.md](image-gate.md), [file-gate.md](file-gate.md).

## Pipeline Behavior

```text
request
  -> context enricher
  -> normalizer
  -> ChromaDB cache lookup
     -> hit: context adjuster (skipped when there is no tone gap) + return
     -> miss: difficulty classifier
        -> easy: local model
        -> hard: encrypted workspace provider credential
  -> background generalize + store when cacheable
```

- Cache hit: `x-dejaq-model-used: cache`.
- A cache hit on a request with **no prior conversation turns** that closely matches the stored
  question skips the adjuster and returns the stored answer verbatim, saving its latency
  (`DEJAQ_ADJUSTER_SKIP_DISTANCE`, see CLAUDE.md). Multi-turn follow-ups always run it, because
  the enricher has already folded a "give me the short version" ask back into the original
  question by the time the distance is measured.
- Easy miss: served by the configured local model backend.
- Hard miss: served by the provider recorded for the workspace's configured external model (or,
  for a config saved before that provider was recorded, inferred from the model name), using
  encrypted workspace credentials.
- A workspace with no external model configured - no per-workspace override and no
  `DEJAQ_EXTERNAL_MODEL` server default - returns `422 Unprocessable Entity`, naming the fix:
  configure a provider and model in Settings. DejaQ never silently substitutes a model nobody
  chose.
- A configured model that maps to no supported provider also returns `422 Unprocessable Entity`,
  naming the offending model.
- Missing hard-query credentials return `402 Payment Required`.
- A hard-query provider failure on the **non-streaming** path returns `400` (request rejected),
  `502` (the workspace's stored provider credential was rejected — not `401`, which on this
  endpoint means the caller's own DejaQ API key was rejected), or `429` (provider rate limit).
  Each carries a fixed per-status message naming the provider, never the provider's own error
  text — that stays in the server log, since it can echo a masked form of the stored credential.
  A status-less failure (timeout, connection reset) still returns `200` with the generic apology,
  as does every failure on the streaming path, whose `200` headers are already flushed.

There is no runtime `GEMINI_API_KEY` fallback, and no baked-in default external model. Store provider credentials through the dashboard or `PUT /admin/v1/workspaces/{workspace_slug}/credentials/{provider}`; choose a provider and model through the dashboard Settings page or `PUT /admin/v1/workspaces/{workspace_slug}/llm-config`.

## SDK Example

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8000/v1",
    api_key="<dejaq-workspace-api-key>",
)

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Why is the sky blue?"}],
)

print(response.choices[0].message.content)
```

## Feedback

If the gateway returns `x-dejaq-response-id`, submit feedback to:

```http
POST /v1/feedback
Authorization: Bearer <dejaq-workspace-api-key>
Content-Type: application/json
```

```json
{
  "response_id": "<x-dejaq-response-id>",
  "rating": "positive",
  "comment": "optional"
}
```

An id that names no entry returns `404 {"detail": "response_id not found"}`. Two cases produce
one: an entry evicted since it was served, and a **streaming** miss whose header was flushed
before generation and whose answer a store guard then refused (a failed, empty, or truncated
answer - see [`finish_reason` / `status`](#finish_reason--status-truncation-is-reported-not-hidden)).
Withholding the id until the store decision would mean withholding the whole response head
until the answer was complete, which is the delay streaming exists to remove.

## Alternative drafts (the semantic tie-breaker)

Off by default; enabled per workspace with `drafts_enabled` on
`PUT /admin/v1/workspaces/{slug}/llm-config`.

The cache hit path serves one winner: `_lookup_candidates` ranks candidates and the router takes
the first that clears the attachment gates. When the two closest candidates sit within
`DEJAQ_CACHE_DRAFTS_MAX_DELTA` (0.02) of each other and both are inside
`DEJAQ_CACHE_DRAFTS_MAX_DISTANCE` (0.05), that ranking is a coin flip nobody is told about. With
this on, both are returned and the user picks.

### Wire format

A response carries `X-DejaQ-Drafts: 2` and a `dejaq_drafts` array:

```json
{
  "choices": [{"message": {"role": "assistant", "content": "The refund window is 30 days."}}],
  "dejaq_drafts": [
    {"label": "A", "response_id": "acme__eng:doc-a", "content": "The refund window is 30 days.", "distance": 0.021},
    {"label": "B", "response_id": "acme__eng:doc-b", "content": "You have a month after it arrives.", "distance": 0.023}
  ]
}
```

**Draft A is always the answer that was actually served**, and `x-dejaq-response-id` names it, so a
client that ignores the field entirely behaves exactly as it did before this existed.

On a **streaming** request the drafts ride the **terminal chunk** — the one carrying
`finish_reason` — as an extra top-level key on an otherwise ordinary
`chat.completion.chunk`. That placement is deliberate, not incidental: an OpenAI SDK parses every
`data:` line into a chunk, so a custom SSE event carrying a foreign shape (no `choices`) fails its
validation and breaks the client. An unknown key on a legal chunk is ignored by all of them. The
key is omitted entirely, on every frame, when no tie fired. `/v1/responses` carries the same array
on its body and on the `response.completed` payload.

### When it fires

All of these, or the response is an ordinary single answer:

| Condition | Why |
| --- | --- |
| Both candidates within `drafts_max_distance` | A tie between two poor matches is still two poor matches |
| Distances within `drafts_max_delta` | This is the tie itself |
| Score gap under `1.0` | **Convergence.** One pick applies the ordinary `+1.0`, the gap reaches exactly 1.0, and the pair is settled — otherwise a distance-based trigger asks every user the same answered question forever |
| Both trusted-tier | A band/rescue candidate is only servable once the validator accepts it |
| Neither is `authored="human"` | A person vouched for that text through Edit & Save |
| No attachment | Two entries for one image or file are two different documents' answers, or the same one twice |
| Single-turn request | A follow-up turn needs the context adjuster, and drafts are served verbatim |
| Answers genuinely differ | Not an alias of one root (an alias holds a byte-copy), not a near-duplicate |

`drafts_max_distance` is capped at `DEJAQ_VALIDATOR_SKIP_DISTANCE`, **not** at the trusted-zone
ceiling. The served answer goes through the validator on merit like any other hit; the *alternate*
never does, because a second `validate()` call would land on the synchronous serve path. That is
only defensible inside the distance where the embedding alone already guarantees a cached answer
covers the question. Above it the validator is what separates a paraphrase from a sibling question
— `solve part a` / `part b` measures 0.0898, comfortably inside the trusted zone. The cost is
recall, knowingly.

Both drafts are served **verbatim**: the context adjuster is skipped, because the text a person
picks has to be the text that gets the point.

### Keeping one

The pick rides `/v1/feedback`, like Edit & Save:

```json
{
  "interaction_id": "<x-dejaq-interaction-id>",
  "rating": "positive",
  "chosen_draft_response_id": "acme__eng:doc-b",
  "rejected_draft_response_ids": ["acme__eng:doc-a"]
}
```

`chosen_draft_response_id` requires `rating: "positive"` and an `interaction_id`, and cannot be
combined with `edited_answer` (both `422`) — those are two writes to one entry with no defined
order between them. Every id is namespace-checked against the caller's own workspace before
anything is scored or logged, rejected ids included.

`chosen_draft_response_id` is checked further: it must be a draft this interaction actually
offered. The offered pair is not stored anywhere (no column, no migration), so it is re-derived —
the id must either equal the interaction's current `response_id` (draft A, the served answer) or
be the alternate the same lookup produces for that entry (draft B). Anything else is a `422`
naming the reason, never silently ignored. Without this, an unrelated entry in the caller's own
namespace takes the `+1.0` **and** the interaction is re-pointed at it, so a later thumbs-down
deletes an entry the user was never shown.

| Field | Meaning |
| --- | --- |
| `draft_choice` | `recorded`, or `not_found` when the entry was evicted before the pick landed — not an error; the answer is already on the user's screen |
| `response_id` | The entry the `+1.0` landed on. Adopt it |

The rejected draft is **not penalised**. By the tie-breaker's own definition it was a high-quality
match, and another user may well prefer it; the `+1.0` on the winner is what settles the pair.

The interaction record is re-pointed at the kept entry server-side. This is the part a client
cannot fix for itself: the record was written naming the draft that was *served*, and every later
call sending only an `interaction_id` resolves through it. Left alone, a thumbs-down on the kept
answer would delete the *discarded* entry — immediately, on a first negative — and a thumbs-up
would score it and hand the settled pair its score gap back.

## Edit & Save

A client can correct a served answer and have the correction become the cached answer. It is the
same request as a thumbs-up, with the text attached:

```json
{
  "interaction_id": "<x-dejaq-interaction-id>",
  "rating": "positive",
  "edited_answer": "the corrected answer",
  "messages": [{"role": "user", "content": "..."}]
}
```

`edited_answer` requires `rating: "positive"` and an `interaction_id` (both `422` otherwise). A save
**is** the like: the `+1.0` is applied in the same call, to the entry the edit wrote rather than to
the answer it replaced.

The response adds two fields:

| Field | Meaning |
| --- | --- |
| `edit_status` | `saved` (an existing entry was overwritten), `created` (no entry existed, so one was written under a freshly derived key), `not_cached` (nothing to overwrite and no usable replay), `message_mismatch` (the replay did not match the interaction) |
| `response_id` | The entry the edit actually landed on. Adopt it - it differs from the id you sent when the answer was served through an alias, or when the entry had to be created |

The edited text **replaces** the model's rather than sitting beside it. Three things would
otherwise put the old answer back, and each is closed separately: the entry's own answer field is
overwritten in place (keeping its score, hit counts and any attachment fingerprints), every alias
of it - which holds a byte-copy - is rewritten too, and every path that stores a model answer
refuses to write over an entry marked `authored="human"` (the background generalize-and-store task,
its in-process fallback, and the thumbs-down escalation store, which share one guard). On the way
out, the context adjuster is skipped for such an entry, so the next asker gets the human text
byte-identical rather than a 1.5B paraphrase of it.
A human entry is also exempt from score eviction; a thumbs-down still deletes it, so a bad edit
stays undoable.

`edit_status` also tells a client whether to show the answer as rated: on `not_cached` and
`message_mismatch` no score was applied, so presenting it as a recorded thumbs-up would be wrong.
A `response_id` naming another workspace's entry is rejected `422` before anything is written.

`messages` is the same hash-verified request replay the escalation path uses, and it is only needed
when no entry exists yet. **Withhold it for a turn that carried an image or a file** - the replay is
blind to the attachment, so building an entry from it would produce an ungated text entry holding
an answer about a document nobody attached. Those turns can only overwrite an entry that already
exists, and answer `not_cached` when there is none.

Unlike the normal store path, `edited_answer` is **not** subject to the cache filter: a person
vouching for an answer outranks the "at least three words" heuristic that decides whether a model's
answer is worth keeping.
