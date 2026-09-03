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

## 1. Install and run

The install-and-run steps (Ollama tags to pull, `uv sync`, `npm install` for the two
frontends, `alembic upgrade head`, and `start.sh` / the manual redis+uvicorn+celery stack with
the `DEJAQ_USE_CELERY=false` fallback) live in the root
[Quick Start](../README.md#quick-start) so they only change in one place. Do that, then come
back here to bootstrap the app.

The five pipeline generation roles default to `granite4.1:3b` (normalizer, generalizer,
validator), `qwen2.5:1.5b` (context enricher, adjuster) and `gemma4:e4b` (local answering).
None is fixed - each is per-workspace configurable on the dashboard **Pipeline** page - so
the tags you need are whatever your workspaces use.

---

## 2. Open the app and bootstrap

| Surface | URL |
|---------|-----|
| Dashboard | http://localhost:3000/dashboard |
| Chat UI | http://localhost:4000 |
| API health check | http://127.0.0.1:8000/health |

1. Open the dashboard → **Workspaces** → create a workspace → **API Keys** → generate an API key (copy it).
   (Equivalent CLI: `cd server && uv run dejaq-admin workspace create --name Demo && uv run dejaq-admin key generate --workspace demo`.)
2. Dashboard → **Settings** → pick an external provider and one of its models, and save that
   provider's API key (storing a key needs `DEJAQ_CREDENTIAL_ENCRYPTION_KEY` in `server/.env`,
   see `server/.env.example`). There is no default model: until you choose one, a hard
   question is answered with `422` rather than routed to a provider you never picked.
3. Open the chat UI → paste the API key on the connect screen → **Connect** (leave the key
   field blank instead to use `DEJAQ_API_KEY` from `chat/.env.local`; a department is picked
   for you either way, change it later in **Settings**).
4. Start chatting — easy questions route to the local model, hard ones to your configured
   external provider, and repeated questions are answered from the semantic cache.

