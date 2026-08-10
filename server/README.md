# DejaQ Server

FastAPI backend for the DejaQ gateway, semantic cache, management API, `dejaq-admin` CLI, and background cache tasks.

## Setup

```bash
cd server
uv sync
uv run alembic upgrade head
# Optional — only to override defaults:
# cp .env.example .env
```

For Apple Silicon local model acceleration:

```bash
CMAKE_ARGS="-DLLAMA_METAL=on" uv sync
```

For NVIDIA CUDA builds:

```bash
CMAKE_ARGS="-DLLAMA_CUBLAS=on" uv sync
```

## Run

Generation runs through Ollama. Start it and pull the tags first:

```bash
ollama serve
ollama pull qwen2.5:0.5b qwen2.5:1.5b gemma4:e2b gemma4:e4b
```

Recommended local stack:

```bash
redis-server
uv run uvicorn app.main:app --reload
uv run celery -A app.celery_app:celery_app worker --queues=background --pool=solo --loglevel=info
```

Single-process local fallback:

```bash
DEJAQ_USE_CELERY=false uv run uvicorn app.main:app --reload
```

The startup helper selects local vs remote Ollama:

```bash
../start.sh --stack=server --mode=local
../start.sh --stack=server --mode=remote --ollama-url=http://<host>:11434
```

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
| `DEJAQ_EXTERNAL_MODEL` | `gemini-2.5-flash` | Default hard-query model when workspace config has no override |
| `DEJAQ_ROUTING_THRESHOLD` | `0.3` | Default easy/hard threshold |
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
  tests/test_provider_clients_contract.py \
  tests/test_provider_clients_logging.py \
  tests/test_stats_service.py \
  tests/test_memory_chromadb.py
```
