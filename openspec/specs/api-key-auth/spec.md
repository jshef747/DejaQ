## MODIFIED Requirements

### Requirement: Extract Bearer token from Authorization header
The system SHALL read the `Authorization` HTTP header on every request to `/v1/*` endpoints. If the header is present and follows the `Bearer <token>` format, the token SHALL be extracted and attached to the request context for downstream use.

#### Scenario: Valid Bearer token extracted
- **WHEN** a request arrives with `Authorization: Bearer sk-abc123`
- **THEN** the token `sk-abc123` is available in `request.state.api_key` for downstream handlers

#### Scenario: Missing Authorization header allowed through
- **WHEN** a request arrives with no `Authorization` header
- **THEN** the request proceeds normally and `request.state.api_key` is `None`

#### Scenario: Malformed Authorization header allowed through
- **WHEN** a request arrives with `Authorization: Token xyz` (not Bearer format)
- **THEN** the request proceeds normally, `request.state.api_key` is `None`, and a WARNING is logged

### Requirement: Log unknown API keys
The system SHALL log a WARNING when a request arrives with a Bearer token that does not match any active key in the SQLite `api_keys` table. The request SHALL still be served. No 401 or 403 SHALL be returned.

#### Scenario: Unknown key logged but request served
- **WHEN** a request arrives with a Bearer token not present in the active key registry
- **THEN** a WARNING log entry is emitted containing the redacted key (first 8 chars + `...`) and the request proceeds to the pipeline

#### Scenario: No key provided — request served silently
- **WHEN** a request arrives with no API key
- **THEN** the request proceeds without a warning log

### Requirement: Attach tenant context to request state
The system SHALL attach an `org_slug` string to `request.state.org_slug` on every `/v1/*` request by resolving the Bearer token against the SQLite `api_keys` table (via in-process cache). If the key maps to a known org, `org_slug` SHALL be that org's slug. If the key is unknown or absent, `org_slug` SHALL be `"anonymous"`.

#### Scenario: Known key maps to org slug
- **WHEN** a request arrives with a recognized Bearer token
- **THEN** `request.state.org_slug` is set to the corresponding org's slug (e.g. `"acme-corp"`)

#### Scenario: Unknown or absent key maps to anonymous
- **WHEN** a request arrives with an unrecognized Bearer token or no token
- **THEN** `request.state.org_slug` is set to `"anonymous"`

### Requirement: Resolve cache namespace from org and optional department header
The system SHALL read the `X-DejaQ-Department` request header (value: department slug). If present and the slug is a valid department under the resolved org, the system SHALL set `request.state.cache_namespace` to that department's `cache_namespace` (e.g. `"acme-corp__customer-support"`). If the header is absent or the slug is not found, the system SHALL fall back to `"{org_slug}/__default__"`.

#### Scenario: Department header present and valid
- **WHEN** a request arrives with `Authorization: Bearer <acme-key>` and `X-DejaQ-Department: customer-support`
- **THEN** `request.state.cache_namespace` is set to `"acme-corp__customer-support"`

#### Scenario: Department header absent — fall back to default namespace
- **WHEN** a request arrives with `Authorization: Bearer <acme-key>` but no `X-DejaQ-Department` header
- **THEN** `request.state.cache_namespace` is set to `"acme-corp/__default__"`

#### Scenario: Department slug not found under org — fall back to default namespace
- **WHEN** a request arrives with `X-DejaQ-Department: nonexistent-dept` for a valid org
- **THEN** a WARNING is logged and `request.state.cache_namespace` falls back to `"{org_slug}/__default__"`

#### Scenario: Anonymous request gets anonymous default namespace
- **WHEN** a request arrives with no API key
- **THEN** `request.state.cache_namespace` is set to `"anonymous/__default__"`

### Requirement: Key registry is loaded from SQLite with in-process cache
The system SHALL NOT query SQLite on every request. Instead, the middleware SHALL maintain an in-process dict mapping token → (org_slug, org_id) loaded from `api_keys` (WHERE revoked_at IS NULL). The cache SHALL be refreshed at most once per `DEJAQ_KEY_CACHE_TTL` seconds (default: 60). Department slug → cache_namespace mapping SHALL be cached with the same TTL.

#### Scenario: Cache populated on first request
- **WHEN** the first `/v1/*` request arrives after server start
- **THEN** the middleware queries SQLite to populate the key cache and department cache before resolving the request

#### Scenario: Cache refreshed after TTL
- **WHEN** more than `DEJAQ_KEY_CACHE_TTL` seconds have elapsed since the last cache refresh
- **THEN** the next request triggers a synchronous SQLite refresh before resolving

#### Scenario: Revoked key becomes inactive within one TTL window
- **WHEN** a key is revoked via CLI and up to `DEJAQ_KEY_CACHE_TTL` seconds have not yet elapsed
- **THEN** the key MAY still be accepted (cache not yet stale); after the TTL expires the key is rejected
