# DejaQ Admin CLI

Run all commands from `server/` with `uv run`.

## Setup

```bash
cd server
uv sync
uv run alembic upgrade head
```

## Organizations

```bash
uv run dejaq-admin org create --name "Acme Corp"
uv run dejaq-admin org list
uv run dejaq-admin org delete --slug acme-corp
```

Org slugs are derived from names with the shared slug helper used by the management API.

## Departments

```bash
uv run dejaq-admin dept create --org acme-corp --name "Customer Support"
uv run dejaq-admin dept list
uv run dejaq-admin dept list --org acme-corp
uv run dejaq-admin dept delete --org acme-corp --slug customer-support
```

Departments isolate cache namespaces with `{org_slug}__{dept_slug}`.

## Gateway API Keys

```bash
uv run dejaq-admin key generate --org acme-corp
uv run dejaq-admin key generate --org acme-corp --force
uv run dejaq-admin key list --org acme-corp
uv run dejaq-admin key revoke --id 3
```

Keys authenticate `/v1/chat/completions` and `/v1/feedback`. Revoked keys may remain accepted until `DEJAQ_KEY_CACHE_TTL` expires.

## Stats

```bash
uv run dejaq-admin stats
```

Stats read `DEJAQ_STATS_DB` and mirror the dashboard/admin API aggregate shapes.

## Provider credentials and feedback

Provider credentials (encrypted per org with `DEJAQ_CREDENTIAL_ENCRYPTION_KEY`) and feedback
are managed through the dashboard or the management API (`/admin/v1/orgs/{slug}/credentials`,
`/admin/v1/feedback`) — not the CLI. Supported live providers: `google`, `openai`, `anthropic`.
There is no platform `GEMINI_API_KEY` fallback.
