# DejaQ - AI Middleware & Organizational Memory

**DejaQ** is an intelligent middleware layer designed to optimize LLM interactions. It intelligently routes queries between a local semantic cache, lightweight local models (Llama/Qwen), and high-performance external APIs (GPT-4/Gemini) to minimize latency and cost.

## Quick Start

### 1. Prerequisites

- **Python 3.13+**
- **uv** (Fast Python package manager)
  - **Mac/Linux:** `curl -LsSf https://astral.sh/uv/install.sh | sh`
  - **Windows:** `powershell -c "irm https://astral.sh/uv/install.ps1 | iex"`
- **Redis** (message broker for background task queue)

#### Installing Redis

**Mac (Homebrew)**
```bash
brew install redis
brew services start redis
```

**Linux (Ubuntu/Debian)**
```bash
sudo apt update && sudo apt install redis-server
sudo systemctl start redis
sudo systemctl enable redis
```

**Windows**
Redis does not run natively on Windows. Choose one of these options:
- **WSL2 (Recommended):** Install WSL2, then follow the Linux instructions above
- **Memurai:** Native Windows Redis alternative — download from [memurai.com](https://www.memurai.com/)

---

### 2. Installation & Hardware Optimization

Clone the repository and navigate to the server directory:

```bash
git clone <your-repo-url>
cd dejaq/server
```

#### Enable GPU Acceleration

**Mac (Apple Silicon M1/M2/M3/M4)** — Metal acceleration
```bash
CMAKE_ARGS="-DLLAMA_METAL=on" uv sync
```

**Windows (NVIDIA GPU)** — CUDA acceleration
*Requires [CUDA Toolkit](https://developer.nvidia.com/cuda-downloads)*
```powershell
$env:CMAKE_ARGS = "-DLLAMA_CUBLAS=on"
uv sync
```

**Linux (NVIDIA GPU)** — CUDA acceleration
*Requires [CUDA Toolkit](https://developer.nvidia.com/cuda-downloads)*
```bash
CMAKE_ARGS="-DLLAMA_CUBLAS=on" uv sync
```

**CPU Only (any platform)**
```bash
uv sync
```

---

### 3. Running the Server

DejaQ requires three processes: Redis, the FastAPI server, and a Celery worker.

On the first run, the system will automatically download the necessary model files (~1GB).

**Mac / Linux**
```bash
# Terminal 1: Redis (skip if already running as a service)
redis-server

# Terminal 2: FastAPI server
uv run uvicorn app.main:app --reload

# Terminal 3: Celery background worker
uv run celery -A app.celery_app:celery_app worker --queues=background --pool=solo --loglevel=info
```

**Windows**
```powershell
# Terminal 1: Redis (via WSL2 or Memurai)
redis-server

# Terminal 2: FastAPI server
uv run uvicorn app.main:app --reload

# Terminal 3: Celery background worker
uv run celery -A app.celery_app:celery_app worker --queues=background --pool=solo --loglevel=info
```

**Server:** [http://127.0.0.1:8000](http://127.0.0.1:8000)
**WebSocket test UI:** Open `index.html` in your browser

#### Scaling with Multiple Workers

Each worker processes tasks sequentially (`--pool=solo`). To handle multiple users in parallel, run additional worker instances — each in its own terminal:

```bash
# Worker 1 (already running from step above)
uv run celery -A app.celery_app:celery_app worker --queues=background --pool=solo --loglevel=info --hostname=worker1@%h

# Worker 2 (new terminal)
uv run celery -A app.celery_app:celery_app worker --queues=background --pool=solo --loglevel=info --hostname=worker2@%h
```

Celery distributes tasks across workers automatically via Redis. Each worker loads its own copy of the Phi-3.5 model (~2.3GB RAM), so scale based on available memory.

> **Why `--pool=solo`?** The `prefork` pool uses `fork()` which crashes on macOS with Metal GPU acceleration (SIGABRT). The `solo` pool runs in-process and is compatible with all platforms (Mac, Windows, Linux). Parallelism is achieved by running multiple worker instances instead.

#### Running Without Redis (Fallback Mode)

For quick local development without Redis, you can disable Celery. Background tasks will run in-process (blocking for WebSocket):

```bash
DEJAQ_USE_CELERY=false uv run uvicorn app.main:app --reload
```

---

## Architecture

```
User Request
     |
     v
┌─────────────────────────────────────────────────────┐
│  FastAPI (uvicorn)                                  │
│  ├── Context Enricher (Qwen 0.5B)                  │
│  ├── Normalizer (Qwen 0.5B)                        │
│  ├── Cache Check (ChromaDB, cosine ≤ 0.15)         │
│  ├── Classifier (NVIDIA DeBERTa)                   │
│  ├── LLM Router (easy→Llama 1B / hard→external)    │
│  └── Context Adjuster (adjust tone via Qwen 1.5B)  │
└───────────────────┬─────────────────────────────────┘
                    │ .delay() (fire-and-forget)
                    v
              ┌───────────┐
              │   Redis    │  (message broker)
              └─────┬─────┘
                    v
┌─────────────────────────────────────────────────────┐
│  Celery Worker (background queue)                   │
│  ├── Generalize response (Phi-3.5 Mini)             │
│  └── Store in ChromaDB semantic cache               │
└─────────────────────────────────────────────────────┘
```

### File Structure

```
app/
├── main.py              # FastAPI init, CORS, health check
├── config.py            # Centralized settings (Redis URL, feature flags)
├── celery_app.py        # Celery configuration (broker, queues, serialization)
├── routers/chat.py      # All endpoints (HTTP + WebSocket) + conversation CRUD
├── tasks/
│   └── cache_tasks.py   # Celery task: generalize + store in cache
├── services/
│   ├── model_loader.py  # ModelManager singleton (lazy model loading)
│   ├── normalizer.py    # Query normalization (Qwen 0.5B)
│   ├── llm_router.py    # Routes easy→local Llama, hard→external API
│   ├── context_adjuster.py  # generalize() + adjust() for tone handling
│   ├── context_enricher.py  # Rewrites follow-up queries into standalone
│   ├── cache_filter.py      # Heuristic filter for non-cacheable prompts
│   ├── conversation_store.py # In-memory conversation history
│   ├── classifier.py        # DeBERTa complexity classifier
│   └── memory_chromaDB.py   # ChromaDB semantic cache
├── schemas/chat.py      # Pydantic request/response models
└── utils/logger.py      # Centralized logging config
index.html               # WebSocket test UI (project root)
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check (includes Celery/Redis status) |
| `POST` | `/normalize` | Normalize a query |
| `POST` | `/chat` | Full chat pipeline (normalize → cache check → LLM → respond) |
| `POST` | `/generalize` | Test endpoint: strip tone from an answer |
| `GET` | `/cache/entries` | List all cached entries with metadata |
| `DELETE` | `/cache/entries/{id}` | Delete a single cache entry |
| `GET` | `/conversations` | List all conversations (newest first) |
| `GET` | `/conversations/{id}/messages` | Get conversation message history |
| `DELETE` | `/conversations/{id}` | Delete a conversation |
| `WS` | `/ws/chat` | Real-time WebSocket chat |

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DEJAQ_REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL for Celery broker and result backend |
| `DEJAQ_USE_CELERY` | `true` | Set to `false` to disable Celery (tasks run in-process) |

---

## Models

| Role | Model | Quantization | Purpose |
|------|-------|--------------|---------|
| Normalizer | Qwen 2.5-0.5B-Instruct | Q4_K_M | Extract core topic from query |
| Context Enricher | Qwen 2.5-0.5B-Instruct | Q4_K_M | Rewrite follow-ups into standalone queries |
| Context Adjuster | Qwen 2.5-1.5B-Instruct | Q4_K_M | Match tone of cached responses to user style |
| Generalizer | Phi-3.5-Mini-Instruct | Q4_K_M | Strip tone from responses for cache storage |
| Local LLM | Llama 3.2-1B-Instruct | Q8_0 | Generate responses for "easy" queries |
| Classifier | NVIDIA DeBERTa-v3-base | Full | Route queries by complexity (easy/hard) |