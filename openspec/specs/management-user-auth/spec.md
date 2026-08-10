## ADDED Requirements

### Requirement: Management API validates Supabase JWTs
The system SHALL require every HTTP request to `/admin/v1/*` to include `Authorization: Bearer <token>` where `<token>` is a Supabase-issued access JWT. The system SHALL use the official Supabase Python SDK request-time Auth user lookup, specifically `supabase.auth.get_user(<access_token>)` or the SDK's current equivalent, to validate the access token and retrieve the Supabase user before running route handlers. Requests with a missing, malformed, expired, invalid, revoked, wrong-project, or unverifiable token SHALL return HTTP 401 and SHALL NOT run the requested management action.

The system SHALL NOT implement manual JWT signature verification, JWKS fetching, signing-key caching, or JWT-secret fallback logic in DejaQ application code. Supabase signing-key rotation SHALL be handled through the official Supabase SDK/Auth API behavior. The management API MUST fail closed with HTTP 503 if the Supabase SDK cannot be configured from the required project settings.

Runtime Supabase SDK/Auth failures, including network errors, timeouts, unusable SDK responses, and server-side project configuration mismatches, SHALL fail closed with HTTP 503. Failed auth responses and logs SHALL NOT include token contents, raw authorization headers, decoded JWT claims, or raw Supabase SDK error payloads.

#### Scenario: Valid Supabase JWT accepted
- **WHEN** a client calls `GET /admin/v1/whoami` with a valid Supabase access JWT
- **THEN** the system validates the token through the Supabase Python SDK
- **THEN** the system authorizes the request and exposes the Supabase user id and email to the handler context

#### Scenario: Missing bearer token rejected
- **WHEN** a client calls any `/admin/v1/*` endpoint without an `Authorization` header
- **THEN** the system returns HTTP 401
- **THEN** the route handler is not executed

#### Scenario: Expired JWT rejected
- **WHEN** a client calls any `/admin/v1/*` endpoint with an expired Supabase access JWT
- **THEN** the system returns HTTP 401
- **THEN** no management data is returned or mutated

#### Scenario: Supabase SDK runtime failure returns unavailable
- **WHEN** Supabase Auth validation cannot complete because of an SDK transport failure, timeout, or unusable SDK response
- **THEN** the system returns HTTP 503
- **THEN** the route handler is not executed
- **THEN** no local user is created or updated

#### Scenario: Supabase auth not configured
- **WHEN** the server has no usable Supabase SDK project configuration and a client calls any `/admin/v1/*` endpoint
- **THEN** the system returns HTTP 503
- **THEN** a startup or request-time warning is logged without token contents

#### Scenario: DejaQ does not manually verify JWT signing keys
- **WHEN** a Supabase access token is submitted to `/admin/v1/whoami`
- **THEN** DejaQ validates it through the official Supabase Python SDK
- **THEN** DejaQ does not fetch JWKS, cache signing keys, or verify the JWT signature in local application code

#### Scenario: DejaQ does not trust local session data for server auth
- **WHEN** a Supabase access token is submitted to any `/admin/v1/*` endpoint
- **THEN** DejaQ validates it through SDK request-time user lookup
- **THEN** DejaQ does not use SDK session-cache helpers as the source of server-side authentication truth

### Requirement: Local users map to Supabase identities
The system SHALL store management users in the SQLite database with a unique Supabase user id and an email address. The Supabase user id SHALL be populated from the verified Supabase user object returned by the SDK. The email SHALL be populated from the verified Supabase user object returned by the SDK. DejaQ application code SHALL NOT decode JWT claims to create or update local management users. Repeated requests from the same Supabase user SHALL resolve to the same local user row.

#### Scenario: First request creates local user
- **WHEN** a valid Supabase JWT has subject `user-123` and email `demo@dejaq.local`
- **THEN** the system creates or finds a local user row with `supabase_user_id = "user-123"` and `email = "demo@dejaq.local"`

#### Scenario: Existing user reused
- **WHEN** a local user already exists for Supabase subject `user-123`
- **THEN** subsequent management requests from that subject use the existing local user row

#### Scenario: Email change is reflected locally
- **WHEN** a valid Supabase JWT for an existing user contains a different email than the stored row
- **THEN** the system updates the local user's email before returning request context

### Requirement: Users can belong to multiple organizations
The system SHALL store a many-to-many relationship between local users and organizations. A user SHALL be allowed to belong to zero, one, or many organizations. An organization SHALL be allowed to have zero, one, or many users. Duplicate membership rows for the same `(user_id, org_id)` SHALL be rejected.

Membership rows SHALL cascade when the linked local user or organization is deleted.

#### Scenario: User belongs to two orgs
- **WHEN** a local user has membership rows for orgs `acme` and `globex`
- **THEN** the user's management auth context includes both orgs as accessible

#### Scenario: Duplicate membership rejected
- **WHEN** setup or an admin operation attempts to create the same user-org membership twice
- **THEN** the database preserves exactly one membership row for that user and org

#### Scenario: Org deletion removes memberships
- **WHEN** an organization is deleted
- **THEN** all user-org membership rows for that organization are deleted by cascade

### Requirement: Management request context includes actor identity and org access
The system SHALL attach a typed management auth context to every authorized management request. For Supabase-authenticated HTTP requests, the context SHALL include actor type `user`, local user id, Supabase user id, email, and accessible organization ids/slugs. For trusted CLI operations, the context SHALL include actor type `system` and full organization access.

A system actor SHALL only be constructed by trusted in-process CLI/service code. HTTP management requests SHALL always resolve to a user actor and SHALL NOT allow headers, JWT claims, query parameters, or request bodies to select or impersonate the system actor.

#### Scenario: HTTP user context includes memberships
- **WHEN** a Supabase-authenticated user belongs to `acme`
- **THEN** admin handlers receive a management auth context with actor type `user`, the user's email, and `acme` in the accessible org list

#### Scenario: User with no memberships has empty org access
- **WHEN** a valid Supabase-authenticated user has no user-org memberships
- **THEN** the request is authenticated
- **THEN** org-scoped management endpoints only return empty collections or authorization errors as defined by the management API spec

#### Scenario: CLI context has full access
- **WHEN** `dejaq-admin` invokes shared admin services
- **THEN** it passes a system management auth context that can list and mutate every org without a Supabase JWT

#### Scenario: HTTP cannot request system actor
- **WHEN** a client calls any `/admin/v1/*` endpoint with a valid Supabase JWT and a header, claim, query parameter, or request body field that attempts to select `actor_type = "system"`
- **THEN** the request context still has actor type `user`
- **THEN** organization access is limited to the user's memberships

### Requirement: Supabase service-role credentials are restricted to setup paths
The system SHALL NOT use Supabase service-role credentials in the request-time HTTP management auth dependency. Service-role credentials SHALL only be used by explicit setup, demo seed, or admin provisioning code paths.

#### Scenario: HTTP auth uses non-service-role SDK configuration
- **WHEN** a client calls any `/admin/v1/*` endpoint with a Supabase access token
- **THEN** the request-time management auth dependency validates the token without using Supabase service-role credentials

#### Scenario: Demo seed may use service role
- **WHEN** the demo seed creates or updates the Supabase Auth demo user
- **THEN** that explicit setup path may use configured Supabase service-role credentials

### Requirement: Gateway API authentication remains unchanged
The system SHALL NOT require Supabase JWTs for `/v1/chat/completions` or `/v1/feedback`. Gateway endpoints SHALL continue to use org API keys and optional department headers exactly as before. The org API-key middleware SHALL continue to skip `/admin/v1/*` before attempting gateway key lookup.

#### Scenario: Chat completion still uses org API key
- **WHEN** a client calls `POST /v1/chat/completions` with a DejaQ org API key
- **THEN** the request is authenticated and scoped using the existing gateway API-key middleware
- **THEN** no Supabase JWT is required

#### Scenario: Supabase token is not treated as gateway key on admin routes
- **WHEN** a client calls `/admin/v1/whoami` with a valid Supabase bearer token
- **THEN** the org API-key middleware is not invoked for token lookup
- **THEN** no unknown org API-key warning is logged for that token

#### Scenario: Supabase token sent to gateway uses gateway contract only
- **WHEN** a client calls `POST /v1/chat/completions` or `POST /v1/feedback` with a Supabase access JWT as the bearer token
- **THEN** the gateway treats the token only under the existing org API-key contract
- **THEN** the gateway does not invoke Supabase validation or management membership lookup
