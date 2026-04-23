## Context

DejaQ currently invokes local text-generation models directly from multiple pipeline services by calling `ModelManager.load_*()` and then `create_chat_completion(...)` on `llama-cpp-python` model objects. That pattern spreads backend-specific code across `context_enricher.py`, `normalizer.py`, `llm_router.py`, and `context_adjuster.py`, and it assumes inference always happens inside the FastAPI or worker process.

This change is a cross-cutting refactor. The product contract must stay identical: same prompts, same routing, same cache behavior, same HTTP API. Goal is only to introduce a stable boundary so local inference can run either in-process or through Ollama without rewriting pipeline logic.

Assumption for this change: backend abstraction covers current local completion-style model calls. `ClassifierService` remains on its existing DeBERTa path because it does not use `llama-cpp-python` and does not match the proposed `model + prompt -> completion` interface.

## Goals / Non-Goals

**Goals:**
- Introduce one async model backend interface for local completion-style inference
- Keep existing prompts, model roles, and service behavior unchanged
- Support two interchangeable implementations: in-process `llama-cpp-python` and remote Ollama HTTP
- Make backend selection per service configurable so switching deployment mode is a config-only change
- Centralize model-to-runtime mapping in one place instead of scattering it across services

**Non-Goals:**
- Changing pipeline business logic, routing thresholds, or prompt wording
- Replacing the external Gemini path
- Reworking `ClassifierService` to use an LLM backend
- Adding streaming, batching, retries, or load balancing beyond what current services need
- Eliminating `model_loader.py`; it remains the in-process implementation detail

## Decisions

### D1 — Add one async backend protocol with a single completion method

**Decision:** Define a small async interface, e.g. `complete(model_name, prompt, *, max_tokens, temperature) -> str`, and make pipeline services depend only on that interface.

**Rationale:** One method is enough for current local generation steps and keeps refactor narrow. Async interface also hides whether work happens in-process, in a threadpool, or over HTTP.

**Alternative:** Expose backend-specific methods like `create_chat_completion()` and pass full raw kwargs through. Rejected: leaks transport/runtime details into business logic and defeats abstraction.

### D2 — Normalize prompts at backend boundary, not inside each service

**Decision:** Backend client accepts a shared prompt payload shape representing existing chat-style prompts, and each backend translates that into its native request format.

**Rationale:** Current services already build structured message lists. Keeping prompt construction in services preserves behavior, while backend implementations own the conversion to `llama-cpp-python` or Ollama wire format.

**Alternative:** Flatten everything into plain strings before calling backend. Rejected: would force prompt rewrites across services and increase regression risk.

### D3 — Keep `model_loader.py` behind `InProcessBackend`

**Decision:** `InProcessBackend` becomes sole caller of `ModelManager`, preserving lazy singleton loading for dev and Celery workers.

**Rationale:** Fastest path to parity. Existing GGUF loading behavior stays intact, but no pipeline service reaches into it directly anymore.

**Alternative:** Delete `ModelManager` and rebuild all in-process loading around a new registry immediately. Rejected: larger refactor than needed for this change.

### D4 — Use config-driven service-to-backend selection plus model alias mapping

**Decision:** Add config for:
- backend type per service (`enricher`, `normalizer`, `local_llm`, `generalizer`, `context_adjuster`)
- one shared `DEJAQ_OLLAMA_URL` plus request timeout
- logical model names per service, mapped inside each backend to concrete runtime identifiers

**Rationale:** Backend selection is per service role only, not per individual model alias. That keeps config small and matches current need. Services should request logical model roles, not know backend-specific repo IDs or Ollama tags. One shared Ollama host keeps deployment simple while still making backend swaps a one-line config change.

**Alternative:** Per-alias backend config. Rejected for now: extra config complexity without a current use case.

**Alternative:** Per-service Ollama hosts. Rejected for now: one shared `DEJAQ_OLLAMA_URL` is enough; host splitting can be added later without changing the service abstraction.

### D5 — Instantiate backend clients once and inject shared instances

**Decision:** Build backend instances during app/service wiring and reuse them across requests. Services receive backend dependency during initialization rather than constructing models at import time.

**Rationale:** Prevents per-request setup cost, avoids hidden global state inside business logic, and makes tests able to stub a fake backend.

**Alternative:** Let each service lazily create its own backend. Rejected: duplicates config parsing and complicates lifecycle.

### D6 — Match current completion semantics first; optimize concurrency later

**Decision:** `OllamaBackend` uses simple async HTTP requests with conservative options matching current temperature/max-token usage. `InProcessBackend` may wrap blocking `llama-cpp-python` calls in `asyncio.to_thread` or equivalent so callers remain async.

**Rationale:** This change unlocks future deployment work without mixing in broader concurrency redesign. Behavior parity first.

**Alternative:** Move all local inference to background workers now. Rejected: changes execution model and expands scope beyond pure refactor.

## Risks / Trade-offs

- **Prompt translation drift between backends** → Keep shared prompt payload close to current `messages` structure; add parity smoke tests for both implementations
- **Config sprawl per service** → Use one structured settings section with validated backend enum values and sensible defaults
- **Behavior mismatch from differing model identifiers or Ollama templates** → Treat logical model names as canonical; backend-specific mapping lives in one registry
- **Async wrapper over blocking `llama-cpp-python` still limits throughput** → Accept for dev path; production concurrency goal comes from Ollama deployment mode
- **Import-time singleton assumptions in existing services** → Refactor service construction carefully so routers/tasks reuse shared service instances without changing behavior

## Migration Plan

1. Add backend interface, in-process implementation, Ollama implementation, and config defaults that preserve current in-process behavior.
2. Refactor local completion-style services to request completions through injected backend clients while keeping prompts unchanged.
3. Update app/task wiring to construct shared backend-backed services once.
4. Verify parity in default in-process mode.
5. Enable Ollama for selected services in non-dev environments by config only.

**Rollback:** Switch config back to `InProcessBackend` everywhere. If code rollback is needed, services can temporarily revert to direct `ModelManager` calls because no external API contract changes in this refactor.

## Open Questions

None.
