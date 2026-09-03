# DejaQ Chat

Standalone Next.js chat app for the DejaQ gateway. Server route handlers proxy requests to the DejaQ backend, authenticated by a workspace API key: a key entered in the app (on the first-run connect screen, later editable in Settings; stored in the browser's `localStorage`, sent to the app's own `/api/*` routes as a header) wins, falling back to `DEJAQ_API_KEY` in `chat/.env.local` when the browser has none. The env-key fallback only applies when the request targets the configured default server (`DEJAQ_API_BASE_URL`, compared by scheme/host/port): a request whose server override points anywhere else gets no key from the env var, so the operator's key is never forwarded to a client-chosen server (see `app/api/_lib/dejaq.ts`).

## Setup

```bash
cd chat
npm install
cp .env.local.example .env.local
```

Fill in:

```bash
DEJAQ_API_KEY=<your workspace API key>
DEJAQ_API_BASE_URL=http://127.0.0.1:8000
NEXT_PUBLIC_DASHBOARD_URL=http://localhost:3000/dashboard
```

`DEJAQ_API_KEY` is optional if you'd rather enter the key in the app instead (a key entered
there always wins over this env var). If you do fill it in, leave the connect screen's key
field blank and press Connect - the request then carries no key of its own and this env var
answers for it. If you point the app at a different server, enter that server's key in the
app - the env var is never sent to any server other than `DEJAQ_API_BASE_URL`.

## Run

```bash
npm run dev
```

Open `http://localhost:4000`. First launch shows a connect screen: paste a workspace API
key (mint one with `dejaq-admin key generate`) - or leave the key field blank to use the
`DEJAQ_API_KEY` this server already has configured - optionally point it at another server,
and Connect. A department is picked for you; change it, the key, or the server later in
Settings.

The app follows your OS light/dark setting and has no in-app toggle; set
`data-theme="light"` or `data-theme="dark"` on `<html>` to force one (`app/tokens.css`).

## Verify

```bash
npx tsc --noEmit --pretty false
npm run build
npm test
```
