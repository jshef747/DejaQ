# DejaQ Server

FastAPI backend for the DejaQ gateway, semantic cache, management API, `dejaq-admin` CLI, and background cache tasks.

## Setup and Run

The setup and run steps (Ollama tags to pull, `uv sync`, `alembic upgrade head`,
`start.sh`, the redis/uvicorn/celery stack, and the `DEJAQ_USE_CELERY=false` single-process
fallback) live in the root [Quick Start](../README.md#quick-start) so they only have to change
in one place. Server-only notes below.

Local model acceleration builds (optional):

```bash
CMAKE_ARGS="-DLLAMA_METAL=on" uv sync   # Apple Silicon (Metal)
CMAKE_ARGS="-DLLAMA_CUBLAS=on" uv sync  # NVIDIA (CUDA)
```

The five pipeline generation roles default to `granite4.1:3b` (normalizer, generalizer,
validator), `qwen2.5:1.5b` (context enricher, adjuster) and `gemma4:e4b` (local answering),
mapped from logical labels in `app/services/model_backends.py::MODEL_RUNTIME_SPECS`. None of
them is fixed: each is per-workspace configurable on the dashboard **Pipeline** page (see the
`DEJAQ_*_MODEL_NAME` defaults below), so the tags you actually need are whatever your
workspaces are configured to use.

## API Surfaces

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| `GET` | `/health` | none | Health and dependency status |
| `POST` | `/v1/chat/completions` | DejaQ workspace API key | OpenAI-compatible chat gateway |
| `POST` | `/v1/feedback` | DejaQ workspace API key | Positive/negative cache feedback |
| `GET/POST/...` | `/admin/v1/*` | dev-admin (loopback-only) | Management API for dashboard and operators |

Management auth is unconditional dev-admin: `/admin/v1/*` requires no credential and is protected only by loopback binding (`AdminLoopbackMiddleware`).

Hard-query external provider calls use encrypted per-workspace credentials stored through `/admin/v1/workspaces/{workspace_slug}/credentials/{provider}` or the dashboard. There is no runtime platform `GEMINI_API_KEY` fallback.

## Key Environment Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `DEJAQ_CREDENTIAL_ENCRYPTION_KEY` | empty | Fernet key for workspace provider credentials |
| `DEJAQ_REDIS_URL` | `redis://localhost:6379/0` | Celery broker/result backend |
| `DEJAQ_USE_CELERY` | `true` | Run background storage in Celery or in process |
| `DEJAQ_KEY_CACHE_TTL` | `60` | Workspace API key lookup cache TTL |
| `DEJAQ_STATS_DB` | `dejaq_stats.db` | SQLite request log path |
| `DEJAQ_LOG_LEVEL` | `INFO` | App log level |
| `DEJAQ_LOG_SHOW_CONTENT` | `false` | Include prompt/response content in request logs |
| `DEJAQ_EVICTION_FLOOR` | `-5.0` | Cache score floor for eviction |
| `DEJAQ_EXTERNAL_MODEL` | unset (no default) | Server-wide fallback hard-query model when a workspace has no `external_model` override. There is no baked-in default: with neither this nor a workspace override set, a hard query returns 422 naming the fix rather than being silently routed to some provider |
| `DEJAQ_ROUTING_THRESHOLD` | `0.50` | Default easy/hard threshold |
| `DEJAQ_CHROMA_HOST` | `127.0.0.1` | ChromaDB host |
| `DEJAQ_CHROMA_PORT` | `8001` | ChromaDB port |
| `DEJAQ_OLLAMA_URL` | `http://127.0.0.1:11434` | Ollama endpoint for all generation (local or remote) |
| `DEJAQ_*_MODEL_NAME` | role-specific | Logical model labels mapped to Ollama tags |

See `.env.example` for the complete editable template.

## CLI

```bash
uv run dejaq-admin --help
uv run dejaq-admin workspace create --name Demo
uv run dejaq-admin key generate --workspace demo
uv run dejaq-admin stats
```

The `dejaq-admin` CLI manages workspaces, departments, API keys, knowledge-base documents,
and stats — the headless/server-only bootstrap path. Provider credentials and feedback are
managed through the dashboard or `/admin/v1/*`. Full command reference:
[docs/cli-instructions.md](../docs/cli-instructions.md).

## Architecture Map

```text
app/
  main.py                 FastAPI app and route registration
  config.py               Environment-backed settings
  routers/openai_compat.py /v1/chat/completions gateway
  routers/feedback.py     /v1/feedback gateway feedback
  routers/admin/          /admin/v1/* management API
  db/                     SQLAlchemy repos, models, migrations-backed schema
  services/               Pipeline, provider, stats, feedback logic
  tasks/cache_tasks.py    Celery generalize-and-store task
  schemas/                Pydantic request/response contracts
cli/                      Rich-based dejaq-admin CLI
```

## Tests

```bash
uv run pytest --collect-only -q
uv run pytest -q -m no_model
uv run pytest -q \
  tests/test_admin_api_resources.py \
  tests/test_feedback_service.py \
  tests/test_openai_compat_smoke.py \
  tests/test_litellm_transport_contract.py \
  tests/test_provider_temperature_and_errors.py \
  tests/test_stats_service.py \
  tests/test_memory_chromadb.py
```
