# Getting Started

## Prerequisites

- Python 3.13+
- Node.js 18+
- [uv](https://github.com/astral-sh/uv) package manager
- [Ollama](https://ollama.com) — generation runs through it (local or remote)
- Redis (optional — for the background task queue; skip with `DEJAQ_USE_CELERY=false`)

> No auth setup is required. The dashboard runs in dev-bypass mode (no login) and the
> backend grants a dev-admin context — the management API is protected by loopback
> binding, not a credential.

---

## 1. Install dependencies

```bash
cd server
uv sync
cd ../dashboard && npm install
cd ../chat && npm install
```

---

## 2. Migrate the database

```bash
cd server
uv run alembic upgrade head
```

No `.env` is needed for local dev. (Optional overrides: copy `server/.env.example` to
`server/.env`.)

---

## 3. Start Ollama and pull models

```bash
ollama serve
ollama pull qwen2.5:0.5b qwen2.5:1.5b gemma4:e2b gemma4:e4b
```

## 4. Start the stack

```bash
./start.sh --stack=all --mode=local
# remote Ollama: ./start.sh --stack=all --mode=remote --ollama-url=http://<host>:11434
```

Cross-platform (macOS/Linux, and Windows git-bash — Redis runs in WSL; override the distro
with `DEJAQ_WSL_DISTRO`). Or launch by hand:

```bash
redis-server                                                            # terminal 1 (optional)
cd server && uv run uvicorn app.main:app --reload                        # terminal 2
cd server && uv run celery -A app.celery_app:celery_app worker \
  --queues=background --pool=solo --loglevel=info                        # terminal 3 (optional)
cd dashboard && npm run dev                                               # terminal 4
cd chat && npm run dev                                                   # terminal 5
```

> **No Redis?** Drop the Redis + Celery terminals and set `DEJAQ_USE_CELERY=false`.

---

## 5. Open the app and bootstrap

| Surface | URL |
|---------|-----|
| Dashboard | http://localhost:3000/dashboard |
| Chat UI | http://localhost:4000 |
| API health check | http://127.0.0.1:8000/health |

1. Open the dashboard → **Workspaces** → create a workspace → **API Keys** → generate an API key (copy it).
   (Equivalent CLI: `cd server && uv run dejaq-admin workspace create --name Demo && uv run dejaq-admin key generate --workspace demo`.)
2. Open the chat UI → **Settings** → paste the API key (and an optional department slug).
3. Start chatting — easy questions route to the local model, hard ones to your configured
   external provider, and repeated questions are answered from the semantic cache.

