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

## Provider Credentials

Provider credentials are encrypted per org with `DEJAQ_CREDENTIAL_ENCRYPTION_KEY`.

```bash
uv run dejaq-admin credential list --org acme-corp
echo "$OPENAI_API_KEY" | uv run dejaq-admin credential set --org acme-corp --provider openai --stdin
uv run dejaq-admin credential delete --org acme-corp --provider openai
```

Supported live providers are `google`, `openai`, and `anthropic`. Runtime hard-query routing uses these stored org credentials; there is no platform `GEMINI_API_KEY` fallback.

## Demo Seed

```bash
uv run dejaq-admin seed demo
echo "$OPENAI_API_KEY" | uv run dejaq-admin seed demo --provider-key-stdin openai
DEJAQ_SEED_PROVIDER_KEY=openai:<key> uv run dejaq-admin seed demo
```

The demo seed creates the demo org, departments, API key, sample stats, and Supabase demo user when `SUPABASE_SERVICE_ROLE_KEY` is configured.

Demo login:

- `demo@dejaq.local`
- `demo1234`

## Stats And Feedback

```bash
uv run dejaq-admin stats
uv run dejaq-admin feedback list --org acme-corp
```

Stats read `DEJAQ_STATS_DB` and mirror the dashboard/admin API aggregate shapes.

## TUI

```bash
uv run dejaq-admin-tui
```

The Textual TUI provides keyboard-driven org, department, API-key, credential, stats, and feedback workflows.
