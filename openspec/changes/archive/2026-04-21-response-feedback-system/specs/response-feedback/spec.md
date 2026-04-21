## ADDED Requirements

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
