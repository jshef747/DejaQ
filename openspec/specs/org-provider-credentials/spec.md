# org-provider-credentials Specification

## Purpose
Define encrypted per-organization external LLM provider credentials, their management API surface, and how hard-query routing uses those credentials.

## Requirements

### Requirement: Master encryption key is required when credential subsystem is used

The system SHALL read a `DEJAQ_CREDENTIAL_ENCRYPTION_KEY` environment variable. The value SHALL be a valid Fernet key (32 URL-safe base64 bytes). Validation SHALL happen lazily on first instantiation of `CredentialService`, NOT at module import. If the variable is absent or malformed when `CredentialService` is first used, the service SHALL raise a `ValueError`. Flows that do not exercise `CredentialService` (e.g., dev environments, CI runs, the enricher/normalizer/adjuster test harnesses) SHALL continue to work without the variable set.

#### Scenario: App starts without encryption key when credentials unused

- **WHEN** `DEJAQ_CREDENTIAL_ENCRYPTION_KEY` is unset and the application starts and serves requests that do NOT invoke `CredentialService`
- **THEN** the application starts normally and serves those requests successfully

#### Scenario: First credential use without encryption key fails loudly

- **WHEN** `DEJAQ_CREDENTIAL_ENCRYPTION_KEY` is unset and any code path instantiates `CredentialService` for the first time
- **THEN** `CredentialService.__init__` raises `ValueError` and the surrounding handler returns an error to the caller

#### Scenario: First credential use with malformed key fails loudly

- **WHEN** `DEJAQ_CREDENTIAL_ENCRYPTION_KEY` contains a value that is not a valid Fernet key and `CredentialService` is instantiated
- **THEN** `CredentialService.__init__` raises `ValueError`

#### Scenario: Valid key permits credential operations

- **WHEN** `DEJAQ_CREDENTIAL_ENCRYPTION_KEY` is set to a valid Fernet key
- **THEN** `CredentialService` instantiates without error and encrypt/decrypt operations succeed

---

### Requirement: Provider credentials are stored encrypted with provider whitelist enforced at the DB level

The system SHALL persist per-org provider credentials in a new `org_provider_credentials` table with columns: `id` (INTEGER PK autoincrement), `org_id` (FK to `organizations.id` ON DELETE CASCADE), `provider` (VARCHAR NOT NULL), `encrypted_key` (TEXT NOT NULL), `created_at` (TIMESTAMP NOT NULL), `updated_at` (TIMESTAMP NOT NULL). The `(org_id, provider)` pair SHALL be unique under a constraint named `uq_org_provider_credentials_org_provider`. Provider values SHALL be restricted to: `google`, `openai`, `anthropic`, `mistral`, `cohere`, `together`, `groq`, `fireworks`. The whitelist SHALL be enforced both in the Pydantic request schema AND by a `CHECK` constraint on the `provider` column (defence-in-depth against direct DB writes). The raw API key SHALL never be written to the database; only the Fernet-encrypted ciphertext SHALL be stored.

#### Scenario: Storing a credential encrypts the key

- **WHEN** an operator upserts a credential for org `acme` and provider `google` with key `AIzaXXX`
- **THEN** the stored `encrypted_key` column contains Fernet ciphertext, not the plaintext key

#### Scenario: Deleting an org cascades its credentials

- **WHEN** an org is deleted via `DELETE /admin/v1/orgs/{slug}`
- **THEN** all rows in `org_provider_credentials` for that org are deleted by FK cascade

#### Scenario: Duplicate provider key is rejected at DB level

- **WHEN** a second INSERT is attempted for the same `(org_id, provider)` pair
- **THEN** the unique constraint is violated; the service layer MUST use upsert instead of raw INSERT

#### Scenario: Direct DB write with invalid provider is rejected

- **WHEN** a direct SQL INSERT attempts to write `provider = 'invalid_provider'`
- **THEN** the DB CHECK constraint rejects the write

---

### Requirement: All credential endpoints enforce org-scoped authorization

The system SHALL enforce org-scoped authorization on every credential endpoint by calling `ManagementAuthContext.has_org_access(org_id)` after resolving the org by slug. Callers without access to the target org SHALL receive HTTP 403, regardless of whether the org or credentials exist. This mirrors the org-scoping pattern already used by `/admin/v1/orgs/{slug}/llm-config`.

#### Scenario: Caller without org access receives 403 on list

- **WHEN** an authenticated caller without access to org `acme` calls `GET /admin/v1/orgs/acme/credentials`
- **THEN** the response is HTTP 403 and no credential data is returned

#### Scenario: Caller without org access receives 403 on upsert

- **WHEN** an authenticated caller without access to org `acme` PUTs to `/admin/v1/orgs/acme/credentials/google`
- **THEN** the response is HTTP 403 and no row is written

#### Scenario: Caller without org access receives 403 on delete

- **WHEN** an authenticated caller without access to org `acme` DELETEs `/admin/v1/orgs/acme/credentials/google`
- **THEN** the response is HTTP 403 and no row is deleted

---

### Requirement: List credentials endpoint with safe masking

The system SHALL expose `GET /admin/v1/orgs/{org_slug}/credentials` returning HTTP 200 with an array of `{provider, key_preview, created_at, updated_at}` objects. `key_preview` SHALL mask the key as `<first4>****<last4>` when the underlying key has at least 12 characters; SHALL mask as `********` (eight asterisks) when the key has fewer than 12 characters, to prevent leaking short keys or test stubs. The full decrypted key SHALL NOT appear in any response body. Unknown org SHALL return HTTP 404. Org inaccessible to the caller SHALL return HTTP 403.

#### Scenario: List returns masked keys for normal-length keys

- **WHEN** an authorized client calls `GET /admin/v1/orgs/acme/credentials` and `acme` has a `google` credential with key `AIzaFoo123Bar` (13 chars)
- **THEN** the response is HTTP 200 with an array containing `{"provider": "google", "key_preview": "AIza****3Bar", ...}`
- **THEN** the response does NOT contain the full key string `AIzaFoo123Bar`

#### Scenario: List fully masks short keys

- **WHEN** an authorized client calls `GET /admin/v1/orgs/acme/credentials` and `acme` has a credential with a key shorter than 12 characters (e.g., `short123`)
- **THEN** the `key_preview` field is `"********"` and does NOT reveal any characters of the underlying key

#### Scenario: List returns empty array when no credentials configured

- **WHEN** an authorized client calls `GET /admin/v1/orgs/acme/credentials` and no credentials exist
- **THEN** the response is HTTP 200 with `[]`

#### Scenario: List for unknown org returns 404

- **WHEN** an authorized client calls `GET /admin/v1/orgs/missing/credentials`
- **THEN** the response is HTTP 404

---

### Requirement: Upsert credential endpoint

The system SHALL expose `PUT /admin/v1/orgs/{org_slug}/credentials/{provider}` accepting `{api_key: str}` and upserting the encrypted credential for that org and provider. HTTP 200 SHALL be returned with the masked credential object `{provider, key_preview, created_at, updated_at}`. An empty or whitespace-only `api_key` SHALL return HTTP 422. An invalid provider name SHALL return HTTP 422. Unknown org SHALL return HTTP 404. Org inaccessible to the caller SHALL return HTTP 403.

#### Scenario: Upsert creates a new credential

- **WHEN** an authorized client PUTs `{"api_key": "AIzaXXXXXXXXX"}` to `/admin/v1/orgs/acme/credentials/google` and no credential exists
- **THEN** the response is HTTP 200 with `{"provider": "google", "key_preview": "AIza****XXXX", ...}`
- **THEN** the database contains one encrypted row for `(acme, google)`

#### Scenario: Upsert replaces an existing credential

- **WHEN** an authorized client PUTs a new `api_key` for a provider that already has a credential
- **THEN** the old ciphertext is replaced and `updated_at` is updated

#### Scenario: Upsert with empty key returns 422

- **WHEN** an authorized client PUTs `{"api_key": "   "}` to a credential endpoint
- **THEN** the response is HTTP 422

#### Scenario: Upsert with invalid provider returns 422

- **WHEN** an authorized client PUTs to `/admin/v1/orgs/acme/credentials/unknown_provider`
- **THEN** the response is HTTP 422

---

### Requirement: Delete credential endpoint

The system SHALL expose `DELETE /admin/v1/orgs/{org_slug}/credentials/{provider}` to remove a configured provider credential. HTTP 200 SHALL be returned with `{"deleted": true}` when a credential existed and was removed. Unknown org SHALL return HTTP 404. Missing credential for a known org/provider SHALL return HTTP 404. Org inaccessible to the caller SHALL return HTTP 403.

#### Scenario: Delete existing credential

- **WHEN** an authorized client calls `DELETE /admin/v1/orgs/acme/credentials/google`
- **THEN** the response is HTTP 200 with `{"deleted": true}`
- **THEN** subsequent GET of the same org's credentials does not include the `google` entry

#### Scenario: Delete non-existent credential returns 404

- **WHEN** an authorized client calls `DELETE /admin/v1/orgs/acme/credentials/openai` and no `openai` credential exists
- **THEN** the response is HTTP 404

---

### Requirement: LLM router resolves org credential via provider inference; supports google, openai, anthropic

The system SHALL derive the target provider from the configured external model name via a `provider_for_model(model_name)` helper. The mapping SHALL cover at minimum:

- `gemini-*` -> `google`
- `gpt-*`, `o1-*`, `o3-*`, `chatgpt-*` -> `openai`
- `claude-*` -> `anthropic`

For each request, the system SHALL look up the calling org's encrypted credential for the derived provider and dispatch to the matching provider client. The lookup SHALL decrypt the key using `DEJAQ_CREDENTIAL_ENCRYPTION_KEY`. The system SHALL NOT fall back to any environment variable (`GEMINI_API_KEY` or equivalent) during request processing.

The system SHALL define `LIVE_PROVIDERS = {"google", "openai", "anthropic"}` - the set of providers wired to a live client. Other entries in `SUPPORTED_PROVIDERS` are storage-only.

Failure modes:

- If `provider_for_model` raises `ValueError` for an unmapped model name, the system SHALL return HTTP 422.
- If the resolved provider is in `SUPPORTED_PROVIDERS` but NOT in `LIVE_PROVIDERS`, the system SHALL return HTTP 422 - no credential lookup is attempted.
- If no credential row exists for the org and a live provider, the system SHALL return HTTP 402 Payment Required with body `{"detail": "No <provider> API key configured for this organization. Add one via the credentials settings."}`.
- The system SHALL NOT use HTTP 503 for missing-credential or unwired-provider cases (permanent per-tenant config errors must not present as transient server faults).

#### Scenario: Hard query routes to Google provider client

- **WHEN** an org has a `google` credential and `EXTERNAL_MODEL_NAME` is `gemini-2.5-flash`
- **THEN** `provider_for_model` resolves `"google"`, the credential is decrypted, and the Google provider client is invoked
- **THEN** the response is HTTP 200 with the generated answer

#### Scenario: Hard query routes to OpenAI provider client

- **WHEN** an org has an `openai` credential and `EXTERNAL_MODEL_NAME` is `gpt-4o`
- **THEN** `provider_for_model` resolves `"openai"`, the credential is decrypted, and the OpenAI provider client is invoked
- **THEN** the response is HTTP 200 with the generated answer

#### Scenario: Hard query routes to Anthropic provider client

- **WHEN** an org has an `anthropic` credential and `EXTERNAL_MODEL_NAME` is `claude-sonnet-4-5`
- **THEN** `provider_for_model` resolves `"anthropic"`, the credential is decrypted, and the Anthropic provider client is invoked
- **THEN** the response is HTTP 200 with the generated answer

#### Scenario: Hard query without credential returns 402

- **WHEN** an org has NO credential for the resolved provider and sends a hard-classified query
- **THEN** the response is HTTP 402 with `{"detail": "No <provider> API key configured..."}`
- **THEN** no provider client is invoked

#### Scenario: Configured model maps to unwired provider returns 422

- **WHEN** `EXTERNAL_MODEL_NAME` resolves to a provider in `SUPPORTED_PROVIDERS` but not in `LIVE_PROVIDERS` (e.g., `mistral-large` -> `mistral`)
- **THEN** the response is HTTP 422 with a message that the provider is not yet wired
- **THEN** no credential lookup is performed

#### Scenario: Unmapped model name returns 422

- **WHEN** `EXTERNAL_MODEL_NAME` does not match any pattern in `provider_for_model`
- **THEN** the response is HTTP 422 with a message naming the unmapped model

#### Scenario: 503 is never used for missing-credential or unwired-provider failures

- **WHEN** any hard query fails because no credential exists or the provider is unwired
- **THEN** the status code is 402 or 422, never 503

#### Scenario: Platform env key is never used at request time

- **WHEN** `GEMINI_API_KEY` is set in the environment but the requesting org has no credential
- **THEN** the response is still HTTP 402 - the env key is not used as a fallback

---

### Requirement: Each live provider client implements a uniform contract

The system SHALL provide three live provider client modules under `app/services/llm_providers/` (`google.py`, `openai.py`, `anthropic.py`), each exposing the same `LLMProviderClient` Protocol: `async generate_response(request: ExternalLLMRequest, api_key: str) -> ExternalLLMResponse`. Each client SHALL instantiate its underlying SDK client per call (no singletons), populate `ExternalLLMResponse` with `text`, `model_used`, `prompt_tokens`, `completion_tokens`, `latency_ms`, and map provider-specific exceptions uniformly:

- Authentication failures -> `ExternalLLMAuthError`
- Timeouts -> `ExternalLLMTimeoutError`
- Other provider errors -> `ExternalLLMError`

The api_key SHALL never appear in any log statement emitted by these clients, and provider error bodies SHALL be redacted before logging.

#### Scenario: All three clients return the same response shape

- **WHEN** any of the three live provider clients completes a successful `generate_response` call
- **THEN** the returned `ExternalLLMResponse` has populated `text`, `model_used`, `prompt_tokens`, `completion_tokens`, and `latency_ms` fields

#### Scenario: All three clients map auth errors uniformly

- **WHEN** the underlying SDK raises an authentication error (`genai_errors.ClientError(401)`, `openai.AuthenticationError`, or `anthropic.AuthenticationError`)
- **THEN** the provider client raises `ExternalLLMAuthError`

#### Scenario: All three clients map timeout errors uniformly

- **WHEN** the underlying SDK raises a timeout (`openai.APITimeoutError`, `anthropic.APITimeoutError`, or the equivalent google-genai timeout)
- **THEN** the provider client raises `ExternalLLMTimeoutError`

#### Scenario: api_key never appears in logs

- **WHEN** any of the three provider clients runs (success or error path) with api_key `SecretKey123`
- **THEN** the captured log output for that request does NOT contain the substring `SecretKey123`

#### Scenario: Anthropic client splits system prompt from messages

- **WHEN** the Anthropic provider client receives a request with a non-empty `system_prompt` and a history of user/assistant messages
- **THEN** the underlying `client.messages.create` call is invoked with `system=<system_prompt>` as a top-level parameter and only user/assistant entries in `messages`

---

### Requirement: API keys are never logged across the dispatcher and all live providers

The system SHALL never write a decrypted API key to logs from the `ExternalLLMService` dispatcher or any live provider client (`google`, `openai`, `anthropic`). The `api_key` parameter passed through the dispatcher and into each provider client SHALL not appear in any log statement on any code path (success, auth failure, timeout, generic error). Any provider error body returned by the underlying SDK (`genai_errors.ClientError` / `APIError`, `openai.OpenAIError` and subclasses, `anthropic.APIError` and subclasses) SHALL be redacted by substring-replacing the api_key value with `<redacted>` before being logged.

#### Scenario: Successful hard query does not log api_key (any provider)

- **WHEN** a hard query succeeds via any of the three live providers with api_key `Secret_AbC_123`
- **THEN** the captured log output for that request does NOT contain the substring `Secret_AbC_123`

#### Scenario: Provider error body is redacted before logging (any provider)

- **WHEN** any live provider returns an error body that contains the api_key value
- **THEN** the logged error message contains `<redacted>` in place of the api_key
