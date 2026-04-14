## Why

DejaQ's semantic caching and smart routing pipeline delivers real cost savings, but today every client must use DejaQ's custom WebSocket or HTTP API. Requiring teams to rewrite their chatbot integration is a hard adoption blocker. By speaking OpenAI's wire format, any existing OpenAI-based product can switch to DejaQ by changing one URL — zero other code changes required.

## What Changes

- Add a new `POST /v1/chat/completions` endpoint that accepts OpenAI `ChatCompletionRequest` bodies and returns OpenAI `ChatCompletion` (and streaming `ChatCompletionChunk`) responses
- Add API key extraction middleware that reads the `Authorization: Bearer <key>` header and maps it to a DejaQ department/tenant identifier
- Map OpenAI message roles (`system`, `user`, `assistant`) to DejaQ's existing conversation history format
- Route the request through the full existing pipeline: context enricher → normalizer → cache check → LLM router → context adjuster → generalize+store
- Translate DejaQ's internal response back to an OpenAI-shaped response object (including `usage` token estimates)
- Support both non-streaming (`stream: false`) and streaming (`stream: true`, SSE `data: [DONE]`) response modes
- Expose the model field passthrough (client sends `"model": "gpt-4o"`, DejaQ routes via its own logic and echoes the requested model name back)

## Capabilities

### New Capabilities

- `openai-chat-completions`: OpenAI-compatible `POST /v1/chat/completions` endpoint — accepts OpenAI request schema, runs full DejaQ pipeline, returns OpenAI response schema (streaming + non-streaming)
- `api-key-auth`: Bearer token extraction middleware — reads `Authorization` header, validates key format, maps to a tenant/department context for future multi-tenant work

### Modified Capabilities

*(none — no existing spec-level requirements change)*

## Impact

- **New file**: `app/routers/openai_compat.py` — new router mounted at `/v1`
- **New file**: `app/schemas/openai_compat.py` — Pydantic models for OpenAI request/response shapes
- **New file**: `app/middleware/api_key.py` — Bearer key extraction (non-blocking; logs unknown keys, does not reject)
- **Existing**: `app/routers/chat.py` — core pipeline logic will be extracted/called from the new router (no behavior change)
- **Existing**: `app/main.py` — register new router + middleware
- **Dependencies**: no new packages required (`fastapi` SSE via `StreamingResponse` + `starlette`)
