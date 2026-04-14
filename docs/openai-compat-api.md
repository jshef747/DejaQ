# OpenAI-Compatible API

DejaQ exposes an OpenAI-compatible chat completions endpoint. Any client that works with the OpenAI SDK can point at DejaQ instead and get transparent semantic caching, query normalization, and model routing — no code changes required.

## Base URL

```
http://127.0.0.1:8000/v1
```

## Authentication

Pass any string as a Bearer token. Auth enforcement is not yet active — all requests are served. Unrecognized keys are logged and treated as `anonymous`.

```
Authorization: Bearer <your-api-key>
```

---

## POST /v1/chat/completions

### Request

```json
{
  "model": "gpt-4o",
  "messages": [
    { "role": "system", "content": "You are a helpful assistant." },
    { "role": "user",   "content": "Why is the sky blue?" }
  ],
  "stream": false,
  "max_tokens": 1024,
  "temperature": 0.7
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `model` | string | Yes | Any model name — used as an echo field in the response. DejaQ routes internally regardless of value. |
| `messages` | array | Yes | OpenAI-format message array. Supports `system`, `user`, and `assistant` roles. The last `user` message is the active query; prior messages are conversation history. |
| `stream` | boolean | No | `false` (default) returns a single JSON response. `true` returns an SSE stream. |
| `max_tokens` | integer | No | Max tokens for local model generation. Default: `1024`. Ignored on cache hits. |
| `temperature` | float | No | Accepted but currently unused (local model uses `0.7`). |

---

### Response (non-streaming)

```json
{
  "id": "chatcmpl-a1b2c3d4e5f6a1b2c3d4e5f6",
  "object": "chat.completion",
  "created": 1713100000,
  "model": "gpt-4o",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "The sky is blue because of Rayleigh scattering..."
      },
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

On a **cache hit**, `completion_tokens` and `total_tokens` equal `prompt_tokens` (no generation occurred).

---

### Response (streaming, `"stream": true`)

Server-Sent Events stream. Each event is a `data:` line containing a JSON chunk.

**First chunk** — carries role:
```
data: {"id":"chatcmpl-...","object":"chat.completion.chunk","created":1713100000,"model":"gpt-4o","choices":[{"index":0,"delta":{"role":"assistant","content":""},"finish_reason":null}]}
```

**Content chunks** — one per word:
```
data: {"id":"chatcmpl-...","object":"chat.completion.chunk","created":1713100000,"model":"gpt-4o","choices":[{"index":0,"delta":{"content":"The "},"finish_reason":null}]}
data: {"id":"chatcmpl-...","object":"chat.completion.chunk","created":1713100000,"model":"gpt-4o","choices":[{"index":0,"delta":{"content":"sky "},"finish_reason":null}]}
```

**Final chunk** — signals completion:
```
data: {"id":"chatcmpl-...","object":"chat.completion.chunk","created":1713100000,"model":"gpt-4o","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

data: [DONE]
```

---

### Response headers

Both streaming and non-streaming responses include:

| Header | Example | Description |
|---|---|---|
| `x-dejaq-model-used` | `gemma-4-e4b` | Which backend served the response: local model name, external model name, or `cache`. |
| `x-dejaq-conversation-id` | `chatcmpl-abc123` | Matches the `id` field in the response body. |

---

## Internal pipeline

Each request flows through the DejaQ pipeline before reaching any LLM:

```
Request
  └─ Context Enricher   — rewrites follow-up queries into standalone form
       └─ Normalizer     — lowercases + spell-corrects + opinion rewrite
            └─ Cache check (ChromaDB, cosine ≤ 0.15)
                 ├─ HIT  → Context Adjuster adds tone → return
                 └─ MISS → Classifier (easy / hard)
                               ├─ easy → Gemma 4 E4B (local)
                               └─ hard → External LLM (Gemini)
                                    └─ Background: generalize + store in cache
```

- **Cache hit**: `x-dejaq-model-used: cache`. Response is the generalized cached answer re-toned to match the current query's phrasing.
- **Easy miss**: `x-dejaq-model-used: gemma-4-e4b`. Served by the local Gemma 4 E4B GGUF model.
- **Hard miss**: `x-dejaq-model-used: <external-model>`. Requires `GEMINI_API_KEY` env var. Falls back to error message if not set.

---

## OpenAI SDK example

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8000/v1",
    api_key="any-string",
)

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[
        {"role": "user", "content": "Why is the sky blue?"}
    ],
)
print(response.choices[0].message.content)
print(response.headers.get("x-dejaq-model-used"))  # "cache" or "gemma-4-e4b"
```

### Streaming

```python
stream = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Explain quantum entanglement"}],
    stream=True,
)
for chunk in stream:
    print(chunk.choices[0].delta.content or "", end="", flush=True)
```
