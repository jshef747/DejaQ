# DejaQ Dashboard

Next.js dashboard for the DejaQ management API. It uses Supabase email/password auth, stores the session through `@supabase/ssr`, and sends the Supabase access token to FastAPI `/admin/v1/*` routes.

## Setup

```bash
cd frontend
npm install
cp .env.local.example .env.local
```

Fill in:

```bash
NEXT_PUBLIC_SUPABASE_URL=https://<project-id>.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=<anon-key>
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

## Run

```bash
npm run dev
```

Open `http://localhost:3000`.

Demo credentials after `cd server && uv run dejaq-admin seed demo`:

- `demo@dejaq.local`
- `demo1234`

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
