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

Keys authenticate `/v1/chat/completions` and `/v1/feedback`. Revoking a key invalidates the key-lookup cache immediately (and the DB-mtime staleness check also fires), so a revoked key is rejected on the very next request, not after `DEJAQ_KEY_CACHE_TTL` expires.

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
Any LiteLLM provider that authenticates with a single API-key string is usable - not a
hand-kept list. `app/services/llm_providers/provider_keys.py::is_usable_provider` accepts a
DejaQ provider key when it maps into `litellm.provider_list` and is not one of the
structured/non-single-key providers (Bedrock, Azure, Vertex, Ollama - see
`model_catalog.STRUCTURED_CREDENTIAL_PROVIDERS`). Every usable provider is served through the
one shared `LiteLLMTransportClient` (`app/services/llm_providers/litellm_transport.py`) - there
is no per-provider `base_url` client and no `provider_registry.py` (both removed in #77).
Credentials are stored under DejaQ's provider key (`google`, `together`, `fireworks`), so a key
saved under a LiteLLM alias (`gemini`, `together_ai`, `fireworks_ai`) is normalised on upsert.
There is no platform `GEMINI_API_KEY` fallback.
