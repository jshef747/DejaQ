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
```

### Environment Variables
| Variable | Default | Description |
|----------|---------|-------------|
| `DEJAQ_REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL (broker + result backend) |
| `DEJAQ_USE_CELERY` | `true` | Set to `false` to disable Celery and run tasks in-process |
| `DEJAQ_STATS_DB` | `dejaq_stats.db` | Path to SQLite request log (used by `dejaq-admin stats`) |
| `DEJAQ_EVICTION_FLOOR` | `-5.0` | Score floor for cache eviction; entries below this are deleted by the beat task |
| `GEMINI_API_KEY` | `` | API key for Google Gemini (external LLM for hard queries) |
| `DEJAQ_EXTERNAL_MODEL` | `gemini-2.5-flash` | Gemini model name for hard-query routing |
| `DEJAQ_CHROMA_HOST` | `127.0.0.1` | ChromaDB HTTP server host |
| `DEJAQ_CHROMA_PORT` | `8001` | ChromaDB HTTP server port |

### Endpoints
- `GET /health` — health check; also reports Celery worker status
- `POST /v1/chat/completions` — OpenAI-compatible chat (streaming + non-streaming); requires `Authorization: Bearer <api-key>` and optional `X-DejaQ-Department` header; response includes `X-DejaQ-Response-Id` header when the response is cached or stored to cache
- `POST /v1/feedback` — thumbs-up/down feedback on a cached response; requires `Authorization: Bearer <api-key>`; body: `{"response_id": "<X-DejaQ-Response-Id value>", "rating": "positive"|"negative", "comment": "<optional>"}`; first negative deletes entry, subsequent negatives decrement score by 2.0; positive increments score by 1.0
- Org/department management endpoints — see `dejaq-admin` CLI (`dejaq-admin org`, `dept`, `key`, `stats`)

## Architecture

```
app/
├── main.py              # FastAPI init, CORS, startup/shutdown, health check
├── config.py            # Centralized settings (Redis URL, Gemini key, ChromaDB host/port, feature flags)
├── celery_app.py        # Celery configuration (broker, queues, serialization)
├── db/
│   ├── base.py          # SQLAlchemy declarative base
│   ├── session.py       # Sync session factory (SQLite via Alembic)
│   ├── org_repo.py      # Org CRUD
│   ├── dept_repo.py     # Department CRUD
│   ├── api_key_repo.py  # API key lookup + caching
│   └── models/
│       ├── org.py       # Organization ORM model
│       ├── department.py # Department ORM model (cache_namespace, org FK)
│       └── api_key.py   # ApiKey ORM model
├── dependencies/
│   └── auth.py          # FastAPI dependency: resolve org/dept from Bearer token
├── middleware/
│   └── api_key.py       # Bearer token → org/department resolution; sets request.state
├── routers/
│   ├── openai_compat.py # Sole chat endpoint (POST /v1/chat/completions), stateless, OpenAI-compatible
│   ├── departments.py   # Org/department CRUD
│   └── feedback.py      # POST /v1/feedback — score-based cache feedback
├── tasks/
│   └── cache_tasks.py   # Celery task: generalize_and_store_task (Phi-3.5 + ChromaDB)
├── services/
│   ├── model_loader.py  # ModelManager singleton (Qwen 0.5B, Qwen 1.5B, Gemma 4 E4B, Gemma 4 E2B, Phi-3.5 Mini)
│   ├── normalizer.py    # Query cleaning via Qwen 2.5-0.5B
│   ├── llm_router.py    # Routes "easy"→Gemma 4 E4B local, "hard"→Gemini
│   ├── external_llm.py  # Gemini client singleton (google-genai, async)
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

**Working:** FastAPI HTTP, Normalizer (Qwen 0.5B, v22), LLM Router (Gemma 4 E4B local → Gemini 2.5 Flash external), Context Adjuster (generalize via Phi-3.5 + adjust via Qwen 1.5B), Semantic cache (ChromaDB, cosine ≤ 0.15), Background generalize+store on cache miss, Hardware acceleration (Metal/CUDA), Context Enricher v5 (Qwen 1.5B + regex gate, 88.7% @0.15 across 5 datasets), Smart Cache Filter (skip non-cacheable prompts), Difficulty Classifier (NVIDIA DeBERTa — routes easy→local, hard→Gemini), Celery + Redis task queue (non-blocking generalize+store), OpenAI-compatible endpoint with API-key auth + per-department cache namespacing, Org/department/API-key management (SQLAlchemy + Alembic SQLite + `dejaq-admin` CLI), Stats tracking (SQLite + Rich TUI — `dejaq-admin stats` / `dejaq-admin-tui`), Score-based cache eviction (Celery beat), Feedback API (score adjustments + delete on first negative), End-to-end demo script (`server/demo.sh`)
**In progress:** Offload user-facing inference to Celery inference queue (multi-user parallelism)
**Planned:** PostgreSQL migration, Subject-extraction preprocessing for bare comparative failures ("Which is cheaper?" — 1.5B model not sufficient)

## Active Technologies

- Python 3.13+ + FastAPI + Uvicorn, ChromaDB (HttpClient), redis-py (Celery dependency), Pydantic v2, Celery, aiosqlite (request log), Rich + Textual (stats TUI), SQLAlchemy + Alembic (org/dept/key DB, SQLite), google-genai (Gemini external LLM)
