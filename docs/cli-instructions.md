# DejaQ Admin CLI

Run all commands from `server/` with `uv run`.

## Setup

```bash
cd server
uv sync
uv run alembic upgrade head
```

## Workspaces

```bash
uv run dejaq-admin workspace create --name "Acme Corp"
uv run dejaq-admin workspace list
uv run dejaq-admin workspace delete --slug acme-corp
```

Workspace slugs are derived from names with the shared slug helper used by the management API.

> The old `dejaq-admin org …` group still runs as a hidden deprecated alias of `workspace`
> and prints a warning. Its `--org` option is gone everywhere else — every other command
> takes `--workspace`.

## Departments

```bash
uv run dejaq-admin dept create --workspace acme-corp --name "Customer Support"
uv run dejaq-admin dept list
uv run dejaq-admin dept list --workspace acme-corp
uv run dejaq-admin dept delete --workspace acme-corp --slug customer-support
```

Departments isolate cache namespaces with `{workspace_slug}__{dept_slug}`.

## Gateway API Keys

```bash
uv run dejaq-admin key generate --workspace acme-corp
uv run dejaq-admin key generate --workspace acme-corp --force
uv run dejaq-admin key list --workspace acme-corp
uv run dejaq-admin key revoke --id 3
```

Keys authenticate `/v1/chat/completions` and `/v1/feedback`. Revoked keys may remain accepted until `DEJAQ_KEY_CACHE_TTL` expires.

## Knowledge Base (RAG)

Curate a workspace's knowledge base — documents that ground answers on a cache miss.
Full design: [rag-layer.md](rag-layer.md).

```bash
uv run dejaq-admin rag list --workspace acme-corp
uv run dejaq-admin rag add-text --workspace acme-corp --title "Refund policy" --content "Refunds within 30 days."
uv run dejaq-admin rag add-file --workspace acme-corp --path ./handbook.pdf   # PDF/DOCX/text/code, or an image to OCR
uv run dejaq-admin rag add-url  --workspace acme-corp --url https://acme.example/docs
uv run dejaq-admin rag delete   --workspace acme-corp --id 3
```

## Stats

```bash
uv run dejaq-admin stats
```

Stats read `DEJAQ_STATS_DB` and mirror the dashboard/admin API aggregate shapes.

## Provider credentials and feedback

Provider credentials (encrypted per workspace with `DEJAQ_CREDENTIAL_ENCRYPTION_KEY`) and
feedback are managed through the dashboard or the management API
(`/admin/v1/workspaces/{slug}/credentials`, `/admin/v1/feedback`) — not the CLI.
Supported live providers: `google`, `openai`, `anthropic`, `xai`, `deepseek`, `groq` -
the last three reuse the OpenAI-compatible client through a per-provider `base_url`
rather than shipping a client module of their own. Provider names are validated in
Python against `app/services/provider_registry.py`; there is no database constraint.
There is no platform `GEMINI_API_KEY` fallback.
