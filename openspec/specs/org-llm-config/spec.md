# org-llm-config Specification

## Purpose
Define per-organization LLM routing configuration persistence and the management endpoints used to read and update effective overrides.

## Requirements

### Requirement: Per-org LLM config is persisted

The system SHALL persist a single LLM configuration record per organization in a new `org_llm_config` table with columns: `org_id` (PK, FK to `organizations.id`, ON DELETE CASCADE), `external_model` (TEXT, nullable), `local_model` (TEXT, nullable), `routing_threshold` (REAL, nullable), `updated_at` (TIMESTAMP, NOT NULL). Nullable config columns with `NULL` values SHALL fall back to the global defaults defined in `app.config`.

#### Scenario: Org with no config row uses defaults

- **WHEN** an org has no row in `org_llm_config`
- **THEN** reads return the global defaults from `app.config` for every field, `is_default=true`, `updated_at=null`, and an empty `overrides` object

#### Scenario: Deleting an org cascades its config

- **WHEN** an org is deleted via `DELETE /admin/v1/orgs/{slug}`
- **THEN** its `org_llm_config` row, if any, is removed by the FK cascade

### Requirement: Read LLM config endpoint

The system SHALL expose `GET /admin/v1/orgs/{org_slug}/llm-config` returning HTTP 200 with `{external_model, local_model, routing_threshold, overrides, updated_at, is_default, credentials_configured}`. The top-level model fields SHALL contain effective values after merging stored overrides with global defaults. The `overrides` object SHALL contain only fields currently overridden by the org row. The `is_default` field SHALL be `true` when no row exists or every nullable config column is `NULL`; otherwise `false`. `updated_at` SHALL be `null` when no row exists. If a row exists but all nullable config columns are `NULL`, `is_default=true`, `overrides={}`, and `updated_at` SHALL return the row timestamp. Unknown org SHALL return HTTP 404. The `credentials_configured` field SHALL be a list of provider strings for which the org has a credential row (may be empty).

#### Scenario: Read config for org with no row

- **WHEN** an authorized client calls `GET /admin/v1/orgs/acme/llm-config` and `acme` has no `org_llm_config` row
- **THEN** the response is HTTP 200 with the global defaults, `"overrides": {}`, `"updated_at": null`, `"is_default": true`, and `"credentials_configured": []`

#### Scenario: Read config for org with credentials configured

- **WHEN** an authorized client calls `GET /admin/v1/orgs/acme/llm-config` and `acme` has a `google` credential
- **THEN** the response includes `"credentials_configured": ["google"]`

#### Scenario: Read config for unknown org

- **WHEN** an authorized client calls `GET /admin/v1/orgs/missing/llm-config`
- **THEN** the response is HTTP 404

### Requirement: Update LLM config endpoint

The system SHALL expose `PUT /admin/v1/orgs/{org_slug}/llm-config` accepting any non-empty subset of `{external_model, local_model, routing_threshold}` where each field may be omitted, non-null, or explicit `null`. Empty `{}` bodies SHALL return HTTP 422 and SHALL NOT create or update a row. The endpoint SHALL upsert the `org_llm_config` row, set `updated_at = now()`, and return HTTP 200 with the resulting effective config including `credentials_configured`. Fields not present in the request body SHALL retain their previous stored value. Explicit `null` SHALL clear that org-level override and make reads fall back to the global default for that field. Unknown org SHALL return HTTP 404. Invalid `routing_threshold` (not a number, or outside `[0.0, 1.0]`) SHALL return HTTP 422.

#### Scenario: Partial update preserves untouched fields

- **WHEN** an authorized client PUTs `{"external_model": "gemini-2.5-pro"}` and the row already has `local_model = "gemma-4-e4b"`
- **THEN** the response and stored row both have `external_model = "gemini-2.5-pro"` and `local_model = "gemma-4-e4b"`

#### Scenario: Explicit null clears an override

- **WHEN** an authorized client PUTs `{"external_model": null}` and the row previously had `external_model = "gemini-2.5-pro"`
- **THEN** the stored `external_model` is `NULL`, the response `external_model` is the global default, and `external_model` is absent from `overrides`

#### Scenario: Empty update is rejected

- **WHEN** an authorized client PUTs `{}`
- **THEN** the response is HTTP 422 and no config row is created or updated

#### Scenario: Update creates row when none exists

- **WHEN** an authorized client PUTs an LLM config for an org with no existing row
- **THEN** a new `org_llm_config` row is inserted and the response reflects the supplied values

#### Scenario: Routing threshold out of range

- **WHEN** an authorized client PUTs `{"routing_threshold": 1.5}`
- **THEN** the response is HTTP 422
