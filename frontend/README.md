# DejaQ Dashboard

Next.js dashboard for the DejaQ management API (`/admin/v1/*`).

**Auth:** by default (no Supabase env) it runs in dev-bypass mode — no login, the backend
grants a dev-admin context. Set the Supabase vars below to require real email/password login
(`@supabase/ssr`), which then attaches the session JWT to every `/admin/v1/*` request.

The customer chat UI lives in the standalone `../chat` app.

## Setup

```bash
cd frontend
npm install
cp .env.local.example .env.local
```

`.env.local` (Supabase vars optional — leave blank for dev bypass):

```bash
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
# NEXT_PUBLIC_SUPABASE_URL=https://<project-id>.supabase.co
# NEXT_PUBLIC_SUPABASE_ANON_KEY=<anon-key>
```

## Run

```bash
npm run dev
```

Open `http://localhost:3000`. In dev-bypass mode you go straight to the dashboard — create an
organization and generate an API key to start using the gateway.

## What It Manages

- Organizations and departments
- Org API keys for `/v1/chat/completions` and `/v1/feedback`
- Org provider credentials for Google, OpenAI, and Anthropic
- Per-org LLM config and provider test calls
- Request stats and cache feedback review

The dashboard does not call the gateway with Supabase auth. Gateway requests still use DejaQ org API keys.

## Verify

```bash
npx tsc --noEmit --pretty false
npm run build
```
