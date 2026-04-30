# DejaQ

DejaQ is an LLM gateway that reduces cost and latency with semantic caching, local routing, and organization-scoped provider credentials. Existing clients can use the OpenAI-compatible API while operators manage organizations, API keys, credentials, stats, and feedback through the management API, CLI, TUI, or dashboard.

## Runtime Flow

```text
OpenAI-compatible request
  -> context enrichment
  -> normalization
  -> ChromaDB semantic cache lookup
     -> hit: context adjuster re-tones cached answer
     -> miss: difficulty classifier
        -> easy: local model
        -> hard: org provider credential
  -> response
  -> background generalize + store when cacheable
```

## Repository Structure

```text
server/              FastAPI app, gateway, management API, CLI/TUI, Celery tasks
frontend/            Next.js dashboard using Supabase auth and /admin/v1/*
normalization-test/  Offline query-normalizer eval harness
enricher-test/       Offline context-enricher eval harness
adjuster-test/       Offline context-adjuster eval harness
docs/                Current product/API notes
openspec/            Archived specs and proposal history
```

## Quick Start

```bash
cd server
uv sync
uv run alembic upgrade head
redis-server
uv run uvicorn app.main:app --reload
```

Start a worker in a second `server/` terminal:

```bash
uv run celery -A app.celery_app:celery_app worker --queues=background --pool=solo --loglevel=info
```

For local development without Redis:

```bash
DEJAQ_USE_CELERY=false uv run uvicorn app.main:app --reload
```

## Frontend

```bash
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
```

The dashboard runs at `http://localhost:3000` and talks to the backend through `NEXT_PUBLIC_API_BASE_URL`.

## Main Interfaces

- `GET /health`
- `POST /v1/chat/completions` — OpenAI-compatible gateway, authenticated by DejaQ org API key
- `POST /v1/feedback` — cache feedback, authenticated by DejaQ org API key
- `/admin/v1/*` — management API, authenticated by Supabase JWT
- `dejaq-admin` — org, department, key, credential, stats, feedback, and demo seed CLI
- `dejaq-admin-tui` — terminal dashboard for operational workflows

See [docs/openai-compat-api.md](/Users/jonathansheffer/Desktop/Coding/DejaQ/docs/openai-compat-api.md), [docs/cli-instructions.md](/Users/jonathansheffer/Desktop/Coding/DejaQ/docs/cli-instructions.md), [server/README.md](/Users/jonathansheffer/Desktop/Coding/DejaQ/server/README.md), and [frontend/README.md](/Users/jonathansheffer/Desktop/Coding/DejaQ/frontend/README.md).

## Demo Flow

```bash
cd server
uv run dejaq-admin seed demo
echo "$OPENAI_API_KEY" | uv run dejaq-admin seed demo --provider-key-stdin openai
```

Demo dashboard account:

- Email: `demo@dejaq.local`
- Password: `demo1234`

## Verification

```bash
cd server
uv run pytest --collect-only -q
uv run pytest -q -m no_model

cd ../frontend
npx tsc --noEmit --pretty false
npm run build
```
