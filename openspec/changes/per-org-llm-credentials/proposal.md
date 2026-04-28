## Why

The external LLM path currently uses a single platform-wide API key from `.env`, which means DejaQ pays for every customer's inference call — that is not the business model. Each organization needs to bring its own API key so costs are billed directly to their provider account.

## What Changes

- Introduce a new `org_provider_credentials` table storing encrypted provider API keys (one row per org × provider).
- Add a `DEJAQ_CREDENTIAL_ENCRYPTION_KEY` env variable (Fernet-compatible, 32-byte base64). The variable is validated lazily on first use of `CredentialService` — not at module import — so dev/test/CI flows that do not touch credentials continue to work without it.
- Expose new management API endpoints under `/admin/v1/orgs/{org_slug}/credentials` for listing, upserting, and removing per-provider keys. All endpoints enforce org-scoping via the existing `ManagementAuthContext.has_org_access(org_id)` primitive.
- Update the LLM router to resolve the active org's credential for the chosen provider at request time; **no fallback to the platform-wide env key**.
- Provider derivation: the chat router infers provider from the configured external model name (`gemini-*` → `google`, `gpt-*` / `o1-*` / `o3-*` / `chatgpt-*` → `openai`, `claude-*` → `anthropic`). This change ships with **three live providers — Google Gemini, OpenAI, and Anthropic** — wired through a common `LLMProviderClient` interface so per-org keys flow to the right SDK.
- Update `dejaq-admin seed demo` to accept the demo provider key via stdin (`--provider-key-stdin`) or env var (`DEJAQ_SEED_PROVIDER_KEY`) instead of argv, so the key never lands in shell history or process listings.
- **BREAKING**: Requests routed to an external provider for orgs with no matching credential now return **HTTP 402 Payment Required** with a pointer to the credentials settings page instead of using the env key. (Not 503 — the failure is a permanent per-tenant config error, not a transient server fault, so retry-on-503 semantics would cause false alerts and retry storms.)

## Capabilities

### New Capabilities

- `org-provider-credentials`: Per-org, per-provider encrypted API key storage — create, list (masked), replace, delete; decrypted only in the LLM router hot path. Org-scoped via existing auth primitive.

### Modified Capabilities

- `org-llm-config`: LLM router now requires a credential lookup from `org-provider-credentials` instead of reading the env key; credential-missing path is a hard failure (HTTP 402).
- `demo-management-seed`: `dejaq-admin seed demo` gains `--provider-key-stdin` and `DEJAQ_SEED_PROVIDER_KEY` env var support to seed a credential for the demo org without exposing the key on argv.

## Impact

- **New DB table**: `org_provider_credentials` — Alembic migration required.
- **New dependency**: `cryptography` (Fernet) for at-rest encryption.
- **New env var**: `DEJAQ_CREDENTIAL_ENCRYPTION_KEY` — required only when credential subsystem is exercised; first call into `CredentialService` raises `ValueError` if absent or malformed. Added to all three deployment mode blocks in CLAUDE.md.
- **`app/services/llm_router.py`** (and chat router): credential lookup replaces env-key read; raises HTTP 402 when credential absent.
- **`app/services/external_llm.py`**: refactored from Gemini-only singleton into a thin dispatcher that picks the right provider client. The `api_key` parameter is never logged, and any provider error bodies are redacted before logging.
- **New provider client modules**: `app/services/llm_providers/google.py` (wraps `google-genai`), `app/services/llm_providers/openai.py` (wraps `openai>=1.0`), `app/services/llm_providers/anthropic.py` (wraps `anthropic` SDK). Each exposes the same `async generate_response(request, api_key) -> ExternalLLMResponse` contract.
- **New dependencies**: `openai`, `anthropic` SDK packages.
- **New router**: `app/routers/admin/credentials.py` + `app/services/credential_service.py` + `app/db/credential_repo.py`. Repo upsert mirrors `llm_config_repo.upsert_for_org` (SELECT → insert-or-update → flush) for portability across SQLite and the planned PostgreSQL migration.
- **`cli/admin.py`**: `seed demo` subcommand gains `--provider-key-stdin` flag and reads `DEJAQ_SEED_PROVIDER_KEY` env var.
- Supported providers (initial set, validated at write time): `google`, `openai`, `anthropic`, `mistral`, `cohere`, `together`, `groq`, `fireworks`. **Live (wired to a real client) in this change: `google`, `openai`, `anthropic`.** The remaining 5 are storage-only — keys can be saved and listed but the chat router will reject them with HTTP 422 ("provider not yet supported") until a client is wired.
