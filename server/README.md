# DejaQ Server

FastAPI backend for the DejaQ gateway, semantic cache, management API, CLI/TUI, and background cache tasks.

## Setup

```bash
cd server
uv sync
uv run alembic upgrade head
cp .env.example .env
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

The startup helper can write deployment-mode env choices:

```bash
./scripts/start.sh --mode=in-process
./scripts/start.sh --mode=self-hosted --ollama-url=http://127.0.0.1:11434
./scripts/start.sh --mode=cloud --ollama-url=https://<ollama-endpoint>
```

## API Surfaces

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| `GET` | `/health` | none | Health and dependency status |
| `POST` | `/v1/chat/completions` | DejaQ org API key | OpenAI-compatible chat gateway |
| `POST` | `/v1/feedback` | DejaQ org API key | Positive/negative cache feedback |
| `GET/POST/...` | `/admin/v1/*` | Supabase JWT | Management API for dashboard and operators |

Hard-query external provider calls use encrypted per-org credentials stored through `/admin/v1/orgs/{org}/credentials/{provider}` or `dejaq-admin credential`. There is no runtime platform `GEMINI_API_KEY` fallback.

## Key Environment Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `SUPABASE_URL` | empty | Supabase project URL for management JWT verification |
| `SUPABASE_ANON_KEY` | empty | Supabase anon/public key |
| `SUPABASE_SERVICE_ROLE_KEY` | empty | Demo seed only |
| `DEJAQ_CREDENTIAL_ENCRYPTION_KEY` | empty | Fernet key for org provider credentials |
| `DEJAQ_REDIS_URL` | `redis://localhost:6379/0` | Celery broker/result backend |
| `DEJAQ_USE_CELERY` | `true` | Run background storage in Celery or in process |
| `DEJAQ_KEY_CACHE_TTL` | `60` | Org API key lookup cache TTL |
| `DEJAQ_STATS_DB` | `dejaq_stats.db` | SQLite request log path |
| `DEJAQ_LOG_LEVEL` | `INFO` | App log level |
| `DEJAQ_LOG_SHOW_CONTENT` | `false` | Include prompt/response content in request logs |
| `DEJAQ_EVICTION_FLOOR` | `-5.0` | Cache score floor for eviction |
| `DEJAQ_EXTERNAL_MODEL` | `gemini-2.5-flash` | Default hard-query model when org config has no override |
| `DEJAQ_ROUTING_THRESHOLD` | `0.3` | Default easy/hard threshold |
| `DEJAQ_CHROMA_HOST` | `127.0.0.1` | ChromaDB host |
| `DEJAQ_CHROMA_PORT` | `8001` | ChromaDB port |
| `DEJAQ_OLLAMA_URL` | `http://127.0.0.1:11434` | Shared Ollama endpoint |
| `DEJAQ_*_BACKEND` | `in_process` | `in_process` or `ollama` per model role |
| `DEJAQ_*_MODEL_NAME` | role-specific | Logical model labels emitted in traces/stats |

See `.env.example` for the complete editable template.

## CLI

```bash
uv run dejaq-admin --help
uv run dejaq-admin seed demo
uv run dejaq-admin-tui
```

The CLI manages orgs, departments, API keys, credentials, stats, feedback, and the demo workspace. Provider keys should be supplied through stdin or `DEJAQ_SEED_PROVIDER_KEY`, not command-line args.

## Architecture Map

```text
app/
  main.py                 FastAPI app and route registration
  config.py               Environment-backed settings
  routers/openai_compat.py /v1/chat/completions gateway
  routers/feedback.py     /v1/feedback gateway feedback
  routers/admin/          /admin/v1/* management API
  db/                     SQLAlchemy repos, models, migrations-backed schema
  services/               Pipeline, provider, auth, stats, feedback logic
  tasks/cache_tasks.py    Celery generalize-and-store task
  schemas/                Pydantic request/response contracts
cli/                      Rich/Textual admin tools
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
