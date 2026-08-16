# DejaQ Dashboard

Next.js dashboard for the DejaQ management API (`/admin/v1/*`).

**Auth:** dev-bypass mode only — no login, the backend grants a dev-admin context to every
request. The management API is protected by loopback binding, not a credential.

The customer chat UI lives in the standalone `../chat` app.

## Setup

```bash
cd dashboard
npm install
cp .env.local.example .env.local
```

`.env.local`:

```bash
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

## Run

```bash
npm run dev
```

Open `http://localhost:3000`. You go straight to the dashboard — create a
workspace and generate an API key to start using the gateway.

## What It Manages

- Workspaces and departments
- Workspace API keys for `/v1/chat/completions` and `/v1/feedback`
- Workspace provider credentials for Google, OpenAI, and Anthropic
- Per-workspace LLM config and provider test calls
- Per-workspace pipeline stage models, system prompts, and token budgets (Pipeline page)
- Per-workspace knowledge base (Rug/RAG documents)
- Request stats and cache feedback review

Gateway requests (`/v1/*`) always use DejaQ workspace API keys, never the dashboard's own auth.

## Verify

```bash
npx tsc --noEmit --pretty false
npm run build
```
