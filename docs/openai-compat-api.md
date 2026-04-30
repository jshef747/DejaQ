# OpenAI-Compatible API

DejaQ exposes `POST /v1/chat/completions` so OpenAI SDK clients can point at the gateway and receive semantic caching, local routing, and org-scoped external provider fallback.

## Base URL

```text
http://127.0.0.1:8000/v1
```

## Authentication

Gateway calls require a DejaQ organization API key:

```text
Authorization: Bearer <dejaq-org-api-key>
```

Use `dejaq-admin key generate --org <slug>` or the dashboard key screen to create keys. `/admin/v1/*` uses Supabase JWTs instead; those tokens are not accepted by the gateway.

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
| `x-dejaq-response-id` | Cache entry response id when feedback can be submitted |

## Pipeline Behavior

```text
request
  -> context enricher
  -> normalizer
  -> ChromaDB cache lookup
     -> hit: context adjuster + return
     -> miss: difficulty classifier
        -> easy: local model
        -> hard: encrypted org provider credential
  -> background generalize + store when cacheable
```

- Cache hit: `x-dejaq-model-used: cache`.
- Easy miss: served by the configured local model backend.
- Hard miss: served by the provider inferred from the org's configured model, using encrypted org credentials.
- Missing hard-query credentials return `402 Payment Required`.

There is no runtime `GEMINI_API_KEY` fallback. Store provider credentials through the dashboard, `/admin/v1/orgs/{org}/credentials/{provider}`, or `dejaq-admin credential`.

## SDK Example

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8000/v1",
    api_key="<dejaq-org-api-key>",
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
Authorization: Bearer <dejaq-org-api-key>
Content-Type: application/json
```

```json
{
  "response_id": "<x-dejaq-response-id>",
  "rating": "positive",
  "comment": "optional"
}
```
