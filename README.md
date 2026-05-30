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
server/              FastAPI app, gateway, management API, dejaq-admin CLI, Celery tasks
frontend/            Next.js dashboard (/admin/v1/*; Supabase auth optional)
chat/                Standalone Next.js chat app with server-side org API key proxy
evals/               Offline eval harnesses: enricher, normalizer, adjuster, validator
docs/                Product/API notes + getting-started.md
openspec/            Specs and proposal history
```

## Quick Start

Local development needs **no Supabase project and no `.env`** — the dashboard runs
in dev-bypass mode (no login) and the backend grants a dev-admin context.

Generation runs through **Ollama** (local or remote). Start it and pull the model tags first:

```bash
ollama serve
ollama pull qwen2.5:0.5b qwen2.5:1.5b gemma4:e2b gemma4:e4b phi3.5:latest
```

```bash
cd server
uv sync
uv run alembic upgrade head
cd ..
./start.sh --stack=all --mode=local         # cross-platform (macOS/Linux/Windows git-bash)
# remote Ollama: ./start.sh --stack=all --mode=remote --ollama-url=http://<host>:11434
```

Then open the dashboard at `http://localhost:3000/dashboard`, create an organization
and generate an API key, and use it as `Authorization: Bearer <key>` against the gateway
(or paste it into the chat app at `http://localhost:4000`).

Backend only, or manual launch:

```bash
./start.sh --stack=server --mode=local
# or, by hand:
redis-server
uv run uvicorn app.main:app --reload
uv run celery -A app.celery_app:celery_app worker --queues=background --pool=solo --loglevel=info
# without Redis:
DEJAQ_USE_CELERY=false uv run uvicorn app.main:app --reload
```

> **Dashboard auth:** blank Supabase env = dev bypass (no login). Fill `SUPABASE_URL` /
> `SUPABASE_ANON_KEY` (+ the frontend equivalents) to require real login for deployment.

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
- `/admin/v1/*` — management API; Supabase JWT in deployment, dev-admin context in local mode
- `dejaq-admin` — org, department, key, and stats CLI (headless/server-only bootstrap)

Responses include `X-DejaQ-Interaction-Id`, `X-DejaQ-Tier` (`cache`|`local`|`external`), and (when cached) `X-DejaQ-Response-Id` headers. See [docs/getting-started.md](docs/getting-started.md), [docs/openai-compat-api.md](docs/openai-compat-api.md), [docs/cli-instructions.md](docs/cli-instructions.md), [server/README.md](server/README.md), and [frontend/README.md](frontend/README.md).

## Bootstrap an org + key

Either through the dashboard (Organizations → create, Keys → generate) or headless via the CLI:

```bash
cd server
uv run dejaq-admin org create --name Demo
uv run dejaq-admin key generate --org demo
```

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
