# response-feedback Specification

## Purpose
Define public and administrative feedback behavior for cached responses, including score updates, logging, attribution, and management listing.

## Requirements

### Requirement: Submit feedback on a cached response

The system SHALL expose a `POST /v1/feedback` endpoint that accepts a `response_id` (opaque string formatted as `<namespace>:<doc_id>`), a `rating` (`positive` or `negative`), and an optional free-text `comment`. The endpoint SHALL require a valid Bearer API key (existing middleware). The endpoint SHALL return HTTP 422 if `response_id` does not contain `:`. On positive feedback, the system SHALL increment `score` by 1.0. On **first** negative feedback (i.e., `negative_count` is 0), the system SHALL immediately delete the entry from ChromaDB and return `{"status": "deleted"}`. On subsequent negative feedback (`negative_count` ≥ 1), the system SHALL decrement `score` by 2.0 and increment `negative_count`. If the `response_id` does not exist in ChromaDB, the system SHALL return HTTP 404.

#### Scenario: Positive feedback on a cached entry

- **WHEN** a client POSTs `{"response_id": "<id>", "rating": "positive"}` with a valid API key
- **THEN** the system increments the entry's `score` by 1.0 and returns HTTP 200 with `{"status": "ok", "new_score": <float>}`

#### Scenario: First negative feedback on a cached entry

- **WHEN** a client POSTs `{"response_id": "<id>", "rating": "negative"}` and the entry's `negative_count` is 0
- **THEN** the system immediately deletes the entry from ChromaDB and returns HTTP 200 with `{"status": "deleted"}`

#### Scenario: Subsequent negative feedback on a cached entry

- **WHEN** a client POSTs `{"response_id": "<id>", "rating": "negative"}` and the entry's `negative_count` is ≥ 1
- **THEN** the system decrements `score` by 2.0, increments `negative_count`, and returns HTTP 200 with `{"status": "ok", "new_score": <float>}`

#### Scenario: Feedback on unknown response_id

- **WHEN** a client POSTs feedback with a `response_id` that does not exist in ChromaDB
- **THEN** the system returns HTTP 404 with `{"detail": "response_id not found"}`

#### Scenario: Feedback with invalid rating value

- **WHEN** a client POSTs `{"response_id": "<id>", "rating": "neutral"}`
- **THEN** the system returns HTTP 422 (Unprocessable Entity)

#### Scenario: Feedback without API key

- **WHEN** a client POSTs feedback with no `Authorization` header
- **THEN** the system returns HTTP 401

### Requirement: Feedback submission is logged with org and department attribution

The system SHALL write one row to `feedback_log` in `dejaq_stats.db` for every feedback submission, recording `ts`, `response_id`, `org`, `department`, `rating`, and optional `comment`. The write SHALL be fire-and-forget and SHALL NOT block the HTTP response. On immediate-delete (first negative), the row SHALL still be written before the entry is deleted.

#### Scenario: Positive feedback is logged

- **WHEN** a client POSTs positive feedback with a valid API key resolving to org `acme` and department `eng`
- **THEN** a row is inserted into `feedback_log` with `rating='positive'`, `org='acme'`, `department='eng'`

#### Scenario: First negative feedback is logged before deletion

- **WHEN** a client POSTs the first negative feedback on an entry
- **THEN** a row is inserted into `feedback_log` with `rating='negative'` and the entry is deleted from ChromaDB

#### Scenario: Log write failure does not affect the response

- **WHEN** the SQLite write to `feedback_log` raises an exception
- **THEN** the error is logged via the application logger and the HTTP response is unaffected

### Requirement: New cached entries initialise with score and hit_count

The system SHALL write `score: 0.0` and `hit_count: 0` into the ChromaDB metadata for every newly stored document.

#### Scenario: Document stored on cache miss

- **WHEN** the background generalize-and-store task writes a new document to ChromaDB
- **THEN** the document's metadata contains `score: 0.0` and `hit_count: 0`

### Requirement: Cache hit increments hit_count

The system SHALL increment the `hit_count` metadata field of the matched ChromaDB document each time it is returned as a cache hit.

#### Scenario: Repeated cache hit on same entry

- **WHEN** the same query is answered from cache twice
- **THEN** the matched document's `hit_count` is 2

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

The system SHALL expose `POST /admin/v1/feedback` accepting `{org, department?, response_id, rating, comment?}` and applying the same score-update semantics as `POST /v1/feedback` (positive +1.0, first negative deletes, subsequent negative -2.0, unknown response_id -> 404). The `department` field SHALL default to `"default"` when omitted. This admin endpoint SHALL authenticate via `DEJAQ_ADMIN_TOKEN` rather than an org API key, allowing the dashboard to submit feedback on behalf of a specific org/department. The existing `POST /v1/feedback` endpoint SHALL remain unchanged in behavior and auth.

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
