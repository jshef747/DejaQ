# DejaQ

DejaQ is an LLM gateway that reduces cost and latency with semantic caching, local routing, and organization-scoped provider credentials. Existing clients can use the OpenAI-compatible API while operators manage organizations, API keys, credentials, stats, and feedback through the management API, CLI, TUI, or dashboard.

## Project Document

[Project document](https://docs.google.com/document/d/18XAP_r1MI7rwU2BvKt5mA25AI7YqmIRA5KEmLbwauAo/edit?tab=t.0)

## Runtime Flow

```text
OpenAI-compatible request
  -> context enrichment
  -> normalization
  -> ChromaDB semantic cache lookup
     -> hit: cache validator (Gemma E2B) checks coverage
        -> VALID: context adjuster re-tones cached answer
        -> INVALID: treat as miss
     -> miss: difficulty classifier
        -> easy: local model (Gemma 4 E4B)
        -> hard: org provider credential (OpenAI / Anthropic / Google)
  -> response
  -> background generalize + store when cacheable
```

## Repository Structure

```text
server/              FastAPI app, gateway, management API, CLI/TUI, Celery tasks
frontend/            Next.js dashboard using Supabase auth and /admin/v1/*
chat/                Standalone Next.js chat app with server-side org API key proxy
normalization-test/  Offline query-normalizer eval harness
enricher-test/       Offline context-enricher eval harness
adjuster-test/       Offline context-adjuster eval harness
validator-test/      Offline cache-answer validator (Gemma E2B) eval harness
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

Or use the root startup script:

```bash
./start.sh --stack=server --mode=in-process
./start.sh --stack=all --mode=in-process
```

## Frontend

```bash
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
```

The dashboard runs at `http://localhost:3000` and talks to the backend through `NEXT_PUBLIC_API_BASE_URL`.

## Chat

```bash
cd chat
npm install
cp .env.local.example .env.local
npm run dev
```

Fill `DEJAQ_API_KEY` in `chat/.env.local`. The chat app runs at `http://localhost:4000`, calls its own `/api/*` routes from the browser, and those server routes forward to the backend through `DEJAQ_API_BASE_URL`.

## Main Interfaces

- `GET /health`
- `POST /v1/chat/completions` — OpenAI Chat Completions-compatible gateway, authenticated by DejaQ org API key
- `POST /v1/responses` — OpenAI Responses API (newer recommended format), same auth, stateless (`previous_response_id` rejected)
- `POST /v1/feedback` — cache feedback with optional thumbs-down escalation to the next serving tier (cache → local → external), authenticated by DejaQ org API key
- `/admin/v1/*` — management API, authenticated by Supabase JWT
- `dejaq-admin` — org, department, key, credential, stats, feedback, and demo seed CLI
- `dejaq-admin-tui` — terminal dashboard for operational workflows

Responses include `X-DejaQ-Interaction-Id`, `X-DejaQ-Tier` (`cache`|`local`|`external`), and (when cached) `X-DejaQ-Response-Id` headers. See [docs/openai-compat-api.md](docs/openai-compat-api.md), [docs/cli-instructions.md](docs/cli-instructions.md), [server/README.md](server/README.md), and [frontend/README.md](frontend/README.md).

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

cd ../chat
npx tsc --noEmit --pretty false
npm run build
```
