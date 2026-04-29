## Context

The external LLM path (`complexity == "hard"`) calls `ExternalLLMService.generate_response()`, which initialises a singleton `genai.Client` using `GEMINI_API_KEY` from the environment. The client is shared across all requests and all orgs, meaning the platform pays for every hard query. The org context (slug, ID) is already threaded through `request.state` into the chat router, but it is not currently passed to `ExternalLLMService`.

The management API already has a pattern for per-org config (`org_llm_config` table, `llm_config_repo`, `llm_config_service`) and follows a `routers/admin → services → db/repos → db/models` layered architecture. The credential feature will slot into the same pattern. Org-scoped admin endpoints already use `ManagementAuthContext.has_org_access(org_id)` (see `app/routers/admin/llm_config.py`); credential endpoints reuse that exact primitive.

## Goals / Non-Goals

**Goals:**
- Store one encrypted API key per (org, provider) pair in SQLite.
- Expose CRUD endpoints on `/admin/v1/orgs/{org_slug}/credentials` consumed by the future BW5 settings UI, all org-scoped via `has_org_access`.
- Resolve the org's credential in the request hot-path and pass it to `ExternalLLMService`; never touch the env key at call time.
- Fail with HTTP 402 (Payment Required) when no credential exists for the chosen provider — no silent fallback, no retry-friendly 503.
- Let operators seed the demo org's credential from the CLI without exposing the key on argv.
- Keep dev/test/CI flows that do not touch credentials working without `DEJAQ_CREDENTIAL_ENCRYPTION_KEY` set.

**Non-Goals:**
- Multi-key rotation (one active key per provider is sufficient for now).
- Wiring all 8 providers in this change. **In scope as live providers:** `google` (Gemini), `openai`, `anthropic`. **Storage-only:** `mistral`, `cohere`, `together`, `groq`, `fireworks` — keys can be saved and listed but the chat router will return HTTP 422 if the configured `external_model` resolves to one of these, since no client is wired.
- UI — the settings page lands with BW5.
- Key auditing or revocation history (tracked as follow-up).
- Master key rotation tooling (tracked as follow-up — `dejaq-admin rotate-encryption-key`).

## Decisions

### D1 — Fernet symmetric encryption at rest, lazy validation

**Choice:** Encrypt stored keys with `cryptography.fernet.Fernet` using a single master key (`DEJAQ_CREDENTIAL_ENCRYPTION_KEY`) from env. The key is validated **on first instantiation of `CredentialService`** — not at module import. If the master key is missing or malformed when `CredentialService` is first used, the service raises `ValueError`.

**Rationale:** Fernet is AES-128-CBC + HMAC-SHA256 with authenticated encryption; the `cryptography` package is well-audited. A single master key is simpler to rotate (re-encrypt all rows) than per-row key-derivation schemes and is appropriate for a SQLite-backed deployment. Lazy validation prevents the credential subsystem from breaking unrelated flows: the enricher/normalizer/adjuster test harnesses, CI runs that don't touch credentials, and dev environments without the key all continue to work. The first request that needs a credential surfaces the misconfiguration loudly.

**Alternative considered:** Validate at module import in `app.config`. Rejected — breaks every dev environment, every CI job, and every offline test harness on day one of pulling this change.

**Alternative considered:** Store keys as plaintext and rely on filesystem permissions. Rejected because it provides no defence-in-depth if the SQLite file is exfiltrated.

**Alternative considered:** Per-row key derivation (HKDF from master + row salt). Deferred — adds complexity without practical benefit until we migrate to PostgreSQL row-level security.

---

### D2 — Multi-provider client layer; stateless; per-call API key; no key logging

**Choice:** `ExternalLLMService` becomes a thin **dispatcher** that delegates to a per-provider client implementing a common interface:

```python
class LLMProviderClient(Protocol):
    async def generate_response(
        self, request: ExternalLLMRequest, api_key: str
    ) -> ExternalLLMResponse: ...
```

Three concrete implementations land in `app/services/llm_providers/`:

- `google.py` — wraps `google-genai`, instantiates `genai.Client(api_key=...)` per call. Converts OpenAI-style `assistant` role to Gemini's `model` role. Maps `genai_errors.ClientError(401)` → `ExternalLLMAuthError`.
- `openai.py` — wraps `openai>=1.0` (`AsyncOpenAI(api_key=...)`). Uses native chat-completions message format directly. Maps `openai.AuthenticationError` → `ExternalLLMAuthError`, `openai.APITimeoutError` → `ExternalLLMTimeoutError`.
- `anthropic.py` — wraps `anthropic` SDK (`AsyncAnthropic(api_key=...)`). Splits `system_instruction` from message history (Anthropic requires `system` as a top-level param, not a message role). Maps `anthropic.AuthenticationError` → `ExternalLLMAuthError`, `anthropic.APITimeoutError` → `ExternalLLMTimeoutError`.

`ExternalLLMService.generate_response(request, provider, api_key)` looks up the right client by provider string and calls it. The singleton pattern is removed; clients are short-lived per call.

In every implementation: the `api_key` parameter is never logged, and any provider error body is redacted (substring-match against the api_key value, replace with `<redacted>`) before being logged.

**Rationale:** A common interface keeps the chat-router gate provider-agnostic and lets each provider's quirks (role naming, system-prompt placement, error taxonomy) live in one place. Caching clients per org would require a concurrent-safe LRU cache; client construction across all three SDKs is sub-millisecond, so the simpler model wins. Explicit redaction defends against the (real) case of a provider echoing the key in an error body.

**Alternative considered:** Stuff all three providers into one giant `ExternalLLMService.generate_response`. Rejected — each SDK has different message formats, role conventions, and error types; one method becomes a 200-line `if/elif` chain.

**Alternative considered:** LRU cache of provider clients keyed on api_key hash. Deferred — premature optimisation; revisit if profiling shows construction overhead.

---

### D3 — Credential lookup in the chat router, not inside `ExternalLLMService`

**Choice:** `openai_compat.py` reads `request.state.org_id` (added by the API key middleware alongside `org_slug`), derives the provider from the configured external model name (see D7), and calls `CredentialService.get_decrypted_key(org_id, provider)` before dispatching to `ExternalLLMService`. A missing key returns `JSONResponse(status_code=402, content={"detail": "No <provider> API key configured for this organization. Add one via the credentials settings."})`.

**Rationale:** Keeps `ExternalLLMService` provider-agnostic and testable without DB fixtures. The router already owns the request/org context; centralising the credential gate there makes the failure path explicit and easily observable in logs.

**Alternative considered:** Inject credential lookup inside `ExternalLLMService.generate_response`. Rejected — couples DB access to the LLM client, makes unit testing harder.

---

### D4 — Provider enum validated at write time; stored as lowercase string with CHECK constraint

**Choice:** Accept provider names from a fixed enum (`google`, `openai`, `anthropic`, `mistral`, `cohere`, `together`, `groq`, `fireworks`) validated in the Pydantic request schema. Store as a lowercase VARCHAR in the DB with a `CHECK (provider IN (...))` constraint as defence-in-depth against direct DB writes.

**Rationale:** Validation at write time prevents garbage entries via the API. The CHECK constraint catches CLI/migration/manual-SQL writes that bypass Pydantic. A string column (not a DB enum) keeps the Alembic migration simple and lets us add providers later without a schema change — adding a provider requires updating both the Pydantic enum and the CHECK constraint, which is a straightforward Alembic migration.

---

### D5 — Key masked to `<first4>****<last4>` in list/get responses; short keys fully masked

**Choice:** The list endpoint returns `{"provider": "google", "key_preview": "AIza****abcd", "created_at": "..."}`. The full key is never returned by any read endpoint. **For keys shorter than 12 characters**, the preview is `********` (eight asterisks, no first/last reveal) — preventing leakage of test stubs or short keys.

**Rationale:** Follows industry convention (Stripe, OpenAI) — the preview is enough for a human to verify which key is configured without exposing the secret. Real provider keys are well above the 12-char threshold (Gemini ~39 chars, OpenAI 51 chars, Anthropic ~100 chars), so the masked preview remains useful in practice.

---

### D6 — Org ID threaded from API key middleware

**Choice:** The existing `api_key.py` middleware already sets `request.state.org_slug`. We add `request.state.org_id` (integer PK) alongside it so the chat router can pass the numeric ID directly to `CredentialService` without a secondary slug→ID lookup.

**Rationale:** Avoids an extra DB query per hard-routed request. The middleware already has the ORM object in scope.

---

### D7 — Provider derivation from external model name

**Choice:** Add a helper `provider_for_model(model_name: str) -> str` that maps configured external model names to provider strings:

| Pattern | Provider |
|---------|----------|
| `gemini-*` | `google` |
| `gpt-*`, `o1-*`, `o3-*`, `chatgpt-*` | `openai` |
| `claude-*` | `anthropic` |
| anything else | raise `ValueError("Unknown provider for model '<name>'")` |

The chat router calls this helper to determine which provider's credential to look up and which client to dispatch to. Unknown model names surface as HTTP 422 to the caller (`{"detail": "Configured external model '<name>' is not mapped to a supported provider."}`) rather than silently picking a default.

**Rationale:** Single source of truth for model→provider mapping. Adding a new provider in the future is a one-line table edit plus a new client module. Failing loudly on unknown models prevents a misconfigured `org_llm_config.external_model` from silently routing to the wrong provider's credential.

---

### D8 — Org-scoping enforced via existing auth primitive

**Choice:** All three credential endpoints (`GET`/`PUT`/`DELETE` under `/admin/v1/orgs/{org_slug}/credentials[...]`) call `ctx.has_org_access(org_id)` after resolving the org by slug, returning HTTP 403 if the caller lacks access. This mirrors the pattern already used by `app/routers/admin/llm_config.py`.

**Rationale:** Without this, the spec passes review but the implementation could ship a cross-tenant credential leak — a user with a valid Supabase JWT for org A could read/write org B's credentials by guessing the slug. The primitive already exists and is consistent across other org-scoped admin routes.

## Risks / Trade-offs

**Master key loss → all credentials permanently inaccessible**
→ Mitigation: Document `DEJAQ_CREDENTIAL_ENCRYPTION_KEY` in CLAUDE.md env table with a backup note. A `dejaq-admin rotate-encryption-key` CLI is tracked as follow-up before customer onboarding. `dejaq-admin` prints a warning when seeding credentials with the env var unset.

**SQLite file exfiltration exposes ciphertext only**
→ Mitigation: Fernet provides authenticated encryption; ciphertext is useless without the master key.

**Single active key per provider; no rotation path**
→ Mitigation: The upsert endpoint (PUT) replaces the key atomically. Operators swap the key via the API/UI; there is a brief window where in-flight requests using the old client may fail if the provider invalidates immediately. Acceptable at current scale.

**`genai.Client` instantiated per hard request**
→ Mitigation: Measured as <1 ms in the Gemini SDK; negligible versus network latency. A per-key LRU cache can be added later without schema or interface changes.

**No credential for a hard-classified query → user-visible 402**
→ Mitigation: Error message explicitly names the provider and says "configure credentials in the dashboard." 402 (Payment Required) is the correct semantic — the request needs paid credentials, not "the server is broken." 503 was rejected because clients/proxies retry on 503, alerting fires false pages, and load balancers may eject the host.

**Configured `external_model` resolves to an unwired provider (e.g., `mistral-large`) → user-visible 422**
→ Mitigation: `provider_for_model()` raises `ValueError` for unknown patterns, and the chat router catches it and returns HTTP 422 with a message naming the unmapped model. This prevents a silent fallback and surfaces operator misconfiguration loudly.

**Three SDKs to keep in lockstep on history/role/error mapping**
→ Mitigation: The `LLMProviderClient` Protocol enforces a single response shape (`ExternalLLMResponse`) and error taxonomy (`ExternalLLMAuthError`, `ExternalLLMTimeoutError`, `ExternalLLMError`). Each provider module owns its own message-format and error mapping — no leaking SDK types across the boundary. A shared contract test (`test_provider_clients_contract.py`) asserts each client returns the expected response shape and maps auth errors uniformly.

**No audit log of who set credentials, no rotation timestamp**
→ Tracked as follow-up. For v1 we accept that operator actions are unaudited; this is consistent with other admin tables (org_llm_config has no audit either). When customer onboarding lands, an audit table covering all admin mutations (orgs, departments, keys, credentials, llm-config) should be added in one pass.

## Migration Plan

1. Add `DEJAQ_CREDENTIAL_ENCRYPTION_KEY` to `.env` (generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`). **Back this value up** — losing it is unrecoverable.
2. Run `uv run alembic upgrade head` to create `org_provider_credentials` table.
3. For demo orgs, run `dejaq-admin seed demo` with the key piped via stdin or the `DEJAQ_SEED_PROVIDER_KEY` env var (see CLAUDE.md for syntax).
4. Remove `GEMINI_API_KEY` from `.env` once all orgs have their own credentials (or keep it for operator reference — it is no longer read at runtime).

**Rollback:** `uv run alembic downgrade -1` drops the new table. **Warning: downgrade destroys all stored encrypted credentials irreversibly** — operators must re-enter every org's API keys after a re-upgrade. The env key path can be restored with a one-line revert in `openai_compat.py`.

## Open Questions

(All previously open questions resolved in D7. Future work: provider-inference helper extension as new providers are wired; "test connection" probe button in the BW5 settings UI.)
