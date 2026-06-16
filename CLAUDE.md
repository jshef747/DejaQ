# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DejaQ is an LLM cost-optimization platform that reduces API costs through semantic caching, query classification, and hybrid model routing.

**Cache miss pipeline:** User Query → Context Enricher (Qwen 1.5B + regex gate, makes query standalone) → Normalizer (Qwen 2.5, produces cache key) → Cache Filter (heuristics) → LLM gets **original query + history** (preserves tone) → Response to user → Background: Generalize response (Phi-3.5 Mini) → Store in ChromaDB (if filter passes)

**Cache hit pipeline:** User Query → Context Enricher → Normalizer → ChromaDB returns tone-neutral response (cosine ≤ 0.15) → **Cache Validator** (Gemma E2B checks cached answer covers the new query; INVALID → treat as miss) → Context Adjuster adds tone → Response to user

## Commands

### Setup
Run from `server/` — the Python project (pyproject.toml + uv.lock) lives there; there is no root project.
```bash
cd server

# Mac (Apple Silicon) - enables Metal GPU acceleration
CMAKE_ARGS="-DLLAMA_METAL=on" uv sync

# Windows (NVIDIA) - enables CUDA acceleration
$env:CMAKE_ARGS = "-DLLAMA_CUBLAS=on"; uv sync

# CPU only
uv sync
```

### Run
Generation runs through **Ollama** (local or remote). Start Ollama and pull the model tags first:
```bash
ollama serve
ollama pull qwen2.5:0.5b qwen2.5:1.5b gemma4:e2b gemma4:e4b phi3.5:latest
```

```bash
# Preferred: start from the repo root with stack + Ollama-mode selection
./start.sh

# Non-interactive examples:
./start.sh --stack=server --mode=local
./start.sh --stack=all --mode=local
./start.sh --stack=all --mode=remote --ollama-url=http://<host>:11434

# Manual (Terminal 1) Redis
redis-server

# Terminal 2: FastAPI
uv run uvicorn app.main:app --reload
# Server at http://127.0.0.1:8000
# UI: the chat/ Next.js app (http://localhost:4000)

# Terminal 3: Celery background worker (--pool=solo for single-worker safety)
uv run celery -A app.celery_app:celery_app worker --queues=background --pool=solo --loglevel=info

# Without Redis (fallback mode — generalize+store runs in-process):
DEJAQ_USE_CELERY=false uv run uvicorn app.main:app --reload
```

### Workspace model

DejaQ is multi-**workspace**: you (the operator) are above all workspaces and can create as many as needed. Each workspace owns API keys + provider credentials + LLM routing config; departments are cache partitions within a workspace. The workspace slug is the billing/isolation boundary — departments only segment the cache.

On first launch with an empty DB the dashboard routes to an **onboarding wizard**: create a workspace → department → reveal the one-time API key. The CLI `dejaq-admin workspace create --name <name>` is the headless alternative.

### Control-plane vs data-plane split

| Surface | Bound to | Protected by |
|---|---|---|
| Dashboard (`:3000`) | 127.0.0.1 | Localhost (+ optional Supabase JWT) |
| Admin API (`/admin/v1/*`) | 127.0.0.1 | `AdminLoopbackMiddleware` (403 from LAN) |
| Data plane (`/v1/*`) | 0.0.0.0 (LAN) | Workspace API key |

Remote admin access: `ssh -L 3000:localhost:3000 -L 8000:localhost:8000 user@server-ip` — see [docs/admin-access.md](docs/admin-access.md).

### Management auth modes (`/admin/v1/*`)

`config.AUTH_MODE` controls how the management API authenticates. It auto-selects
`local` when `SUPABASE_URL` is blank, `supabase` otherwise (override with `DEJAQ_AUTH_MODE`).

- **`local` (default — recommended for on-prem):** `require_management_auth` returns an unauthenticated dev-admin context (`ManagementAuthContext.local_dev()`); the dashboard opens with no login. Protected by localhost binding, not a password.
- **`supabase` (optional — for hosted/multi-user deployments):** validates a Supabase JWT per request. Set up a free project at [supabase.com](https://supabase.com), copy the Project URL + anon key into `server/.env` (`SUPABASE_URL`, `SUPABASE_ANON_KEY`) and the frontend env. The `users` + `user_workspace_memberships` tables back this mode (dormant under `local`).

Bootstrap a workspace + API key with the dashboard onboarding wizard or with:
`dejaq-admin workspace create --name "Acme"` then `dejaq-admin key generate --workspace acme`.

> **Note:** `/v1/chat/completions` and `/v1/feedback` always use DejaQ workspace API keys, never Supabase JWTs. Only `/admin/v1/*` is affected by `AUTH_MODE`.

### Environment Variables
Generation always runs through Ollama (`DEJAQ_OLLAMA_URL`); there is no per-role backend switch.

| Variable | Default | Description |
|----------|---------|-------------|
| `DEJAQ_AUTH_MODE` | auto | `local` (dev-admin bypass) or `supabase` (JWT). Auto: `local` when `SUPABASE_URL` blank, else `supabase` |
| `SUPABASE_URL` | `` | Supabase project URL — set to enable `supabase` auth mode for `/admin/v1/*` |
| `SUPABASE_ANON_KEY` | `` | Supabase anon/public key — used by management auth dependency in `supabase` mode |
| `SUPABASE_SERVICE_ROLE_KEY` | `` | Supabase service-role key — reserved for admin Supabase operations (not used at runtime auth) |
| `DEJAQ_REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL (broker + result backend) |
| `DEJAQ_USE_CELERY` | `true` | Set to `false` to disable Celery and run tasks in-process |
| `DEJAQ_ADMIN_LOOPBACK_ONLY` | `true` | Restrict `/admin/v1/*` to loopback peers (127.0.0.1/::1); set `false` behind a trusted reverse proxy |
| `DEJAQ_BIND_HOST` | `0.0.0.0` (start.sh) | Uvicorn listen host; defaults `127.0.0.1` for bare `uv run uvicorn` |
| `DEJAQ_KEY_CACHE_TTL` | `60` | Workspace API-key lookup cache TTL in seconds |
| `DEJAQ_STATS_DB` | `dejaq_stats.db` | Path to SQLite request log (used by `dejaq-admin stats`) |
| `DEJAQ_LOG_LEVEL` | `INFO` | App logging level |
| `DEJAQ_LOG_SHOW_CONTENT` | `false` | Include prompt/response content in request logs when explicitly enabled |
| `DEJAQ_EVICTION_FLOOR` | `-5.0` | Score floor for cache eviction; entries below this are deleted by the beat task |
| `DEJAQ_CREDENTIAL_ENCRYPTION_KEY` | `` | Fernet key used to encrypt workspace provider credentials. Generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`; back it up because losing it makes stored credentials unrecoverable |
| `DEJAQ_EXTERNAL_MODEL` | `gemini-2.5-flash` | Default hard-query model when workspace config has no override; provider is inferred from model name |
| `DEJAQ_ROUTING_THRESHOLD` | `0.3` | Default per-workspace LLM routing threshold used when no workspace override exists |
| `DEJAQ_CHROMA_HOST` | `127.0.0.1` | ChromaDB HTTP server host |
| `DEJAQ_CHROMA_PORT` | `8001` | ChromaDB HTTP server port |
| `DEJAQ_OLLAMA_URL` | `http://127.0.0.1:11434` | Ollama HTTP endpoint for all generation roles (local or remote) |
| `DEJAQ_OLLAMA_TIMEOUT_SECONDS` | `60.0` | Timeout for Ollama backend requests |
| `DEJAQ_ENRICHER_MODEL_NAME` | `qwen_1_5b` | Logical model label for context enricher (→ Ollama tag) |
| `DEJAQ_NORMALIZER_MODEL_NAME` | `gemma_e2b` | Logical model label for normalizer (→ Ollama tag) |
| `DEJAQ_LOCAL_LLM_MODEL_NAME` | `gemma_local` | Logical model label for local generation (→ Ollama tag) |
| `DEJAQ_GENERALIZER_MODEL_NAME` | `phi_generalizer` | Logical model label for background generalizer (→ Ollama tag) |
| `DEJAQ_CONTEXT_ADJUSTER_MODEL_NAME` | `qwen_1_5b` | Logical model label for context adjuster (→ Ollama tag) |
| `DEJAQ_VALIDATOR_MODEL_NAME` | `gemma_e2b` | Logical model label for cache-answer validator (→ Ollama tag) |
| `DEJAQ_VALIDATOR_ENABLED` | `true` | Validator is on by default; set `false` to disable (kill switch) |
| `DEJAQ_VALIDATOR_SKIP_DISTANCE` | `0.05` | Cache hits at or below this cosine distance skip the validator (near-identical match; embedding already guarantees correctness) |

### Endpoints
- `GET /health` — health check; also reports Celery worker status
- `POST /v1/chat/completions` — OpenAI Chat Completions-compatible chat (streaming + non-streaming); requires `Authorization: Bearer <workspace-api-key>` and optional `X-DejaQ-Department` header; response includes `X-DejaQ-Response-Id` header when cached or stored. Hard queries return HTTP 402 when the workspace has no credential for the configured external provider.
- `POST /v1/responses` — OpenAI Responses API endpoint (newer recommended format). Same auth and `X-DejaQ-*` headers. Body: `{model, input: string | [{role, content}...], instructions?, stream?, temperature?, max_output_tokens?}`. Non-streaming: `{id, object:"response", output:[...], output_text, usage:{input_tokens, output_tokens, total_tokens}}`. Streaming: typed SSE events (`response.created`, `response.output_text.delta`, `response.completed`, etc.). `previous_response_id` / `conversation` rejected with HTTP 400 — DejaQ is stateless; clients send full history in `input`. The `chat/` Next.js app is the reference client.
- `POST /v1/feedback` — thumbs-up/down feedback on a cached response; requires `Authorization: Bearer <workspace-api-key>`; body: `{"response_id": "<X-DejaQ-Response-Id value>", "rating": "positive"|"negative", "comment": "<optional>"}`; first negative deletes entry, subsequent negatives decrement score by 2.0; positive increments score by 1.0
- `/admin/v1/*` management endpoints — **loopback-only** (127.0.0.1); auth via `local` dev-admin (default) or Supabase JWT when `SUPABASE_URL` is set. In local mode no token is required:
  - `GET /admin/v1/whoami`
  - `GET|POST|DELETE /admin/v1/workspaces[/{slug}]`
  - `GET /admin/v1/departments`, `POST|DELETE /admin/v1/workspaces/{workspace_slug}/departments[/{dept_slug}]`
  - `GET|POST /admin/v1/workspaces/{workspace_slug}/keys`, `DELETE /admin/v1/keys/{key_id}`
  - `GET /admin/v1/stats/workspaces`, `GET /admin/v1/stats/workspaces/{workspace_slug}/departments`
  - `GET|PUT /admin/v1/workspaces/{workspace_slug}/llm-config`
  - `GET /admin/v1/workspaces/{workspace_slug}/credentials`
  - `PUT /admin/v1/workspaces/{workspace_slug}/credentials/{provider}`
  - `DELETE /admin/v1/workspaces/{workspace_slug}/credentials/{provider}`
  - `POST /admin/v1/workspaces/{workspace_slug}/test-provider`
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
│   ├── model_backends.py # OllamaBackend + MODEL_RUNTIME_SPECS (logical name → Ollama tag)
│   ├── service_factory.py # Builds pipeline services on the shared Ollama backend
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
│   ├── validator.py     # Cache-answer validator (Gemma E2B): VALID/INVALID judge on cache hits; INVALID → treat as miss
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
└── ui.py                # Shared Rich console helpers
```

**Key patterns:**
- All generation runs through Ollama (`OllamaBackend`); `service_factory` builds one shared backend from `DEJAQ_OLLAMA_URL` (local or remote)
- `MODEL_RUNTIME_SPECS` maps logical role names (e.g. `gemma_e2b`) to Ollama tags (e.g. `gemma4:e2b`)
- The DeBERTa difficulty classifier and BGE cache embeddings are the only in-process ML (torch); generation is not in-process
- All schemas use Pydantic BaseModel
- Client sends full message history in the `messages` array (stateless; no server-side conversation store)
- Cache miss triggers background generalization + storage via Celery task queue (falls back to in-process if Celery disabled) — only if cache filter passes
- Celery workers reach the same shared Ollama endpoint for generation (no per-worker model loading)
- Context enricher rewrites follow-up queries ("tell me more") into standalone questions before normalization
- Cache filter skips storing trivial messages (filler words, too short, too vague)
- Per-request stats logged to SQLite (fire-and-forget via asyncio.create_task)
- Feedback adjusts ChromaDB entry scores (+1.0 positive, −2.0 negative); first negative deletes immediately
- External LLM routing supports Google, OpenAI, and Anthropic provider clients through encrypted org credentials; `ExternalLLMService` is a singleton
- Org/dept/API-key data lives in SQLite (SQLAlchemy + Alembic); `dejaq.db` by default

### Management API

`/admin/v1/*` is a separate operator surface from the OpenAI-compatible `/v1/*` gateway. It requires Supabase JWT authentication; system access is reserved for configured service paths such as demo seeding.

The org API-key middleware skips `/admin/v1/*` before parsing or logging `Authorization`, so admin tokens are never treated as customer API keys.

## Coding Conventions

- **Never use `print()`** — use `logging.getLogger("dejaq.<module>")` via `app.utils.logger`
- **Package manager**: `uv` only (no pip)
- **Async/await** for all I/O operations
- **Strong typing** with Pydantic for all request/response models
- **Directory structure**: routers (endpoints) → services (business logic) → schemas (data models) → models (DB) → repositories (DB access)

## Models (actual)

| Role | Model | Ollama tag |
|------|-------|-----------|
| Context Enricher (v5) | Qwen 2.5-1.5B-Instruct | `qwen2.5:1.5b` |
| Normalizer (cleaning) | Qwen 2.5-0.5B-Instruct | `qwen2.5:0.5b` |
| Normalizer (opinion rewrite, v22) | Gemma 4 E2B-Instruct | `gemma4:e2b` |
| Cache Validator | Gemma 4 E2B-Instruct | `gemma4:e2b` |
| Context Adjuster (adjust) | Qwen 2.5-1.5B-Instruct | `qwen2.5:1.5b` |
| Generalizer (strip tone) | Phi-3.5-Mini-Instruct | `phi3.5:latest` |
| Local LLM (generation) | Gemma 4 E4B-Instruct | `gemma4:e4b` |
| Difficulty Classifier | NVIDIA DeBERTa-v3-base | in-process torch (not Ollama) |
| Cache embeddings | BAAI/bge-small-en-v1.5 | in-process torch (not Ollama) |

## Deployment Modes (Ollama local / remote)

All generation runs through Ollama. The DeBERTa classifier and BGE cache embeddings still load in-process (torch) on first request. ChromaDB starts with the app stack; Redis backs Celery (or set `DEJAQ_USE_CELERY=false` to run background storage in-process).

Pull the model tags once (anywhere Ollama runs):

```bash
ollama pull qwen2.5:0.5b qwen2.5:1.5b gemma4:e2b gemma4:e4b phi3.5:latest
```

**local** — Ollama on the same host (default `http://127.0.0.1:11434`):

```bash
ollama serve
./start.sh --stack=all --mode=local
```

**remote** — Ollama on a LAN/cloud host (private networking, VPN, or an authenticated proxy):

```bash
export DEJAQ_OLLAMA_URL=http://<host>:11434   # or https://<endpoint>
./start.sh --stack=server --mode=remote --ollama-url="$DEJAQ_OLLAMA_URL"
```

FastAPI stays lightweight and sends independent async HTTP requests to Ollama; total throughput is bounded by the Ollama host. For external (hard-query) provider credentials set `DEJAQ_CREDENTIAL_ENCRYPTION_KEY` (back it up; losing it is unrecoverable).

## Test Harnesses

Offline eval harnesses live under `evals/` (`enricher`, `normalizer`, `adjuster`, `validator`). Run from each directory with `uv`. Generated `reports/` are gitignored.

### evals/enricher/ — Context Enricher eval

```bash
cd evals/enricher

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

### evals/normalizer/ — Normalizer eval

```bash
cd evals/normalizer
uv run python -m harness.runner
```

Best config: `v22` (BGE-small embedder + opinion LLM gate) — 81% Hit@0.20.

### evals/adjuster/ — Context Adjuster eval

```bash
cd evals/adjuster
uv run python -m harness.runner
uv run python -m harness.runner --configs baseline_qwen_1_5b
uv run python -m harness.runner --metrics-only
```

Uses an LLM judge (requires `ANTHROPIC_API_KEY`) for scoring. Configs in `configs/`, datasets in `dataset/`.

## Current Status

**Working:** FastAPI HTTP, Normalizer (Qwen 0.5B, v22), LLM Router (Gemma 4 E4B local → provider-backed external LLMs), Context Adjuster (generalize via Phi-3.5 + adjust via Qwen 1.5B), Semantic cache (ChromaDB, cosine ≤ 0.15), Background generalize+store on cache miss, Context Enricher v5 (Qwen 1.5B + regex gate, 88.7% @0.15 across 5 datasets), Smart Cache Filter (skip non-cacheable prompts), Difficulty Classifier (NVIDIA DeBERTa — routes easy→local, hard→org credential backed provider), Celery + Redis task queue (non-blocking generalize+store), OpenAI-compatible endpoint with API-key auth + per-department cache namespacing, Org/department/API-key/credential management (SQLAlchemy + Alembic SQLite + `dejaq-admin` CLI), Stats tracking (SQLite + Rich CLI — `dejaq-admin stats`), Score-based cache eviction (Celery beat), Feedback API (score adjustments + delete on first negative), Web dashboard (Next.js) with local dev-bypass auth (Supabase JWT in deployment), Ollama-only generation (local or remote via `OllamaBackend`/service_factory — decouples inference from FastAPI for multi-user parallelism). DeBERTa classifier + BGE cache embeddings run in-process (torch). Hard-query runtime credentials come from encrypted `org_provider_credentials`.
**Planned:** File & image support (multimodal input pipeline), RAG within organizations (per-org document retrieval), PostgreSQL migration, Subject-extraction preprocessing for bare comparative failures ("Which is cheaper?" — 1.5B model not sufficient)

## Active Technologies

- Python 3.13+ + FastAPI + Uvicorn, ChromaDB (HttpClient), redis-py (Celery dependency), Pydantic v2, Celery, aiosqlite (request log), Rich (stats CLI), SQLAlchemy + Alembic (org/dept/key/credential DB, SQLite), cryptography/Fernet, google-genai, openai, anthropic

## Frontend (dashboard)

The web dashboard lives in `frontend/` (Next.js 16, TypeScript, Tailwind v4, App Router). It talks to the management API at `/admin/v1/*`. Setup and env vars: see [frontend/README.md](frontend/README.md).

> ⚠️ Next.js 16 differs from older versions — see [frontend/AGENTS.md](frontend/AGENTS.md). Notably the middleware file convention was renamed `middleware.ts` → `proxy.ts`; the project root `proxy.ts` is the active middleware.

**Auth modes** (mirrors backend `AUTH_MODE`, gated by `lib/authMode.ts` = `!NEXT_PUBLIC_SUPABASE_URL`):
- **Local dev (no `NEXT_PUBLIC_SUPABASE_URL`):** dashboard skips login; `lib/api.ts` sends `Authorization: Bearer dev-local` (backend ignores it in local mode). Dev only.
- **Supabase (deployment):** user signs in via `@supabase/ssr`; `lib/api.ts` attaches the session JWT to every `/admin/v1/*` call; FastAPI validates it. `/v1/chat/completions` and `/v1/feedback` always use DejaQ org API keys, never Supabase JWTs.

**CORS:** FastAPI must allow `http://localhost:3000` (`allow_origins` in `server/app/main.py`) for local development.
