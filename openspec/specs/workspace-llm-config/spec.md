# workspace-llm-config Specification

## Purpose
Define per-workspace LLM routing configuration persistence and the management endpoints used to read and update effective overrides.

## Requirements

### Requirement: Per-workspace LLM config is persisted

The system SHALL persist a single LLM configuration record per workspace in a new `workspace_llm_configs` table with columns: `workspace_id` (PK, FK to `workspaces.id`, ON DELETE CASCADE), `external_model` (TEXT, nullable), `external_provider` (TEXT, nullable - the provider recorded for `external_model` when it is saved), the six pipeline-role model columns `local_model`, `generalizer_model`, `adjuster_model`, `enricher_model`, `normalizer_model`, `validator_model` (each TEXT, nullable), the seven pipeline-role system prompt columns `enricher_system_prompt`, `normalizer_system_prompt`, `validator_system_prompt`, `validator_image_system_prompt`, `adjuster_system_prompt`, `generalizer_system_prompt`, `local_model_system_prompt` (each TEXT, nullable), `routing_threshold` (REAL, nullable), the three token-budget columns `default_max_tokens`, `rewrite_max_tokens`, `ollama_num_ctx` (each INTEGER, nullable), `updated_at` (TIMESTAMP, NOT NULL). Nullable config columns with `NULL` values SHALL fall back to the global defaults defined in `app.config` (models, routing threshold, and token budgets - each token-budget column mirrors the `app.config` constant of the same name uppercased) or to the owning service module's shipped `DEFAULT_*_SYSTEM_PROMPT` constant (prompts). `external_model` is the one field whose global default may itself be unset: `app.config.EXTERNAL_MODEL_NAME` is `DEJAQ_EXTERNAL_MODEL` with no baked-in literal behind it, so a workspace that overrides neither reads back `null` - "no model configured", never a substituted one.

#### Scenario: Workspace with no config row uses defaults

- **WHEN** a workspace has no row in `workspace_llm_configs`
- **THEN** reads return the global defaults from `app.config` for every field, `is_default=true`, `updated_at=null`, and an empty `overrides` object

#### Scenario: Deleting a workspace cascades its config

- **WHEN** a workspace is deleted via `DELETE /admin/v1/workspaces/{slug}`
- **THEN** its `workspace_llm_configs` row, if any, is removed by the FK cascade

### Requirement: Read LLM config endpoint

The system SHALL expose `GET /admin/v1/workspaces/{workspace_slug}/llm-config` returning HTTP 200 with `{external_model, local_model, generalizer_model, adjuster_model, enricher_model, normalizer_model, validator_model, enricher_system_prompt, normalizer_system_prompt, validator_system_prompt, validator_image_system_prompt, adjuster_system_prompt, generalizer_system_prompt, local_model_system_prompt, routing_threshold, default_max_tokens, rewrite_max_tokens, ollama_num_ctx, overrides, updated_at, is_default, credentials_configured}`. The top-level model, system prompt, and token-budget fields SHALL contain effective values after merging stored overrides with the shipped defaults, so a prompt field is never empty. The `overrides` object SHALL contain only fields currently overridden by the workspace row. The `is_default` field SHALL be `true` when no row exists or every nullable config column is `NULL`; otherwise `false`. `updated_at` SHALL be `null` when no row exists. If a row exists but all nullable config columns are `NULL`, `is_default=true`, `overrides={}`, and `updated_at` SHALL return the row timestamp. Unknown workspace SHALL return HTTP 404. The `credentials_configured` field SHALL be a list of provider strings for which the workspace has a credential row (may be empty).

#### Scenario: Read config for workspace with no row

- **WHEN** an authorized client calls `GET /admin/v1/workspaces/acme/llm-config` and `acme` has no `workspace_llm_configs` row
- **THEN** the response is HTTP 200 with the global defaults, `"overrides": {}`, `"updated_at": null`, `"is_default": true`, and `"credentials_configured": []`

#### Scenario: Read config for workspace with credentials configured

- **WHEN** an authorized client calls `GET /admin/v1/workspaces/acme/llm-config` and `acme` has a `google` credential
- **THEN** the response includes `"credentials_configured": ["google"]`

#### Scenario: Read config for unknown workspace

- **WHEN** an authorized client calls `GET /admin/v1/workspaces/missing/llm-config`
- **THEN** the response is HTTP 404

### Requirement: Update LLM config endpoint

The system SHALL expose `PUT /admin/v1/workspaces/{workspace_slug}/llm-config` accepting any non-empty subset of `{external_model, local_model, generalizer_model, adjuster_model, enricher_model, normalizer_model, validator_model, enricher_system_prompt, normalizer_system_prompt, validator_system_prompt, validator_image_system_prompt, adjuster_system_prompt, generalizer_system_prompt, local_model_system_prompt, routing_threshold, default_max_tokens, rewrite_max_tokens, ollama_num_ctx}` where each field may be omitted, non-null, or explicit `null`. Empty `{}` bodies SHALL return HTTP 422 and SHALL NOT create or update a row. The endpoint SHALL upsert the `workspace_llm_configs` row, set `updated_at = now()`, and return HTTP 200 with the resulting effective config including `credentials_configured`. Fields not present in the request body SHALL retain their previous stored value. Explicit `null` SHALL clear that workspace-level override and make reads fall back to the global default for that field. Unknown workspace SHALL return HTTP 404. Invalid `routing_threshold` (not a number, or outside `[0.0, 1.0]`) SHALL return HTTP 422.

#### Scenario: Partial update preserves untouched fields

- **WHEN** an authorized client PUTs `{"external_model": "gemini-2.5-pro"}` and the row already has `local_model = "gemma-4-e4b"`
- **THEN** the response and stored row both have `external_model = "gemini-2.5-pro"` and `local_model = "gemma-4-e4b"`

#### Scenario: Explicit null clears an override

- **WHEN** an authorized client PUTs `{"external_model": null}` and the row previously had `external_model = "gemini-2.5-pro"`
- **THEN** the stored `external_model` and `external_provider` are both `NULL`, the response `external_model` is the global default (which is itself `null` when `DEJAQ_EXTERNAL_MODEL` is unset), and `external_model` is absent from `overrides`

#### Scenario: Empty update is rejected

- **WHEN** an authorized client PUTs `{}`
- **THEN** the response is HTTP 422 and no config row is created or updated

#### Scenario: Update creates row when none exists

- **WHEN** an authorized client PUTs an LLM config for a workspace with no existing row
- **THEN** a new `workspace_llm_configs` row is inserted and the response reflects the supplied values

#### Scenario: Routing threshold out of range

- **WHEN** an authorized client PUTs `{"routing_threshold": 1.5}`
- **THEN** the response is HTTP 422

### Requirement: Pipeline-role model overrides are validated against the live Ollama catalog

A non-null value for any of the six pipeline-role model fields (`local_model`, `generalizer_model`, `adjuster_model`, `enricher_model`, `normalizer_model`, `validator_model`) SHALL be validated on write against a forced (cache-bypassing) `GET /api/tags` call to the configured Ollama host, accepting any installed tag rather than only tags registered in `MODEL_RUNTIME_SPECS`. A value Ollama does not currently report SHALL return HTTP 422 naming the offending field and value, and SHALL NOT be stored. An unreachable Ollama SHALL also return HTTP 422. Explicit `null` (reset to default) SHALL skip this validation, so an override can be cleared while Ollama is down. `external_model` names a provider model string, not an Ollama tag, and SHALL NOT be validated this way - it is validated against the provider registry instead (see the requirement below).

A role whose stored override names a tag that was later uninstalled SHALL NOT fail the request that uses it: the affected role SHALL fall back to its shipped default and log a warning.

#### Scenario: Model override naming an uninstalled tag

- **WHEN** an authorized client PUTs `{"validator_model": "not-installed:1b"}` and Ollama does not report that tag
- **THEN** the response is HTTP 422 naming the field and value, and no override is stored

#### Scenario: Clearing an override while Ollama is unreachable

- **WHEN** an authorized client PUTs `{"validator_model": null}` and Ollama is unreachable
- **THEN** the override is cleared and the response returns the shipped default for that field

#### Scenario: Stored override is uninstalled after the fact

- **WHEN** a workspace has `enricher_model` set to a tag that is no longer installed and a request exercises the context enricher
- **THEN** the role runs on its shipped default model and a warning is logged, rather than the request failing

### Requirement: external_model is validated against the provider registry and records its provider

A non-null `external_model` SHALL be validated on write against the provider registry (`app/services/provider_registry.py`), the single declaration of which providers exist and which models each offers. A value no provider in the registry offers SHALL return HTTP 422 naming the offending model, and SHALL NOT be stored. A valid value SHALL be stored together with the offering provider in `external_provider`, so the request path reads a recorded provider rather than guessing one from the model name. Explicit `null` SHALL clear both columns and SHALL skip validation.

The registry SHALL also be served read-only as `GET /admin/v1/providers`, returning each provider's key, whether it is wired to a live client, its client wire shape, and its models with each model's accepted input kinds - the one source the dashboard's provider/model pickers read, so no client ships its own copy of the list.

#### Scenario: Unknown external model is rejected

- **WHEN** an authorized client PUTs `{"external_model": "not-a-real-model"}`
- **THEN** the response is HTTP 422 naming the model and no override is stored

#### Scenario: Saving a model records its provider

- **WHEN** an authorized client PUTs `{"external_model": "claude-sonnet-5"}`
- **THEN** the row stores `external_provider = "anthropic"` alongside it

### Requirement: Blank system prompt overrides are rejected

A value for any of the seven `*_system_prompt` fields that is empty or contains only whitespace SHALL return HTTP 422 naming the offending field and instructing the caller to send `null` to restore the shipped default, and SHALL NOT be stored. Explicit `null` SHALL clear the override. The same check SHALL apply to a direct service-layer update that bypasses the request schema.

#### Scenario: Blank prompt is rejected

- **WHEN** an authorized client PUTs `{"validator_system_prompt": "   "}`
- **THEN** the response is HTTP 422 and no override is stored

#### Scenario: Null prompt restores the shipped default

- **WHEN** an authorized client PUTs `{"validator_system_prompt": null}` and the row previously had a custom prompt
- **THEN** the stored column is `NULL`, the response returns the shipped default text, and the field is absent from `overrides`

### Requirement: Token budget overrides are validated as a relationship, not per field

Each of `default_max_tokens`, `rewrite_max_tokens`, and `ollama_num_ctx` SHALL be a positive integer, and `ollama_num_ctx` SHALL additionally be at most the `app.config.OLLAMA_NUM_CTX` global default (32768 as shipped). One window is sent to every Ollama-backed role, so the ceiling is the SMALLEST context maximum among the models sharing it (`qwen2.5:1.5b`, which runs the enricher and adjuster), not the largest; that is the bound `OLLAMA_NUM_CTX` already encodes, so the ceiling SHALL read it rather than restate a literal. Per-field bounds alone are not sufficient: when an update touches any of the three, the system SHALL validate the EFFECTIVE resulting triple (the values the workspace would have after the update lands, taking the stored value, or the `app.config` global default when unset, for any of the three the request does not touch) against all of:

- `default_max_tokens` SHALL be greater than `1024`, the value `app.config` records as having measurably truncated ordinary answers mid-sentence;
- `rewrite_max_tokens` SHALL be at least 2x `default_max_tokens`, because `generalize()`/`adjust()` are handed the whole raw answer and must keep every fact, and a truncated STORED copy never self-heals;
- `ollama_num_ctx` SHALL be at least 2x `rewrite_max_tokens`, because the context window bounds the prompt as well as the generation.

A violating combination SHALL return HTTP 422 whose message names the offending value and the relationship it breaks, and SHALL NOT be stored; the system SHALL NOT clamp, auto-correct, or accept-and-warn. An update that touches none of the three SHALL NOT re-validate them. Explicit `null` SHALL clear the override, after which the field's global default participates in the relationship.

#### Scenario: Rewrite budget too close to the answer budget

- **WHEN** an authorized client PUTs `{"default_max_tokens": 4096, "rewrite_max_tokens": 5000}`
- **THEN** the response is HTTP 422 naming `rewrite_max_tokens` and no override is stored

#### Scenario: Violation judged against the effective triple

- **WHEN** a workspace already stores `rewrite_max_tokens = 8192` and an authorized client PUTs `{"default_max_tokens": 8000}` alone
- **THEN** the response is HTTP 422, because the resulting triple leaves the rewrite budget under 2x the answer budget

#### Scenario: Answer budget at the measured truncation cap

- **WHEN** an authorized client PUTs `{"default_max_tokens": 1024}`
- **THEN** the response is HTTP 422 and no override is stored

#### Scenario: Context window above the smallest sharing model's maximum

- **WHEN** an authorized client PUTs `{"ollama_num_ctx": 65536}` against the shipped `OLLAMA_NUM_CTX` of 32768
- **THEN** the response is HTTP 422 naming `ollama_num_ctx`, because the enricher and adjuster share that window on a model that cannot honour it - the ceiling is a floor-of-the-two, so the override can only lower the shipped window, never raise it
