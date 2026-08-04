# DejaQ Chat

Standalone Next.js chat app for the DejaQ gateway. Server route handlers proxy requests to the DejaQ backend, authenticated by a workspace API key: a key pasted into the Settings modal (stored in the browser's `localStorage`, sent to the app's own `/api/*` routes as a header) wins, falling back to `DEJAQ_API_KEY` in `chat/.env.local` when Settings has none.

## Setup

```bash
cd chat
npm install
cp .env.local.example .env.local
```

Fill in:

```bash
DEJAQ_API_KEY=dq_...
DEJAQ_API_BASE_URL=http://127.0.0.1:8000
NEXT_PUBLIC_DASHBOARD_URL=http://localhost:3000/dashboard
```

`DEJAQ_API_KEY` is optional if you'd rather paste the key into the chat app's Settings
modal after it starts (a Settings key always wins over this env var).

## Run

```bash
npm run dev
```

Open `http://localhost:4000`.

## Verify

```bash
npx tsc --noEmit --pretty false
npm run build
```
