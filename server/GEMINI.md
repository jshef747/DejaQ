# DejaQ - AI Middleware & Organizational Memory

DejaQ is an intelligent middleware layer designed to optimize LLM interactions through semantic caching, query classification, and hybrid routing. It intelligently routes queries between local lightweight models (Llama/Qwen) and high-performance external APIs (GPT-4/Gemini) to minimize latency and cost.

## Project Overview

- **Core Technologies:** Python 3.13+, FastAPI, Celery, Redis, ChromaDB, llama-cpp-python (GGUF).
- **Architecture:** 
    - **FastAPI:** Main web server handling HTTP and WebSocket connections.
    - **Celery + Redis:** Background task queue for non-blocking operations like response generalization and cache storage.
    - **ChromaDB:** Vector database for semantic caching and retrieval.
    - **ModelManager:** Singleton service that lazily loads GGUF models (Qwen, Llama, Phi) once for efficient resource usage.
- **Pipeline:**
    - **Cache Miss:** Query → Context Enricher → Normalizer → Cache Filter → LLM (Local/External) → Respond → Background: Generalize → Store in ChromaDB.
    - **Cache Hit:** Query → Context Enricher → Normalizer → ChromaDB (Hit) → Context Adjuster (Tone Matching) → Respond.

## Building and Running

### Setup
Ensure you have `uv` installed.
```bash
# Mac (Apple Silicon) - Metal GPU acceleration
CMAKE_ARGS="-DLLAMA_METAL=on" uv sync

# Windows (NVIDIA) - CUDA acceleration
$env:CMAKE_ARGS = "-DLLAMA_CUBLAS=on"; uv sync

# CPU Only
uv sync
```

### Running the Server
The system requires Redis, the FastAPI server, and a Celery worker.
```bash
# 1. Start Redis (if not a service)
redis-server

# 2. Start FastAPI
uv run uvicorn app.main:app --reload

# 3. Start Celery Worker
uv run celery -A app.celery_app:celery_app worker --queues=background --pool=solo --loglevel=info
```

### Fallback Mode (No Redis)
```bash
DEJAQ_USE_CELERY=false uv run uvicorn app.main:app --reload
```

## Testing
Tests are managed via `pytest`.
```bash
# Run all tests
uv run pytest

# Run tests with specific model markers
uv run pytest -m no_model
uv run pytest -m qwen
```

## Development Conventions

- **Logging:** Never use `print()`. Use `logging.getLogger("dejaq.<module>")` via `app.utils.logger`.
- **Package Management:** Use `uv` only.
- **Asynchrony:** Use `async/await` for all I/O-bound operations.
- **Data Modeling:** Use Pydantic `BaseModel` for all request/response schemas.
- **Service Pattern:** Business logic resides in `app/services/`.
- **Model Loading:** Always use the `ModelManager` singleton to access LLMs.
- **Testing:** Add new tests in `tests/`. Use fixtures from `tests/conftest.py`.

## Key Files & Directories

- `app/main.py`: Application entry point and router inclusion.
- `app/config.py`: Centralized configuration and feature flags.
- `app/routers/`: API endpoints (Chat, Feedback, CRUD).
- `app/services/`: Core logic (Caching, Routing, Inference).
- `app/tasks/`: Celery background tasks.
- `app/schemas/`: Pydantic data models.
- `specs/`: Detailed design specifications for project features.
- `docs/`: Supplemental documentation on caching and architecture.

## Active Technologies
- Python 3.13+ + FastAPI, Celery, Redis, ChromaDB, llama-cpp-python, `openai` (or `httpx`) (002-external-llm-routing)
- ChromaDB (semantic cache), Redis (task queue/metadata) (002-external-llm-routing)

## Recent Changes
- 002-external-llm-routing: Added Python 3.13+ + FastAPI, Celery, Redis, ChromaDB, llama-cpp-python, `openai` (or `httpx`)
