## Why

Local model inference still effectively serializes requests when it runs inside the FastAPI process, so simultaneous users end up waiting behind one another. The backend abstraction from BI1a removed the pipeline coupling, but now the in-process path needs to behave concurrently and the project needs a simple proof of that behavior before operators choose a deployment mode.

## What Changes

- Ensure in-process local completion calls run off the main async event loop so concurrent requests can make progress while a model is generating
- Verify the Ollama backend preserves concurrent behavior under simultaneous requests because it uses async HTTP calls
- Add a simple concurrent load test that fires multiple requests, measures wall-clock time, and reports whether backend mode scales better than naive serialization
- Document the concurrency characteristics and operator expectations for each backend mode in `CLAUDE.md`
- Preserve pipeline logic, prompts, and public API behavior; this is concurrency and observability work around existing backends

## Capabilities

### New Capabilities
- `backend-load-testing`: A simple benchmark path for issuing concurrent requests and measuring backend wall-clock concurrency behavior

### Modified Capabilities
- `model-backends`: Backend implementations must support concurrent request handling appropriate to their transport mode and document those characteristics clearly

## Impact

- **`server/app/services/model_backends.py`** — concurrency behavior and backend execution details
- **`server/app/routers/openai_compat.py`** and related request path — validation under simultaneous local-model requests
- **`server/tests/`** or dedicated benchmark tooling — concurrent load test coverage
- **`CLAUDE.md`** — backend-mode concurrency guidance for operators
- **No breaking API changes** — same request/response contracts, improved concurrency only
