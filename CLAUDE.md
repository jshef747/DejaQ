# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DejaQ is an LLM cost-optimization platform that reduces API costs through semantic caching, query classification, and hybrid model routing.

**Cache miss pipeline:** User Query → Context Enricher (Qwen 1.5B + regex gate, makes query standalone) → Normalizer (Qwen 2.5, produces cache key) → Cache Filter (heuristics) → LLM gets **original query + history** (preserves tone) → Response to user → Background: Generalize response (Phi-3.5 Mini) → Store in ChromaDB (if filter passes)

**Cache hit pipeline:** User Query → Context Enricher → Normalizer → ChromaDB returns tone-neutral response (cosine ≤ 0.15) → Context Adjuster adds tone → Response to user

## Commands

### Setup
```bash
# Mac (Apple Silicon) - enables Metal GPU acceleration
CMAKE_ARGS="-DLLAMA_METAL=on" uv sync

# Windows (NVIDIA) - enables CUDA acceleration
$env:CMAKE_ARGS = "-DLLAMA_CUBLAS=on"; uv sync

# CPU only
uv sync
```

### Run
```bash
# Preferred: start the full local stack with deployment-mode selection
./server/scripts/start.sh

# Terminal 1: Start Redis
redis-server

# Terminal 2: Start FastAPI
uv run uvicorn app.main:app --reload
# Server at http://127.0.0.1:8000
# Demo UI: open server/openai-compat-demo.html in browser

# Terminal 3: Start Celery background worker (--pool=solo required for Metal/GPU compatibility)
uv run celery -A app.celery_app:celery_app worker --queues=background --pool=solo --loglevel=info

# Without Redis (fallback mode — generalize+store runs in-process):
DEJAQ_USE_CELERY=false uv run uvicorn app.main:app --reload

# Benchmark backend concurrency directly
cd server
uv run python scripts/benchmark_backend_concurrency.py --backend in_process --model qwen_0_5b --concurrency 10
uv run python scripts/benchmark_backend_concurrency.py --backend ollama --model qwen_0_5b --concurrency 10
```

### Supabase Setup (Management API)

The `/admin/v1/*` management API requires a Supabase project for JWT authentication.

1. Create a free project at [supabase.com](https://supabase.com).
2. Go to **Project Settings → API** and copy the **Project URL** and **anon/public key**.
3. Add to `server/.env`:
   ```
   SUPABASE_URL=https://<project-id>.supabase.co
   SUPABASE_ANON_KEY=eyJ...
   ```
4. Optionally add the **service_role** key for demo seeding (creates the demo Supabase Auth user):
   ```
   SUPABASE_SERVICE_ROLE_KEY=eyJ...
   ```
5. Run the Alembic migration to add users and membership tables:
   ```bash
   cd server && uv run alembic upgrade head
   ```
6. Seed the demo workspace (demo org, departments, user, sample stats):
   ```bash
   cd server && uv run dejaq-admin seed demo
   ```
   To seed the demo org's external LLM credential without putting the key on argv:
   ```bash
   echo $GEMINI_API_KEY | uv run dejaq-admin seed demo --provider-key-stdin google
   DEJAQ_SEED_PROVIDER_KEY=google:$GEMINI_API_KEY uv run dejaq-admin seed demo
   ```
   Demo credentials: `demo@dejaq.local` / `demo1234`

> **Note:** `/v1/chat/completions` and `/v1/feedback` continue to use DejaQ org API keys, not Supabase JWTs. Only `/admin/v1/*` uses Supabase authentication.

### Environment Variables
When adding a new `DEJAQ_*_BACKEND` variable, update the env examples in all three Deployment Modes blocks.

| Variable | Default | Description |
|----------|---------|-------------|
| `SUPABASE_URL` | `` | Supabase project URL — required for `/admin/v1/*` JWT auth |
| `SUPABASE_ANON_KEY` | `` | Supabase anon/public key — used by management auth dependency |
| `SUPABASE_SERVICE_ROLE_KEY` | `` | Supabase service-role key — only used by `dejaq-admin seed demo` |
| `DEJAQ_REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL (broker + result backend) |
| `DEJAQ_USE_CELERY` | `true` | Set to `false` to disable Celery and run tasks in-process |
| `DEJAQ_STATS_DB` | `dejaq_stats.db` | Path to SQLite request log (used by `dejaq-admin stats`) |
| `DEJAQ_EVICTION_FLOOR` | `-5.0` | Score floor for cache eviction; entries below this are deleted by the beat task |
| `DEJAQ_CREDENTIAL_ENCRYPTION_KEY` | `` | Fernet key used to encrypt org provider credentials. Generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`; back it up because losing it makes stored credentials unrecoverable |
| `GEMINI_API_KEY` | `` | Optional operator reference key for Google Gemini; no longer read at request time for hard-query routing |
| `DEJAQ_EXTERNAL_MODEL` | `gemini-2.5-flash` | Gemini model name for hard-query routing |
| `DEJAQ_ROUTING_THRESHOLD` | `0.3` | Default per-org LLM routing threshold used when no org override exists |
| `DEJAQ_CHROMA_HOST` | `127.0.0.1` | ChromaDB HTTP server host |
| `DEJAQ_CHROMA_PORT` | `8001` | ChromaDB HTTP server port |
| `DEJAQ_OLLAMA_URL` | `http://127.0.0.1:11434` | Shared Ollama HTTP endpoint for service roles using `ollama` backend |
| `DEJAQ_OLLAMA_TIMEOUT_SECONDS` | `60.0` | Timeout for Ollama backend requests |
| `DEJAQ_ENRICHER_BACKEND` | `in_process` | Backend mode for context enricher (`in_process` or `ollama`) |
| `DEJAQ_NORMALIZER_BACKEND` | `in_process` | Backend mode for normalizer opinion-rewrite path (`in_process` or `ollama`) |
| `DEJAQ_LOCAL_LLM_BACKEND` | `in_process` | Backend mode for local generation (`in_process` or `ollama`) |
| `DEJAQ_GENERALIZER_BACKEND` | `in_process` | Backend mode for background tone-stripping generalizer |
| `DEJAQ_CONTEXT_ADJUSTER_BACKEND` | `in_process` | Backend mode for tone-adjustment path on cache hits |

### Endpoints
- `GET /health` — health check; also reports Celery worker status
- `POST /v1/chat/completions` — OpenAI-compatible chat (streaming + non-streaming); requires `Authorization: Bearer <api-key>` and optional `X-DejaQ-Department` header; response includes `X-DejaQ-Response-Id` header when the response is cached or stored to cache. Hard queries return HTTP 402 Payment Required when the org has no credential for the configured external provider.
- `POST /v1/feedback` — thumbs-up/down feedback on a cached response; requires `Authorization: Bearer <api-key>`; body: `{"response_id": "<X-DejaQ-Response-Id value>", "rating": "positive"|"negative", "comment": "<optional>"}`; first negative deletes entry, subsequent negatives decrement score by 2.0; positive increments score by 1.0
- `/admin/v1/*` management endpoints — auth via Supabase JWT (Bearer token validated through Supabase Auth SDK); send a Supabase access token as `Authorization: Bearer <supabase-access-token>`:
  - `GET /admin/v1/whoami`
  - `GET|POST|DELETE /admin/v1/orgs[/{slug}]`
  - `GET /admin/v1/departments`, `POST|DELETE /admin/v1/orgs/{org_slug}/departments[/{dept_slug}]`
  - `GET|POST /admin/v1/orgs/{org_slug}/keys`, `DELETE /admin/v1/keys/{key_id}`
  - `GET /admin/v1/stats/orgs`, `GET /admin/v1/stats/orgs/{org_slug}/departments`
  - `GET|PUT /admin/v1/orgs/{org_slug}/llm-config`
  - `GET /admin/v1/orgs/{org_slug}/credentials`
  - `PUT /admin/v1/orgs/{org_slug}/credentials/{provider}`
  - `DELETE /admin/v1/orgs/{org_slug}/credentials/{provider}`
  - `POST /admin/v1/orgs/{org_slug}/test-provider`
  - `GET|POST /admin/v1/feedback`

## Architecture

```
app/
├── main.py              # FastAPI init, CORS, startup/shutdown, health check
├── config.py            # Centralized settings (Redis URL, credential encryption key, ChromaDB host/port, feature flags)
├── celery_app.py        # Celery configuration (broker, queues, serialization)
├── db/
│   ├── base.py          # SQLAlchemy declarative base
│   ├── session.py       # Sync session factory (SQLite via Alembic)
│   ├── org_repo.py      # Org CRUD
│   ├── dept_repo.py     # Department CRUD
│   ├── api_key_repo.py  # API key lookup + caching
│   ├── llm_config_repo.py # Per-org LLM config CRUD
│   ├── credential_repo.py # Per-org provider credential CRUD
│   └── models/
│       ├── org.py       # Organization ORM model
│       ├── department.py # Department ORM model (cache_namespace, org FK)
│       ├── api_key.py   # ApiKey ORM model
│       ├── org_llm_config.py # Org-level LLM routing config
│       └── org_provider_credentials.py # Encrypted org provider API keys
├── dependencies/
│   └── auth.py          # FastAPI dependency: resolve org/dept from Bearer token
├── middleware/
│   └── api_key.py       # Bearer token → org/department resolution; sets request.state
├── routers/
│   ├── admin/           # Management REST API (/admin/v1/*)
│   ├── openai_compat.py # Sole chat endpoint (POST /v1/chat/completions), stateless, OpenAI-compatible
│   ├── departments.py   # Org/department CRUD
│   └── feedback.py      # POST /v1/feedback — score-based cache feedback
├── tasks/
│   └── cache_tasks.py   # Celery task: generalize_and_store_task (Phi-3.5 + ChromaDB)
├── services/
│   ├── model_loader.py  # ModelManager singleton (Qwen 0.5B, Qwen 1.5B, Gemma 4 E4B, Gemma 4 E2B, Phi-3.5 Mini)
│   ├── admin_service.py # Shared org/dept/API-key management business logic
│   ├── stats_service.py # Shared request-log aggregate queries for CLI + admin API
│   ├── llm_config_service.py # Per-org LLM config defaults/update logic
│   ├── feedback_service.py # Shared cache feedback score/logging behavior
│   ├── normalizer.py    # Query cleaning via Qwen 2.5-0.5B
│   ├── llm_router.py    # Routes "easy"→Gemma 4 E4B local; hard queries go through provider clients
│   ├── credential_service.py # Fernet encryption/decryption and masked credential responses
│   ├── provider_inference.py # External model name → provider mapping
│   ├── external_llm.py  # External provider dispatcher
│   ├── llm_providers/   # Google, OpenAI, Anthropic provider clients
│   ├── context_adjuster.py # generalize() strips tone via Phi-3.5 Mini, adjust() adds tone via Qwen 2.5-1.5B
│   ├── context_enricher.py # Rewrites context-dependent queries into standalone ones (Qwen 1.5B + regex gate, v5)
│   ├── cache_filter.py  # Smart heuristic filter: skips non-cacheable prompts (too short, filler, vague)
│   ├── classifier.py    # NVIDIA DeBERTa-based prompt complexity classifier (easy/hard routing)
│   ├── memory_chromaDB.py # ChromaDB semantic cache (HttpClient, cosine ≤ 0.15); score-based eviction
│   └── request_logger.py  # Async SQLite request log (org, dept, latency, cache hit/miss, model, feedback)
├── schemas/
│   ├── chat.py          # ExternalLLMRequest/Response only
│   ├── openai_compat.py # OpenAI-compatible request/response schemas
│   ├── feedback.py      # FeedbackRequest schema
│   ├── org.py           # Org schemas
│   └── department.py    # Department schemas
└── utils/
    ├── logger.py        # Centralized logging config
    └── exceptions.py    # ExternalLLMError, ExternalLLMAuthError, ExternalLLMTimeoutError
cli/
├── admin.py             # dejaq-admin CLI (org, dept, key, stats subcommands)
├── stats.py             # Stats queries + Rich table rendering
├── tui.py               # dejaq-admin-tui — full Textual TUI dashboard
└── ui.py                # Shared Rich console helpers
```

**Key patterns:**
- ModelManager is a singleton — models load once on first use
- Models use GGUF format via `llama-cpp-python` for cross-platform GPU support (Metal/CUDA)
- In-process backend runs blocking local completion work in `asyncio.to_thread` so one request does not stall the main FastAPI event loop
- All schemas use Pydantic BaseModel
- Client sends full message history in the `messages` array (stateless; no server-side conversation store)
- Cache miss triggers background generalization + storage via Celery task queue (falls back to in-process if Celery disabled) — only if cache filter passes
- Celery workers lazy-load their own model instances via ModelManager singleton (one per worker process)
- Context enricher rewrites follow-up queries ("tell me more") into standalone questions before normalization
- Cache filter skips storing trivial messages (filler words, too short, too vague)
- Per-request stats logged to SQLite (fire-and-forget via asyncio.create_task)
- Feedback adjusts ChromaDB entry scores (+1.0 positive, −2.0 negative); first negative deletes immediately
- External LLM is Google Gemini via `google-genai` async client; `ExternalLLMService` is a singleton
- Org/dept/API-key data lives in SQLite (SQLAlchemy + Alembic); `dejaq.db` by default

### Management API

`/admin/v1/*` is a separate operator surface from the OpenAI-compatible `/v1/*` gateway. Auth is being migrated to Supabase JWT (per-user ownership); endpoints are currently unprotected while the JWT layer is implemented.

The org API-key middleware skips `/admin/v1/*` before parsing or logging `Authorization`, so admin tokens are never treated as customer API keys.

## Coding Conventions

- **Never use `print()`** — use `logging.getLogger("dejaq.<module>")` via `app.utils.logger`
- **Package manager**: `uv` only (no pip)
- **Async/await** for all I/O operations
- **Strong typing** with Pydantic for all request/response models
- **Directory structure**: routers (endpoints) → services (business logic) → schemas (data models) → models (DB) → repositories (DB access)

## Models (actual)

| Role | Model | Size | Loader |
|------|-------|------|--------|
| Context Enricher (v5) | Qwen 2.5-1.5B-Instruct | Q4_K_M | `ModelManager.load_qwen_1_5b()` |
| Normalizer (cleaning) | Qwen 2.5-0.5B-Instruct | Q4_K_M | `ModelManager.load_qwen()` |
| Normalizer (opinion rewrite, v22) | Gemma 4 E2B-Instruct | Q4_K_M | `ModelManager.load_gemma_e2b()` |
| Context Adjuster (adjust) | Qwen 2.5-1.5B-Instruct | Q4_K_M | `ModelManager.load_qwen_1_5b()` |
| Generalizer (strip tone) | Phi-3.5-Mini-Instruct | Q4_K_M | `ModelManager.load_phi()` |
| Local LLM (generation) | Gemma 4 E4B-Instruct | Q4_K_M | `ModelManager.load_gemma()` |
| Difficulty Classifier | NVIDIA DeBERTa-v3-base | Full | `ClassifierService` (singleton) |

## Backend Concurrency

DejaQ can run local completion roles inside the FastAPI process (`in_process`) or delegate them to an Ollama HTTP server (`ollama`). In-process mode keeps development simple but serializes access to each shared GGUF model; Ollama decouples inference from FastAPI so concurrent throughput is bounded by the Ollama host. See Deployment Modes for operator guidance, and use `server/scripts/benchmark_backend_concurrency.py` to compare modes on your hardware.

## Deployment Modes

All three modes require Python dependencies installed with `uv sync` and ChromaDB started with the app stack. Redis is the default shared prerequisite for Celery-backed background storage and eviction; for local-only runs, `DEJAQ_USE_CELERY=false` disables Celery and runs background storage in-process.

Use the combined startup script from the repo root:

```bash
./server/scripts/start.sh
```

The script prompts for a mode by default. Automation can pass `--mode=in-process`, `--mode=self-hosted`, or `--mode=cloud`; self-hosted and cloud also accept `--ollama-url=<url>` or `DEJAQ_OLLAMA_URL`.

### in-process (development)

Use this for laptop demos and local development when you do not want an external Ollama server. It is responsive for a single user because blocking GGUF calls run in worker threads, but concurrent requests that need the same loaded model still serialize for runtime safety.

```bash
export DEJAQ_USE_CELERY=true
export DEJAQ_CREDENTIAL_ENCRYPTION_KEY=<fernet-key>  # Back this up; losing it is unrecoverable.
export DEJAQ_ENRICHER_BACKEND=in_process
export DEJAQ_NORMALIZER_BACKEND=in_process
export DEJAQ_LOCAL_LLM_BACKEND=in_process
export DEJAQ_GENERALIZER_BACKEND=in_process
export DEJAQ_CONTEXT_ADJUSTER_BACKEND=in_process
```

Bring-up:

```bash
redis-server
cd server
uv run uvicorn app.main:app --reload
uv run celery -A app.celery_app:celery_app worker --queues=background --pool=solo --loglevel=info
```

Redis-free local fallback:

```bash
DEJAQ_USE_CELERY=false uv run uvicorn app.main:app --reload
```

### self-hosted (on-prem production)

Use this when FastAPI runs on one host and Ollama runs on a reachable LAN host. Pull the exact Ollama tags DejaQ requests:

```bash
ollama pull qwen2.5:0.5b
ollama pull qwen2.5:1.5b
ollama pull gemma4:e2b
ollama pull gemma4:e4b
ollama pull phi3.5:latest
```

```bash
export DEJAQ_USE_CELERY=true
export DEJAQ_CREDENTIAL_ENCRYPTION_KEY=<fernet-key>  # Back this up; losing it is unrecoverable.
export DEJAQ_OLLAMA_URL=http://<lan-host>:11434
export DEJAQ_ENRICHER_BACKEND=ollama
export DEJAQ_NORMALIZER_BACKEND=ollama
export DEJAQ_LOCAL_LLM_BACKEND=ollama
export DEJAQ_GENERALIZER_BACKEND=ollama
export DEJAQ_CONTEXT_ADJUSTER_BACKEND=ollama
```

Bring-up:

```bash
ollama serve
redis-server
cd server
uv run uvicorn app.main:app --reload
uv run celery -A app.celery_app:celery_app worker --queues=background --pool=solo --loglevel=info
```

This is the preferred production shape for concurrent users: FastAPI remains lightweight and independent async HTTP requests are sent to Ollama. Total throughput is bounded by the Ollama host CPU/GPU, model residency, and queueing capacity.

### cloud (future scaling)

Cloud mode is interface-compatible with self-hosted mode. Run Ollama on a cloud GPU instance, expose it to DejaQ over a secured path such as private networking, VPN, or an authenticated proxy, and use the same model tags:

```bash
ollama pull qwen2.5:0.5b
ollama pull qwen2.5:1.5b
ollama pull gemma4:e2b
ollama pull gemma4:e4b
ollama pull phi3.5:latest
```

```bash
export DEJAQ_USE_CELERY=true
export DEJAQ_CREDENTIAL_ENCRYPTION_KEY=<fernet-key>  # Back this up; losing it is unrecoverable.
export DEJAQ_OLLAMA_URL=https://<cloud-ollama-endpoint>
export DEJAQ_ENRICHER_BACKEND=ollama
export DEJAQ_NORMALIZER_BACKEND=ollama
export DEJAQ_LOCAL_LLM_BACKEND=ollama
export DEJAQ_GENERALIZER_BACKEND=ollama
export DEJAQ_CONTEXT_ADJUSTER_BACKEND=ollama
```

Bring-up is the same as self-hosted on the DejaQ side:

```bash
redis-server
cd server
uv run uvicorn app.main:app --reload
uv run celery -A app.celery_app:celery_app worker --queues=background --pool=solo --loglevel=info
```

Expect the same client behavior as self-hosted, with different operational trade-offs: higher network sensitivity, cloud GPU cold-start and utilization costs, and easier vertical scaling of the Ollama host.

## Test Harnesses

Three offline eval harnesses exist. Run from their respective directories with `uv`.

### enricher-test/ — Context Enricher eval

```bash
cd enricher-test

# Run all configs against all 5 datasets
uv run python -m harness.runner --all-datasets

# Run specific configs only
uv run python -m harness.runner --configs v2_regex_gate,v3_improved_fewshots --all-datasets

# Single dataset
uv run python -m harness.runner --configs baseline_qwen_0_5b --dataset dataset/conversations.json

# Recompute metrics from cached raw outputs (no inference)
uv run python -m harness.runner --metrics-only --raw-from reports/20260413-111941/conversations
```

**Metric:** Fidelity — cosine distance between embed(enriched) and embed(expected_standalone). Lower = better.
- `fidelity@0.15` = production cache similarity threshold
- `fidelity@0.20` = trusted entry threshold
- `passthrough rate` = % of `passthrough` category rows where enriched ≈ original (dist < 0.05)

**Datasets** (5 files, `dataset/conversations*.json`): `conversations` (general, 60 scenarios), `conversations_coding` (54), `conversations_science` (51), `conversations_culture` (49), `conversations_practical` (49). Each scenario has 3 phrasings × 5 categories: `pronoun_resolution`, `topic_continuation`, `multi_reference`, `passthrough`, `deep_chain`.

**Configs** (`configs/`):
| Config | Description | Key result |
|--------|-------------|------------|
| `baseline_qwen_0_5b` | Production enricher, no gate | ~85% @0.20, 60% passthrough |
| `v2_regex_gate` | Regex gate skips LLM on standalone queries | ~92% @0.20, 100% passthrough, −30ms |
| `v3_improved_fewshots` | v2 gate + `\bones?\b` fix + 8 few-shots | +3pp coding, neutral elsewhere |

**Known ceiling:** Qwen 0.5B cannot inject subject nouns into bare "which" comparatives ("Which is cheaper?" from gym vs home history) without domain-specific few-shots. Needs 1.5B or subject-extraction preprocessing to fix.

### normalization-test/ — Normalizer eval

```bash
cd normalization-test
uv run python -m harness.runner
```

Best config: `v22` (BGE-small embedder + opinion LLM gate) — 81% Hit@0.20.

### adjuster-test/ — Context Adjuster eval

```bash
cd adjuster-test
uv run python -m harness.runner
uv run python -m harness.runner --configs baseline_qwen_1_5b
uv run python -m harness.runner --metrics-only
```

Uses an LLM judge (requires `ANTHROPIC_API_KEY`) for scoring. Configs in `configs/`, datasets in `dataset/`.

## Current Status

**Working:** FastAPI HTTP, Normalizer (Qwen 0.5B, v22), LLM Router (Gemma 4 E4B local → provider-backed external LLMs), Context Adjuster (generalize via Phi-3.5 + adjust via Qwen 1.5B), Semantic cache (ChromaDB, cosine ≤ 0.15), Background generalize+store on cache miss, Hardware acceleration (Metal/CUDA), Context Enricher v5 (Qwen 1.5B + regex gate, 88.7% @0.15 across 5 datasets), Smart Cache Filter (skip non-cacheable prompts), Difficulty Classifier (NVIDIA DeBERTa — routes easy→local, hard→org credential backed provider), Celery + Redis task queue (non-blocking generalize+store), OpenAI-compatible endpoint with API-key auth + per-department cache namespacing, Org/department/API-key/credential management (SQLAlchemy + Alembic SQLite + `dejaq-admin` CLI), Stats tracking (SQLite + Rich TUI — `dejaq-admin stats` / `dejaq-admin-tui`), Score-based cache eviction (Celery beat), Feedback API (score adjustments + delete on first negative), End-to-end demo script (`scripts/demo.sh`), Three documented deployment modes (in-process / self-hosted / cloud) validated against the end-to-end demo. `GEMINI_API_KEY` is no longer read at request time; keep it only as operator reference, while runtime credentials come from `org_provider_credentials`.
**In progress:** Offload user-facing inference to Celery inference queue (multi-user parallelism)
**Planned:** PostgreSQL migration, Subject-extraction preprocessing for bare comparative failures ("Which is cheaper?" — 1.5B model not sufficient)

## Active Technologies

- Python 3.13+ + FastAPI + Uvicorn, ChromaDB (HttpClient), redis-py (Celery dependency), Pydantic v2, Celery, aiosqlite (request log), Rich + Textual (stats TUI), SQLAlchemy + Alembic (org/dept/key/credential DB, SQLite), cryptography/Fernet, google-genai, openai, anthropic

## Frontend (dashboard)

The web dashboard lives in `frontend/` at the repo root. It is a Next.js 16 app with TypeScript, Tailwind v4, and the App Router. Auth is Supabase email/password (`@supabase/ssr`). The dashboard talks to the FastAPI management API at `/admin/v1/*`, sending the Supabase JWT as a Bearer token on every request.

### Frontend setup

```bash
cd frontend
npm install
cp .env.local.example .env.local
# Fill in your Supabase project URL and anon key in .env.local
```

### Frontend dev server

```bash
cd frontend
npm run dev
# Dashboard at http://localhost:3000
```

### Frontend environment variables

| Variable | Description |
| -------- | ----------- |
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase project URL (`https://<id>.supabase.co`) |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase anon/public key |
| `NEXT_PUBLIC_API_BASE_URL` | FastAPI backend base URL (default: `http://127.0.0.1:8000`) |

### Demo account

Use the account seeded by `dejaq-admin seed demo`:

- Email: `demo@dejaq.local`
- Password: `demo1234`

### How auth works

1. User signs in via Supabase email/password → session cookie set by `@supabase/ssr`
2. Every management API call in `lib/api.ts` reads the session JWT and sends it as `Authorization: Bearer <token>` to the FastAPI backend
3. FastAPI validates the JWT via the Supabase Auth SDK on all `/admin/v1/*` routes
4. The `/v1/chat/completions` and `/v1/feedback` endpoints continue to use DejaQ org API keys — not Supabase JWTs

### CORS note

FastAPI CORS must allow `http://localhost:3000` for local development. If you see CORS errors, add `http://localhost:3000` to `allow_origins` in `server/app/main.py`.
