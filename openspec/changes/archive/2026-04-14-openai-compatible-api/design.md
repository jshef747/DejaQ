## Context

DejaQ's pipeline (enricher → normalizer → cache → LLM router → adjuster → generalize+store) is fully implemented in `app/routers/chat.py` and its services. All the intelligence lives there. The only missing piece is a front door that speaks OpenAI's wire format so that existing OpenAI clients need zero code changes.

OpenAI's `/v1/chat/completions` is the de-facto standard for LLM APIs. It accepts a list of messages with roles and returns either a full completion object or a stream of SSE chunks. Any client using the `openai` Python/JS SDK, LangChain, LlamaIndex, or direct HTTP can be pointed at DejaQ with only a base URL change.

Current state: DejaQ has `/ws/chat` (WebSocket) and `POST /chat` (custom schema). Neither is compatible with the OpenAI SDK.

## Goals / Non-Goals

**Goals:**
- Accept `POST /v1/chat/completions` with an OpenAI-shaped request body
- Return OpenAI-shaped responses (non-streaming + streaming SSE)
- Run the full existing DejaQ pipeline on every request
- Extract Bearer token from `Authorization` header and log/attach it as tenant context
- Pass through the `model` field from the request back in the response (DejaQ routes internally)
- No new dependencies

**Non-Goals:**
- Full OpenAI API parity (embeddings, images, audio, fine-tuning, assistants, etc.)
- Hard API key validation / tenant enforcement (logged only; enforcement is future work)
- Per-model capability negotiation
- Billing/usage metering
- OpenAI function calling / tool use support

## Decisions

### 1. New router, not modifying `/chat`

A separate `app/routers/openai_compat.py` mounted at `/v1` keeps OpenAI-compat logic isolated. The existing `/chat` endpoint is unchanged — teams already using DejaQ's native API are not affected. The new router calls the same service layer (`context_enricher`, `normalizer`, `memory_chromadb`, `llm_router`, `context_adjuster`), not `chat.py`'s internal functions.

*Alternative considered*: Modify `chat.py` to also accept OpenAI bodies. Rejected — mixing two schemas in one handler adds complexity and risks regressions in the existing API.

### 2. Pydantic schemas in `app/schemas/openai_compat.py`

All OpenAI request/response shapes defined as Pydantic v2 models. This keeps validation declarative and lets FastAPI auto-generate docs. Only the fields DejaQ actually uses are required; unknown fields are allowed through (`model_config = ConfigDict(extra="allow")`) so clients sending OpenAI-specific extras don't 400.

Key models:
- `OAIMessage` — `{role: str, content: str}`
- `OAIChatRequest` — `{model, messages, stream?, temperature?, ...}`
- `OAIChatResponse` — full completion object
- `OAIChatChunk` — SSE delta chunk

### 3. Streaming via `StreamingResponse` + SSE

For `stream: true`, use FastAPI's `StreamingResponse` with an async generator that yields `data: <json>\n\n` chunks and terminates with `data: [DONE]\n\n`. Token-by-token streaming from `llama-cpp-python` maps naturally to this. For cache hits, the cached response is chunked word-by-word to preserve the streaming UX.

*Alternative considered*: WebSocket upgrade. Rejected — OpenAI clients expect SSE, not WebSockets.

### 4. Message → conversation format mapping

OpenAI sends the full history in every request (`messages` array). DejaQ's pipeline expects the last user message as the query and prior turns as context. Mapping:

- Last message with `role: "user"` → current query
- All preceding messages → injected into conversation history for the LLM
- `role: "system"` messages → prepended to the LLM system prompt (passed as `system_prompt` override)

This means DejaQ's in-memory `conversation_store` is **bypassed** for OpenAI-compat requests — the client owns the history. A `conversation_id` derived from a hash of the initial system prompt + model is generated and attached for logging/cache attribution.

### 5. API key middleware (non-blocking)

`app/middleware/api_key.py` adds a lightweight Starlette middleware that reads `Authorization: Bearer <key>`. It attaches the key to `request.state.api_key`. Unknown or missing keys are logged at `WARNING` level but the request proceeds. This is the foundation for future tenant enforcement without breaking clients during rollout.

### 6. Token usage estimates in response

`llama-cpp-python` provides token counts after inference. For cache hits, estimate input tokens via `len(prompt.split()) * 1.3` (rough BPE estimate) and report 0 output tokens (response came from cache). This gives clients a plausible `usage` object without requiring a tokenizer roundtrip on every cache hit.

## Risks / Trade-offs

- **History ownership mismatch** → OpenAI clients send full history; DejaQ's enricher was designed for a stateful server-side history. Enricher may over-enrich when history is already fully resolved. Mitigation: pass full history to enricher as-is — it has a passthrough path for already-standalone queries.
- **Streaming cache hits feel fake** → Chunking a cached string word-by-word isn't true streaming. Mitigation: acceptable UX; indistinguishable from a fast model. Document behavior.
- **`model` field echo** → Clients sending `"model": "gpt-4o"` get `"gpt-4o"` back in the response even though DejaQ routed to Llama 1B. This is correct behavior for a proxy but could confuse debugging. Mitigation: add `x-dejaq-model-used` response header with the actual model.
- **No auth enforcement yet** → Any request with any Bearer token (or none) is served. Mitigation: log unknown keys; enforcement added in a follow-on change.

## Migration Plan

1. Deploy new router and middleware — purely additive, no existing routes change.
2. Clients change `base_url` to `http://<dejaq-host>/v1` and set any Bearer token.
3. No rollback needed — new routes can be disabled by removing the router registration in `main.py`.

## Resolved Decisions

**`x-dejaq-conversation-id` response header: yes.**
Always emit it. Zero cost to add, and it's the only way to correlate a client request to a DejaQ cache entry or log line without server-side tracing. Clients can ignore it; debugging sessions can't live without it.

**`max_tokens` passthrough: yes.**
Clients set `max_tokens` for a reason — budget control, UI constraints, test reproducibility. Silently ignoring it means DejaQ produces responses the client didn't ask for (too long, wrong format). Pass it directly to `llama-cpp-python`'s `max_tokens` parameter on cache miss. For cache hits the field is irrelevant (response already exists), so skip it.
