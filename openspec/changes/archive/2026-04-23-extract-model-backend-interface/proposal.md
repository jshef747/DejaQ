## Why

Local text-generation models are currently loaded directly inside FastAPI services via `llama-cpp-python`. That works for development, but it couples pipeline logic to one execution mode, keeps inference in-process, and makes it hard to switch to an external model server for better concurrency and deployment flexibility.

## What Changes

- Add a thin async model backend interface with one operation: given a configured model name and prompt payload, return a completion
- Introduce `InProcessBackend` to preserve current `llama-cpp-python` behavior for local development
- Introduce `OllamaBackend` to send equivalent generation requests to a configured Ollama HTTP server
- Refactor local model-using pipeline services to depend on the backend interface instead of constructing or holding `llama-cpp-python` models directly
- Add config for selecting which backend each pipeline service uses so backend swaps are a configuration-only change
- Preserve existing pipeline behavior, prompts, request/response contracts, and cache semantics

## Capabilities

### New Capabilities
- `model-backends`: Configurable backend abstraction for local text-generation pipeline steps, with interchangeable in-process and Ollama implementations

### Modified Capabilities

## Impact

- **`server/app/services/`** — new backend interface module plus refactors in `context_enricher.py`, `normalizer.py`, `llm_router.py`, and `context_adjuster.py`
- **`server/app/config.py`** — backend selection and Ollama connection settings
- **`server/app/main.py`** and startup wiring — initialize shared backend dependencies without changing HTTP behavior
- **`server/app/services/model_loader.py`** — retained behind `InProcessBackend` instead of being called from pipeline services directly
- **Deployment/runtime** — local dev can keep in-process inference; production can point selected services at Ollama with one config change
- **No breaking API changes** — DejaQ external behavior remains unchanged; this is internal refactoring only
