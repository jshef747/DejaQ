## 1. Pydantic Schemas

- [x] 1.1 Create `app/schemas/openai_compat.py` with `OAIMessage`, `OAIChatRequest`, `OAIChoice`, `OAIUsage`, `OAIChatResponse` models (extra fields allowed)
- [x] 1.2 Add `OAIStreamDelta`, `OAIStreamChoice`, `OAIChatChunk` models for SSE streaming shape

## 2. API Key Middleware

- [x] 2.1 Create `app/middleware/api_key.py` with `ApiKeyMiddleware` (Starlette `BaseHTTPMiddleware`) that extracts `Authorization: Bearer <token>` and sets `request.state.api_key` and `request.state.tenant_id`
- [x] 2.2 Log WARNING for unrecognized tokens (redact to first 8 chars + `...`); set `tenant_id = "anonymous"` for missing/unknown keys

## 3. OpenAI-Compatible Router

- [x] 3.1 Create `app/routers/openai_compat.py` with `POST /v1/chat/completions` handler
- [x] 3.2 Implement message extraction: last `user` message → query, preceding messages → history, `system` messages → system prompt override
- [x] 3.3 Wire the full pipeline: context enricher → normalizer → cache lookup → LLM router (pass `max_tokens` from request) → context adjuster → background generalize+store (reuse service layer, do not call `chat.py` internals)
- [x] 3.4 Build non-streaming response path: construct `OAIChatResponse` with echoed `model`, `usage` estimates, `x-dejaq-model-used` header, and `x-dejaq-conversation-id` header
- [x] 3.5 Build streaming response path: `StreamingResponse` with async generator yielding `data: <OAIChatChunk json>\n\n` chunks; final chunk sets `finish_reason: "stop"`; terminate with `data: [DONE]\n\n`; include `x-dejaq-conversation-id` and `x-dejaq-model-used` headers
- [x] 3.6 For cache hits in streaming mode, chunk the cached response string word-by-word through the SSE generator; set `x-dejaq-model-used: cache`

## 4. App Registration

- [x] 4.1 Register `ApiKeyMiddleware` in `app/main.py`
- [x] 4.2 Mount `openai_compat` router in `app/main.py` with prefix `/v1`

## 5. Verification

- [x] 5.1 Smoke-test non-streaming: `curl -X POST http://localhost:8000/v1/chat/completions -H "Authorization: Bearer test" -d '{"model":"gpt-4o","messages":[{"role":"user","content":"What is 2+2?"}]}'`
- [x] 5.2 Smoke-test streaming: same request with `"stream": true` and verify SSE chunks arrive
- [x] 5.3 Smoke-test cache hit: repeat the same query and verify `x-dejaq-model-used: cache` in response headers
- [x] 5.4 Smoke-test with `openai` Python SDK: point `base_url` at `http://localhost:8000/v1`, set any `api_key`, call `client.chat.completions.create(...)` and verify no SDK errors
