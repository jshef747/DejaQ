## ADDED Requirements

### Requirement: List feedback endpoint

The system SHALL expose `GET /admin/v1/feedback` for the management API, returning recorded feedback rows from `feedback_log`. The endpoint SHALL accept optional query parameters `org`, `department`, `response_id`, `limit` (default 100, max 500), and `offset` (default 0). Filters SHALL combine with AND. Unknown org or department filter values SHALL return HTTP 200 with an empty result set, not 404. The response SHALL be HTTP 200 with `{items: [{id, ts, response_id, org, department, rating, comment}], total: <int>, limit, offset}` where `total` counts rows matching the filters before pagination. Results SHALL be ordered by `ts DESC, id DESC` for deterministic pagination. Authorization SHALL follow the management-api admin-token rule (`Authorization: Bearer <DEJAQ_ADMIN_TOKEN>`); requests without a valid admin token SHALL receive HTTP 401, and unconfigured admin token SHALL produce HTTP 503.

#### Scenario: List feedback unfiltered

- **WHEN** an authorized admin client calls `GET /admin/v1/feedback`
- **THEN** the response contains the most recent feedback rows up to `limit` (default 100), ordered by `ts` descending and then `id` descending

#### Scenario: List feedback filtered by org and department

- **WHEN** an authorized admin client calls `GET /admin/v1/feedback?org=acme&department=eng`
- **THEN** only rows where `org='acme'` AND `department='eng'` are returned

#### Scenario: List feedback with unknown org filter

- **WHEN** an authorized admin client calls `GET /admin/v1/feedback?org=missing`
- **THEN** the response is HTTP 200 with `{"items": [], "total": 0, "limit": 100, "offset": 0}`

#### Scenario: List feedback filtered by response_id

- **WHEN** an authorized admin client calls `GET /admin/v1/feedback?response_id=ns:doc-123`
- **THEN** only rows for that exact `response_id` are returned

#### Scenario: List feedback enforces max limit

- **WHEN** an authorized admin client calls `GET /admin/v1/feedback?limit=10000`
- **THEN** the response is HTTP 422

#### Scenario: List feedback without admin token

- **WHEN** a client calls `GET /admin/v1/feedback` with no `Authorization` header
- **THEN** the response is HTTP 401

### Requirement: Submit feedback endpoint accepts admin token with explicit attribution

The system SHALL expose `POST /admin/v1/feedback` accepting `{org, department?, response_id, rating, comment?}` and applying the same score-update semantics as `POST /v1/feedback` (positive +1.0, first negative deletes, subsequent negative -2.0, unknown response_id → 404). The `department` field SHALL default to `"default"` when omitted. This admin endpoint SHALL authenticate via `DEJAQ_ADMIN_TOKEN` rather than an org API key, allowing the dashboard to submit feedback on behalf of a specific org/department. The existing `POST /v1/feedback` endpoint SHALL remain unchanged in behavior and auth.

The system SHALL validate that the supplied org and department exist and that the target `response_id` belongs to the supplied namespace. Unknown org or department SHALL return HTTP 404. A `response_id` that exists but belongs to a different org/department namespace SHALL return HTTP 422.

#### Scenario: Admin submits positive feedback

- **WHEN** an authorized admin client POSTs `{"org": "acme", "department": "eng", "response_id": "<id>", "rating": "positive"}` to `/admin/v1/feedback`
- **THEN** the entry's score is incremented by 1.0 and the response is HTTP 200 with `{"status": "ok", "new_score": <float>}`

#### Scenario: Admin feedback defaults department

- **WHEN** an authorized admin client POSTs `{"org": "acme", "response_id": "<id>", "rating": "positive"}` to `/admin/v1/feedback`
- **THEN** the request is attributed to department `"default"`

#### Scenario: Admin feedback namespace mismatch

- **WHEN** an authorized admin client POSTs feedback for `org="acme"` but the `response_id` belongs to another org namespace
- **THEN** the response is HTTP 422

#### Scenario: Admin endpoint requires admin token

- **WHEN** a client POSTs to `/admin/v1/feedback` with an org API key (not the admin token)
- **THEN** the response is HTTP 401
