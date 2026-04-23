## 1. Backend Abstraction

- [x] 1.1 Add shared async model backend interface and prompt payload type under `server/app/services/` or a dedicated backend module
- [x] 1.2 Implement `InProcessBackend` that maps logical model names to existing `ModelManager` loaders and returns text completions through the shared interface
- [x] 1.3 Implement `OllamaBackend` that sends async HTTP completion requests to configured Ollama endpoints and returns text through the same interface
- [x] 1.4 Centralize logical model-name to runtime-model mapping so pipeline services no longer know GGUF repo IDs or Ollama tags

## 2. Config & Wiring

- [x] 2.1 Add validated config for per-service backend selection, logical model names, Ollama base URL, and request timeout in `server/app/config.py`
- [x] 2.2 Add backend/service factory wiring so shared backend-backed service instances are created once and reused by FastAPI and worker code
- [x] 2.3 Keep default config on `in_process` for all local completion services so current development behavior remains unchanged

## 3. Pipeline Service Refactor

- [x] 3.1 Refactor `ContextEnricherService` to call the shared backend interface instead of holding a direct llama-cpp model
- [x] 3.2 Refactor `NormalizerService` opinion-rewrite path to call the shared backend interface instead of `ModelManager.load_gemma_e2b()`
- [x] 3.3 Refactor `LLMRouterService` local generation path to call the shared backend interface instead of `ModelManager.load_gemma()`
- [x] 3.4 Refactor `ContextAdjusterService` generalize and adjust paths to call the shared backend interface instead of direct model handles

## 4. Verification

- [x] 4.1 Add or update tests for backend selection, logical model mapping, and service invocation through fake backend stubs
- [x] 4.2 Run parity smoke tests in default `in_process` mode to confirm unchanged prompts, responses, and `/v1/chat/completions` behavior
- [x] 4.3 Run smoke test with at least one service role set to `ollama` to confirm config-only backend switching works end-to-end

## 5. Cleanup

- [x] 5.1 Remove direct `ModelManager` imports from local completion pipeline services after task 4.2 parity smoke tests pass, keeping old imports available as an A/B safety net until the new path is verified
