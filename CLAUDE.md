# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DejaQ is an LLM cost-optimization platform that reduces API costs through semantic caching, query classification, and hybrid model routing.

**Cache miss pipeline:** User Query → Context Enricher (Qwen 0.5B, makes query standalone) → Normalizer (Qwen 2.5, produces cache key) → Cache Filter (heuristics) → LLM gets **original query + history** (preserves tone) → Response to user → Background: Generalize response (Phi-3.5 Mini) → Store in ChromaDB (if filter passes)

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
# WebSocket test UI: open index.html in browser

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
| `DEJAQ_TRUSTED_THRESHOLD` | `3` | Minimum net-positive feedback score for relaxed cache matching |
| `DEJAQ_FLAG_THRESHOLD` | `-3` | Score at which a cache entry is flagged as unreliable |
| `DEJAQ_AUTO_DELETE_THRESHOLD` | `-5` | Score at which a cache entry is auto-deleted |
| `DEJAQ_TRUSTED_SIMILARITY` | `0.20` | Cosine distance ceiling for trusted (high-score) entries |
| `DEJAQ_SUPPRESSION_TTL` | `300` | Seconds to hold a storage suppression flag in Redis |

### Endpoints
- `GET /health` — health check
- `POST /normalize` — normalize a query
- `POST /chat` — full chat pipeline (normalize → cache check → LLM → respond)
- `POST /generalize` — test endpoint: strips tone from an answer to produce neutral version
- `GET /cache/entries` — cache viewer: list all cached entries with metadata
- `DELETE /cache/entries/{id}` — delete a single cache entry
- `POST /cache/entries/{id}/feedback` — submit positive/negative quality rating for a cache entry
- `GET /cache/entries/{id}/feedback` — retrieve timestamped feedback history for a cache entry
- `GET /conversations` — list all conversations (newest first)
- `GET /conversations/{id}/messages` — get conversation message history
- `DELETE /conversations/{id}` — delete a conversation
- `WS /ws/chat` — real-time WebSocket chat (with conversation history support)

## Architecture

```
app/
├── main.py              # FastAPI init, CORS, startup/shutdown, health check
├── config.py            # Centralized settings (Redis URL, feature flags)
├── celery_app.py        # Celery configuration (broker, queues, serialization)
├── routers/chat.py      # All endpoints (HTTP + WebSocket) + conversation CRUD
├── tasks/
│   └── cache_tasks.py   # Celery task: generalize_and_store_task (Phi-3.5 + ChromaDB)
├── services/
│   ├── model_loader.py  # ModelManager singleton (Qwen 0.5B, Qwen 1.5B, Llama 3.2 1B, Phi-3.5 Mini)
│   ├── normalizer.py    # Query cleaning via Qwen 2.5-0.5B
│   ├── llm_router.py    # Routes "easy"→Llama 3.2 1B local, "hard"→external API (stub)
│   ├── context_adjuster.py # generalize() strips tone via Phi-3.5 Mini, adjust() adds tone via Qwen 2.5-1.5B
│   ├── context_enricher.py # Rewrites context-dependent queries into standalone ones (Qwen 0.5B)
│   ├── cache_filter.py  # Smart heuristic filter: skips non-cacheable prompts (too short, filler, vague)
│   ├── conversation_store.py # In-memory multi-turn conversation history (max 20 messages)
│   ├── classifier.py    # NVIDIA DeBERTa-based prompt complexity classifier (easy/hard routing)
│   └── memory_chromaDB.py # ChromaDB semantic cache (PersistentClient, cosine ≤ 0.15)
├── schemas/chat.py      # ChatRequest/ChatResponse (Pydantic), includes conversation_id
├── models/              # TODO: DB models (PostgreSQL)
├── repositories/        # TODO: DB access layer
└── utils/logger.py      # Centralized logging config
index.html               # WebSocket chatbot test UI with cache diagnostics (project root)
```

**Key patterns:**
- ModelManager is a singleton — models load once on first use
- Models use GGUF format via `llama-cpp-python` for cross-platform GPU support (Metal/CUDA)
- All schemas use Pydantic BaseModel
- Conversation history is passed to the LLM for multi-turn context
- Cache miss triggers background generalization + storage via Celery task queue (falls back to in-process if Celery disabled) — only if cache filter passes
- Celery workers lazy-load their own model instances via ModelManager singleton (one per worker process)
- Context enricher rewrites follow-up queries ("tell me more") into standalone questions before normalization
- Cache filter skips storing trivial messages (filler words, too short, too vague)

## Coding Conventions

- **Never use `print()`** — use `logging.getLogger("dejaq.<module>")` via `app.utils.logger`
- **Package manager**: `uv` only (no pip)
- **Async/await** for all I/O operations
- **Strong typing** with Pydantic for all request/response models
- **Directory structure**: routers (endpoints) → services (business logic) → schemas (data models) → models (DB) → repositories (DB access)

## Models (actual)

| Role | Model | Size | Loader |
|------|-------|------|--------|
| Normalizer | Qwen 2.5-0.5B-Instruct | Q4_K_M | `ModelManager.load_qwen()` |
| Context Adjuster (adjust) | Qwen 2.5-1.5B-Instruct | Q4_K_M | `ModelManager.load_qwen_1_5b()` |
| Generalizer (strip tone) | Phi-3.5-Mini-Instruct | Q4_K_M | `ModelManager.load_phi()` |
| Local LLM (generation) | Llama 3.2-1B-Instruct | Q8_0 | `ModelManager.load_llama()` |
| Difficulty Classifier | NVIDIA DeBERTa-v3-base | Full | `ClassifierService` (singleton) |

## Current Status

**Working:** FastAPI WebSocket + HTTP, Normalizer (Qwen 0.5B), LLM Router (Llama 3.2 1B local), Context Adjuster (generalize via Phi-3.5 + adjust via Qwen 1.5B), Semantic cache (ChromaDB, cosine ≤ 0.15), Multi-turn conversation history (in-memory), Conversation CRUD endpoints, Background generalize+store on cache miss, Hardware acceleration (Metal/CUDA), Context Enricher (conversation-aware caching), Smart Cache Filter (skip non-cacheable prompts), Cache Viewer API + UI panel, Difficulty Classifier (NVIDIA DeBERTa — routes easy→local, hard→external), Celery + Redis task queue (non-blocking generalize+store for both HTTP and WebSocket)
**In progress:** Database integration (PostgreSQL)
**Planned:** External LLM APIs (GPT/Gemini), Feedback loop, React frontend, Persistent conversation storage (currently in-memory only), Offload user-facing inference to Celery inference queue (multi-user parallelism)

## Active Technologies
- Python 3.13+ + FastAPI + Uvicorn, ChromaDB (PersistentClient), redis-py (already present as Celery dependency), Pydantic v2, Celery (001-cache-feedback-loop)
- ChromaDB (entry metadata), Redis (feedback event history, suppression flags) (001-cache-feedback-loop)

## Recent Changes
- 001-cache-feedback-loop: Added Python 3.13+ + FastAPI + Uvicorn, ChromaDB (PersistentClient), redis-py (already present as Celery dependency), Pydantic v2, Celery
