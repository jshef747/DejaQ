## ADDED Requirements

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
The system SHALL log a WARNING when a request arrives with a Bearer token that does not match any known DejaQ department key. The request SHALL still be served. No 401 or 403 SHALL be returned during this phase.

#### Scenario: Unknown key logged but request served
- **WHEN** a request arrives with a Bearer token not in the known key registry
- **THEN** a WARNING log entry is emitted containing the redacted key (first 8 chars + `...`) and the request proceeds to the pipeline

#### Scenario: No key provided — request served silently
- **WHEN** a request arrives with no API key
- **THEN** the request proceeds without a warning log (missing key is not an error in this phase)

### Requirement: Attach tenant context to request state
The system SHALL attach a `tenant_id` string to `request.state.tenant_id` on every `/v1/*` request. If the key maps to a known tenant, `tenant_id` SHALL be that tenant's identifier. If the key is unknown or absent, `tenant_id` SHALL be `"anonymous"`.

#### Scenario: Known key maps to tenant
- **WHEN** a request arrives with a recognized Bearer token
- **THEN** `request.state.tenant_id` is set to the corresponding tenant identifier

#### Scenario: Unknown or absent key maps to anonymous
- **WHEN** a request arrives with an unrecognized Bearer token or no token
- **THEN** `request.state.tenant_id` is set to `"anonymous"`
