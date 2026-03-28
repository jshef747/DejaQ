# Research: External LLM API Integration

## Decision: Use `openai` Python Library
- **Decision:** Integrate the `openai` library (>= 1.0.0) for all external LLM communications.
- **Rationale:** 
    - Industry standard for chat completion APIs.
    - Native support for `async` via `AsyncOpenAI`.
    - Simplified multi-turn history management using the `messages` list format.
    - Many other providers (Anthropic, Google via Vertex/AI Studio, local vLLM/Ollama) are increasingly compatible with this format or have similar SDK patterns.
- **Alternatives Considered:** 
    - `httpx`: Provides more control but requires manual implementation of retry logic, streaming (if needed later), and message formatting. Rejected in favor of the specialized SDK.

## Pattern: Singleton Async Client
- **Decision:** Implement `ExternalLLMService` as a singleton that manages a single `AsyncOpenAI` instance.
- **Rationale:** 
    - Follows DejaQ's "Singleton Model Management" constitution principle.
    - Reuses underlying connection pools for improved latency.
- **Findings:** The `AsyncOpenAI` client should be instantiated once and reused across requests.

## Integration Point: `LLMRouterService`
- **Findings:** The existing `LLMRouterService._call_external_api` is a synchronous stub that only takes a `query` string.
- **Update Required:** `LLMRouterService` needs to be updated to support async calls if `ExternalLLMService` is async. However, `LLMRouterService.generate_response` is currently **synchronous**.
- **Conflict:** DejaQ's constitution says "Async for I/O (HTTP)". External API calls are I/O.
- **Resolution:** `LLMRouterService.generate_response` should remain synchronous for local inference (llama-cpp-python), but the calling router (`app/routers/chat.py`) should handle the branch to either call the sync local service or the async external service. Alternatively, `LLMRouterService` can be made async, but local inference will still be blocking (which is fine per constitution).

## Configuration
- **New Variables:**
    - `OPENAI_API_KEY`: Required for authentication.
    - `EXTERNAL_MODEL_NAME`: Defaulting to `gpt-4o` or similar.
    - `EXTERNAL_API_BASE`: Optional, allows routing to other OpenAI-compatible providers.
