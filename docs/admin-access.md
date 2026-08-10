# Accessing the DejaQ Admin Dashboard

DejaQ runs the admin dashboard and API on **127.0.0.1 only** (loopback) to protect workspace credentials from being accessible over the LAN. The data plane (`/v1/chat/completions`, `/v1/responses`, `/v1/feedback`) is intentionally LAN-accessible because it's protected by workspace API keys.

## Same machine (your laptop or the DejaQ server box)

No SSH needed. Open the dashboard directly:

```
http://localhost:3000/dashboard
```

If it's your first run with an empty database, the dashboard will redirect you to the onboarding wizard where you can create your first Workspace, Department, and API key.

## DejaQ on a separate server, you at your own computer

Run this command **on your computer** (replace `user` and `server-ip`):

```bash
ssh -L 3000:localhost:3000 -L 8000:localhost:8000 user@server-ip
```

Then open `http://localhost:3000/dashboard` in your browser as normal. The SSH tunnel forwards the server's admin ports to your machine over an encrypted connection.

To disconnect, close the SSH window (or press `Ctrl+C`).

> **Chat clients and apps** don't need the tunnel — they connect directly to the LAN data plane at `http://server-ip:8000/v1/...` using a workspace API key.

## Control-plane vs data-plane split

| Surface | Bound to | Protected by |
|---|---|---|
| Dashboard (`localhost:3000`) | 127.0.0.1 | Localhost + (optional) Supabase JWT |
| Admin API (`/admin/v1/*`) | 127.0.0.1 | Loopback middleware (403 from LAN) |
| Data plane (`/v1/*`) | 0.0.0.0 (LAN) | Workspace API key (`Authorization: Bearer ...`) |
| ChromaDB (`:8001`) | 127.0.0.1 | Localhost only |

## Environment overrides

| Variable | Default | Notes |
|---|---|---|
| `DEJAQ_ADMIN_LOOPBACK_ONLY` | `true` | Set `false` to disable the loopback guard (e.g. behind a trusted reverse proxy) |
| `DEJAQ_BIND_HOST` | `0.0.0.0` (via start.sh) | Override to `127.0.0.1` for fully local installs |
