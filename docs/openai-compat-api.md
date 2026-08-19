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
| `x-dejaq-rag-chunks` | Present on a cache miss when the answer was **grounded** in the workspace knowledge base (Rug); value is the number of injected chunks. Absent when nothing was retrieved |

> `POST /v1/responses` (OpenAI Responses API, newer format) shares the same auth, headers, and
> pipeline. It is stateless: `previous_response_id` / `conversation` are rejected with HTTP 400.

> **Knowledge grounding (Rug):** on a cache miss, DejaQ retrieves relevant chunks from the
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
