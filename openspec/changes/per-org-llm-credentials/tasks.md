## 1. Dependencies and Configuration

- [x] 1.1 Add `cryptography`, `openai`, and `anthropic` to `server/pyproject.toml` dependencies (`cryptography.fernet.Fernet` for encryption; `openai>=1.0` for the OpenAI provider client; `anthropic` for the Anthropic provider client). `google-genai` is already a dep.
- [x] 1.2 Add `DEJAQ_CREDENTIAL_ENCRYPTION_KEY` to `server/app/config.py` — read from env into a settings field. **Do not validate at module load.** Validation happens lazily in `CredentialService.__init__` (task 4.1) so dev/test/CI flows that don't touch credentials continue to work without the key set.
- [x] 1.3 Update `CLAUDE.md` env variable table with `DEJAQ_CREDENTIAL_ENCRYPTION_KEY` (description, how to generate with `Fernet.generate_key()`, and a note that losing it makes all stored credentials unrecoverable — back it up)

## 2. Database — ORM Model and Migration

- [x] 2.1 Create `server/app/db/models/org_provider_credentials.py` — `OrgProviderCredentials` ORM model with `id`, `org_id` (FK CASCADE), `provider` (VARCHAR), `encrypted_key` (TEXT), `created_at`, `updated_at`; unique constraint on `(org_id, provider)` named `uq_org_provider_credentials_org_provider`
- [x] 2.2 Register the new model in `server/app/db/models/__init__.py` and import it in `server/app/db/base.py` so Alembic detects it
- [x] 2.3 Add `provider_credentials` relationship to the `Organization` ORM model in `server/app/db/models/org.py` (use `provider_credentials` rather than the more generic `credentials` to avoid future naming collisions if other credential types are added)
- [x] 2.4 Generate Alembic migration `server/alembic/versions/<rev>_add_org_provider_credentials.py` (down_revision = `a1b2c3d4e5f6` — verified current head) creating the `org_provider_credentials` table with: unique constraint named `uq_org_provider_credentials_org_provider`, FK CASCADE on `organizations.id`, and a `CHECK (provider IN ('google', 'openai', 'anthropic', 'mistral', 'cohere', 'together', 'groq', 'fireworks'))` constraint as defence-in-depth against direct DB writes that bypass Pydantic validation. Add a docstring comment in the migration: **"Downgrade destroys all stored encrypted credentials. Operators must re-enter every org's API keys after a re-upgrade."**

## 3. Repository Layer

- [x] 3.1 Create `server/app/db/credential_repo.py` mirroring the `llm_config_repo.upsert_for_org` pattern (SELECT → insert-or-update → flush — do NOT use `sqlite_insert(...).on_conflict_do_update` because it is not portable to the planned PostgreSQL migration). Functions: `upsert_credential(db, org_id, provider, encrypted_key)`, `get_credential(db, org_id, provider) -> OrgProviderCredentials | None`, `list_credentials(db, org_id) -> list[OrgProviderCredentials]`, `delete_credential(db, org_id, provider) -> bool`

## 4. Service Layer — Credential Service

- [x] 4.1 Create `server/app/services/credential_service.py` with `CredentialService` class:
  - `SUPPORTED_PROVIDERS` constant: `{"google", "openai", "anthropic", "mistral", "cohere", "together", "groq", "fireworks"}`
  - `__init__` — read `DEJAQ_CREDENTIAL_ENCRYPTION_KEY` from settings; raise `ValueError("DEJAQ_CREDENTIAL_ENCRYPTION_KEY missing or malformed")` if absent or not a valid Fernet key. **This is the lazy-validation point** — module import does not trigger this.
  - `encrypt(key: str) -> str` — Fernet-encrypt
  - `decrypt(ciphertext: str) -> str` — Fernet-decrypt
  - `mask(key: str) -> str` — returns `<first4>****<last4>` when `len(key) >= 12`; returns `"********"` (eight asterisks) when `len(key) < 12` to prevent leaking short test stubs
  - `upsert(db, org_id, provider, raw_key)` — validate provider is in `SUPPORTED_PROVIDERS`, strip whitespace, raise `ValueError` if empty, encrypt, call repo upsert
  - `get_decrypted_key(db, org_id, provider) -> str | None` — fetch + decrypt; return `None` if no row
  - `list_masked(db, org_id) -> list[dict]` — list credentials with masked keys
  - `delete(db, org_id, provider) -> bool`

## 5. Schemas

- [x] 5.1 Create `server/app/schemas/credentials.py` with Pydantic models:
  - `ProviderEnum` (str enum of all 8 supported providers)
  - `CredentialUpsertRequest(api_key: str)` — validator strips whitespace, raises if empty
  - `CredentialResponse(provider, key_preview, created_at, updated_at)`
  - `CredentialDeleteResponse(deleted: bool)`

## 6. Admin Router — Credentials Endpoints

- [x] 6.1 Create `server/app/routers/admin/credentials.py` with:
  - `GET /admin/v1/orgs/{org_slug}/credentials` → list masked credentials (HTTP 200 / 403 / 404)
  - `PUT /admin/v1/orgs/{org_slug}/credentials/{provider}` → upsert (HTTP 200 / 403 / 404 / 422)
  - `DELETE /admin/v1/orgs/{org_slug}/credentials/{provider}` → delete (HTTP 200 / 403 / 404)
  - **Each endpoint MUST resolve the org by slug then call `ctx.has_org_access(org_id)` and return HTTP 403 if access is denied.** Mirror the pattern in `server/app/routers/admin/llm_config.py:_check_org_access_by_slug`. Without this, a user with a valid Supabase JWT for org A could read/write org B's credentials by guessing the slug.
- [x] 6.2 Register the credentials router in `server/app/routers/admin/__init__.py`
- [x] 6.3 Update `CLAUDE.md` endpoints section to list the three new credential endpoints under `/admin/v1/*`

## 7. LLM Config — Add `credentials_configured` Field

- [x] 7.1 Update `server/app/services/llm_config_service.py` to join credential presence and include `credentials_configured: list[str]` in the returned config dict
- [x] 7.2 Update `GET /admin/v1/orgs/{org_slug}/llm-config` response schema in `server/app/routers/admin/llm_config.py` to include `credentials_configured`

## 8. ExternalLLMService — Multi-Provider Dispatcher (No Key Logging)

- [x] 8.1 Define the provider-client contract:
  - Create `server/app/services/llm_providers/__init__.py` exporting an `LLMProviderClient` Protocol with one method: `async generate_response(request: ExternalLLMRequest, api_key: str) -> ExternalLLMResponse`.
  - Define a constant `LIVE_PROVIDERS = {"google", "openai", "anthropic"}` — providers that have a wired client. The remaining 5 in `SUPPORTED_PROVIDERS` are storage-only.

- [x] 8.2 Create `server/app/services/llm_providers/google.py`:
  - Move the existing Gemini logic out of `external_llm.py` into a `GoogleProviderClient` class implementing the protocol.
  - Per-call `genai.Client(api_key=api_key)` (no singleton).
  - Keep the existing OpenAI→Gemini role mapping (`assistant` → `model`).
  - Map `genai_errors.ClientError(401)` → `ExternalLLMAuthError`; other `ClientError`/`APIError` → `ExternalLLMError`.

- [x] 8.3 Create `server/app/services/llm_providers/openai.py`:
  - `OpenAIProviderClient` using `openai.AsyncOpenAI(api_key=api_key)` per call.
  - Build messages as native OpenAI chat-completions format (history is already in `{"role": "...", "content": "..."}` shape from the chat router; just prepend a `system` message from `request.system_prompt`).
  - Use `client.chat.completions.create(model=..., messages=..., max_tokens=..., temperature=...)`.
  - Map `openai.AuthenticationError` → `ExternalLLMAuthError`, `openai.APITimeoutError` → `ExternalLLMTimeoutError`, others → `ExternalLLMError`.
  - Populate `ExternalLLMResponse` with `text=response.choices[0].message.content`, `prompt_tokens=response.usage.prompt_tokens`, `completion_tokens=response.usage.completion_tokens`.

- [x] 8.4 Create `server/app/services/llm_providers/anthropic.py`:
  - `AnthropicProviderClient` using `anthropic.AsyncAnthropic(api_key=api_key)` per call.
  - **Important**: Anthropic requires `system` as a top-level parameter, NOT a message role. Pass `request.system_prompt` as the `system=` arg; pass only `user`/`assistant` messages in `messages=`.
  - Use `client.messages.create(model=..., system=..., messages=..., max_tokens=..., temperature=...)`. Note: Anthropic requires `max_tokens` (no default).
  - Map `anthropic.AuthenticationError` → `ExternalLLMAuthError`, `anthropic.APITimeoutError` → `ExternalLLMTimeoutError`, others → `ExternalLLMError`.
  - Populate `ExternalLLMResponse` with `text=response.content[0].text`, `prompt_tokens=response.usage.input_tokens`, `completion_tokens=response.usage.output_tokens`.

- [x] 8.5 Refactor `server/app/services/external_llm.py` into a dispatcher:
  - Remove the singleton `_instance` guard and `_client` cache.
  - Remove the `GEMINI_API_KEY` import; remove all Gemini-specific code (it now lives in `llm_providers/google.py`).
  - Change signature to `async def generate_response(request, provider: str, api_key: str)`.
  - Maintain a `_PROVIDER_CLIENTS: dict[str, LLMProviderClient]` registry mapping `"google"` → `GoogleProviderClient()`, `"openai"` → `OpenAIProviderClient()`, `"anthropic"` → `AnthropicProviderClient()`.
  - If `provider not in _PROVIDER_CLIENTS`, raise `ExternalLLMError(f"Provider '{provider}' is not wired to a live client.")` — caught by the chat router as HTTP 422.
  - Delegate to the right client's `generate_response`.

- [x] 8.6 Logging guardrails (apply to all three provider clients AND the dispatcher):
  - **Never log the `api_key` parameter.**
  - In every error-handling block, redact the api_key value from the error message string before logging (substring replace with `<redacted>`).
  - Add a unit test in `tests/services/test_provider_clients_logging.py` that — for each provider, on both success and error paths — asserts the api_key never appears in `caplog.text`.

- [x] 8.7 Provider-client contract test:
  - Create `tests/services/test_provider_clients_contract.py` that mocks each SDK and asserts: (a) all three clients return an `ExternalLLMResponse` with the same shape; (b) auth errors uniformly map to `ExternalLLMAuthError`; (c) timeout errors uniformly map to `ExternalLLMTimeoutError`.

## 9. Provider-Derivation Helper

- [x] 9.1 Create `server/app/services/provider_inference.py` with `provider_for_model(model_name: str) -> str` that maps configured external model names to provider strings. Mapping (initial):
  - `gemini-*` → `"google"`
  - `gpt-*`, `o1-*`, `o3-*`, `chatgpt-*` → `"openai"`
  - `claude-*` → `"anthropic"`
  - anything else → raise `ValueError(f"Unknown provider for model '{model_name}'")` so configuration errors surface loudly.
  - Add a unit test covering each mapped pattern, the unmapped-fallback raise, and case-sensitivity (matching is case-insensitive on the prefix).

## 10. API Key Middleware — Expose `org_id` on `request.state`

- [x] 10.1 Update `server/app/middleware/api_key.py` to set `request.state.org_id` (integer PK) alongside the existing `request.state.org_slug`, so the chat router can pass it directly to `CredentialService` without a secondary lookup

## 11. Chat Router — Credential Gate for Hard Queries (HTTP 402 / 422)

- [x] 11.1 Update `server/app/routers/openai_compat.py`:
  - Read `org_id = getattr(raw_request.state, "org_id", None)` at the top of the handler.
  - Before dispatching to `ExternalLLMService` for hard queries, call `provider_for_model(EXTERNAL_MODEL_NAME)` (task 9.1):
    - If it raises `ValueError` (unmapped model), return `JSONResponse(status_code=422, content={"detail": f"Configured external model '{EXTERNAL_MODEL_NAME}' is not mapped to a supported provider."})`.
  - If the resolved provider is in `SUPPORTED_PROVIDERS` but NOT in `LIVE_PROVIDERS` (i.e., one of `mistral`, `cohere`, `together`, `groq`, `fireworks`), return `JSONResponse(status_code=422, content={"detail": f"Provider '{provider}' is not yet wired to a live client. Configure a model from a supported provider (google, openai, anthropic)."})`. Do NOT attempt the credential lookup.
  - Otherwise, call `CredentialService().get_decrypted_key(db, org_id, provider)`.
  - If key is `None`, return `JSONResponse(status_code=402, content={"detail": f"No {provider} API key configured for this organization. Add one via the credentials settings."})` immediately. **Use 402 (Payment Required), not 503** — this is a permanent per-tenant config error; 503 would trigger client retries, alerting false-fires, and load-balancer ejection.
  - Pass both the provider string and the decrypted key to `ExternalLLMService().generate_response(request, provider=provider, api_key=decrypted_key)`.
  - Use the existing sync `SessionLocal` for the credential lookup (consistent with how the chat router already accesses other repos).

## 12. CLI — `seed demo` Provider Key via Stdin / Env Var

- [x] 12.1 Update `server/cli/admin.py` `seed demo` command:
  - Add `--provider-key-stdin <provider>` option (e.g., `--provider-key-stdin google`) — reads the raw key from stdin, never argv. Avoids exposing the key in shell history, `ps auxe`, or CI logs.
  - Also accept `DEJAQ_SEED_PROVIDER_KEY` env var as an alternative source (format `<provider>:<key>`)
  - **Do not accept the key as a literal argv value** — this is a deliberate security regression vs. argv-passing
  - After all other seed steps, validate the provider is in `SUPPORTED_PROVIDERS`, call `CredentialService().upsert(db, demo_org_id, provider, raw_key)`
  - If `DEJAQ_CREDENTIAL_ENCRYPTION_KEY` is not set, print a Rich warning and skip the credential upsert (do not error — rest of the seed must still succeed)
  - Running twice replaces the credential (idempotent via upsert)
- [x] 12.2 Update `CLAUDE.md` Supabase Setup section to document both stdin and env-var seeding flows. Example: `echo $GEMINI_API_KEY | dejaq-admin seed demo --provider-key-stdin google`

## 13. Documentation

- [x] 13.1 Add `DEJAQ_CREDENTIAL_ENCRYPTION_KEY` to all three Deployment Modes env blocks in `CLAUDE.md` with a "back this up — losing it is unrecoverable" note
- [x] 13.2 Add a note in `CLAUDE.md` Current Status that `GEMINI_API_KEY` is no longer read at request time (kept in env for operator reference only; runtime credential comes from DB)
- [x] 13.3 Document the 402 Payment Required failure mode for hard queries in CLAUDE.md alongside the existing endpoint documentation

## 14. Tracked Follow-ups (Not in This Change)

- [ ] 14.1 `dejaq-admin rotate-encryption-key` CLI — re-encrypt all rows under a new master key. **Required before customer onboarding.**
- [ ] 14.2 Audit table covering admin mutations (orgs, departments, keys, credentials, llm-config) — single sweep when customer onboarding lands.
- [ ] 14.3 Per-key LRU(8) cache of `genai.Client` instances if profiling shows construction overhead.
