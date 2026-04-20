# DejaQ

DejaQ is an AI middleware layer that sits between users and language models, with the goal of making enterprise-style chat systems faster, cheaper, and smarter over time.

Instead of sending every prompt directly to an expensive model, DejaQ enriches the request with context, normalizes the query, checks a semantic cache, routes simple work to local models, and only escalates harder requests to external providers when needed.

## Why DejaQ

- Reduce API cost by answering repeated or simple questions locally
- Improve latency with semantic cache hits and lightweight routing
- Build shared organizational memory across teams and departments
- Stay compatible with existing clients through an OpenAI-style API
- Experiment safely with normalization and enrichment strategies before promoting them into production

## How It Works

```text
Incoming request
  -> Context enrichment
  -> Query normalization
  -> Semantic cache lookup
     -> hit: adjust response tone and return
     -> miss: classify difficulty
        -> easy: local model
        -> hard: external LLM
  -> Background feedback + cache storage
```

Core building blocks in the current codebase include:

- `FastAPI` for the API layer
- `ChromaDB` for semantic memory
- `Celery` + `Redis` for background processing
- Local GGUF models via `llama-cpp-python`
- OpenAI-compatible chat completions endpoints
- Evaluation harnesses for normalizer and context enricher iteration

## Repository Structure

```text
server/              Main FastAPI application and middleware pipeline
normalization-test/  Standalone harness for query-normalizer experiments
enricher-test/       Standalone harness for context-enricher experiments
docs/                Product and API notes
openspec/            Specs, proposals, and archived change records
```

## Quick Start

### 1. Prerequisites

- Python `3.13+`
- [`uv`](https://docs.astral.sh/uv/)
- `Redis` for background jobs

### 2. Install server dependencies

```bash
cd server
uv sync
```

For GPU-backed local inference, the project already documents platform-specific install flags in [server/README.md](/Users/jonathansheffer/Desktop/Coding/DejaQ/server/README.md).

### 3. Run the app

Start these processes from `server/`:

```bash
# Terminal 1
redis-server

# Terminal 2
uv run uvicorn app.main:app --reload

# Terminal 3
uv run celery -A app.celery_app:celery_app worker --queues=background --pool=solo --loglevel=info
```

Then open:

- API health: `http://127.0.0.1:8000/health`
- OpenAI-compatible base URL: `http://127.0.0.1:8000/v1`
- Demo UI: `server/openai-compat-demo.html`

If you want a lighter local setup, the server can also run without Celery:

```bash
DEJAQ_USE_CELERY=false uv run uvicorn app.main:app --reload
```

## OpenAI-Compatible API

DejaQ exposes a `POST /v1/chat/completions` endpoint so existing OpenAI SDK clients can point at DejaQ with minimal change.

Python example:

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8000/v1",
    api_key="any-string",
)

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Why is the sky blue?"}],
)

print(response.choices[0].message.content)
```

More details live in [docs/openai-compat-api.md](/Users/jonathansheffer/Desktop/Coding/DejaQ/docs/openai-compat-api.md).

## Experimentation Harnesses

DejaQ includes two separate offline evaluation projects for improving pipeline quality without destabilizing the main server.

### `normalization-test/`

Used to compare query-normalizer configurations against fixed groups of semantically equivalent prompts.

```bash
cd normalization-test
uv sync
uv run python -m harness.runner
```

Results are written to timestamped `reports/` folders. See [normalization-test/README.md](/Users/jonathansheffer/Desktop/Coding/DejaQ/normalization-test/README.md).

### `enricher-test/`

Used to benchmark context-enricher variants across conversation datasets.

```bash
cd enricher-test
uv sync
uv run python -m harness.runner
```

## Documentation

- [server/README.md](/Users/jonathansheffer/Desktop/Coding/DejaQ/server/README.md) - server setup, architecture, models, endpoints
- [docs/openai-compat-api.md](/Users/jonathansheffer/Desktop/Coding/DejaQ/docs/openai-compat-api.md) - OpenAI-compatible API behavior
- [docs/services/normalizer.md](/Users/jonathansheffer/Desktop/Coding/DejaQ/docs/services/normalizer.md) - normalizer notes
- [docs/services/context-enricher.md](/Users/jonathansheffer/Desktop/Coding/DejaQ/docs/services/context-enricher.md) - context enricher notes
- [server/docs/project_overview.md](/Users/jonathansheffer/Desktop/Coding/DejaQ/server/docs/project_overview.md) - product direction and architecture rationale

## Current Focus

The repo already includes:

- A FastAPI middleware server with health checks, chat routing, feedback endpoints, and OpenAI-compatible chat completions
- Department and organization data models with Alembic migrations
- Background caching flow with Celery
- Local experimentation loops for improving normalization and enrichment quality

The broader product vision is to turn repeated organizational questions into reusable memory, while preserving a familiar LLM interface for users and client apps.
