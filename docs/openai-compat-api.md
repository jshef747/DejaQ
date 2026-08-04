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

Use `dejaq-admin key generate --workspace <slug>` or the dashboard key screen to create keys. `/admin/v1/*` authenticates separately, following `DEJAQ_AUTH_MODE`: it defaults to `local` (an unauthenticated dev-admin context, protected by loopback binding) whenever `SUPABASE_URL` is blank, and validates a Supabase JWT otherwise. Neither an admin token nor a Supabase JWT is accepted by the `/v1/*` gateway, which always uses workspace API keys.

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
| `temperature` | no | Passed to generation providers where applicable. |

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

Gateway headers:

| Header | Meaning |
| --- | --- |
| `x-dejaq-model-used` | `cache`, local model name, or external model name |
| `x-dejaq-conversation-id` | OpenAI-compatible response id |
| `x-dejaq-interaction-id` | Interaction id for feedback / escalation |
| `x-dejaq-tier` | Serving tier: `cache`, `local`, or `external` |
| `x-dejaq-response-id` | Cache entry response id when feedback can be submitted |

> `POST /v1/responses` (OpenAI Responses API, newer format) shares the same auth, headers, and
> pipeline. It is stateless: `previous_response_id` / `conversation` are rejected with HTTP 400.

### Attachments — `/v1/responses` only

`/v1/responses` is the only endpoint that accepts attachments. A request may carry **one**
attachment: an `input_image` **or** an `input_file`, never both.

| Part | Field | Accepts |
| --- | --- | --- |
| `input_image` | `image_url` | `data:<mime>;base64,<payload>` |
| `input_file` | `file_data` (+ optional `filename`) | `data:<mime>;base64,<payload>` — PDF (`application/pdf`, `.pdf`) or Markdown (`text/markdown`, `text/plain`, `.md`/`.markdown`/`.txt`) |

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
  no fuzzy matching, false merges impossible by construction. Text under
  `DEJAQ_CACHE_FILE_MIN_CHARS` (200) is never served and never stored (scanned, corrupt, or
  encrypted PDFs land here); the answer still returns, uncached.

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
     -> hit: context adjuster + return
     -> miss: difficulty classifier
        -> easy: local model
        -> hard: encrypted workspace provider credential
  -> background generalize + store when cacheable
```

- Cache hit: `x-dejaq-model-used: cache`.
- Easy miss: served by the configured local model backend.
- Hard miss: served by the provider inferred from the workspace's configured model, using encrypted workspace credentials.
- Missing hard-query credentials return `402 Payment Required`.

There is no runtime `GEMINI_API_KEY` fallback. Store provider credentials through the dashboard or `PUT /admin/v1/workspaces/{workspace_slug}/credentials/{provider}`.

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
