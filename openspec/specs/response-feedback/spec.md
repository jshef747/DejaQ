## MODIFIED Requirements

### Requirement: Submit feedback on a cached response

The system SHALL expose a `POST /v1/feedback` endpoint that accepts a `rating` (`positive` or `negative`), an optional free-text `comment`, and at least one feedback target:

- `response_id`: legacy cache document identifier formatted as `<namespace>:<doc_id>`
- `interaction_id`: server-issued identifier for a chat response that returned an answer

The endpoint SHALL require a valid org Bearer API key. Missing, malformed, unknown, or revoked keys SHALL return HTTP 401 for this endpoint.

When `response_id` is supplied, the system SHALL validate that the namespace belongs to the authenticated org and department. A `response_id` without `:` SHALL return HTTP 422. A namespace mismatch SHALL return HTTP 422. An unknown cache-backed `response_id` SHALL return HTTP 404.

Legacy requests that send only `response_id`, `rating`, and optional `comment` SHALL preserve the existing response shapes:

- positive feedback increments `score` by 1.0 and returns `{"status": "ok", "new_score": <float>}`
- first negative feedback deletes the entry from ChromaDB and returns `{"status": "deleted"}`
- subsequent negative feedback decrements `score` by 2.0, increments `negative_count`, and returns `{"status": "ok", "new_score": <float>}`

When `interaction_id` is supplied, the system SHALL look up the corresponding response identity record, verify it belongs to the authenticated org and department, log the feedback, and use that trusted record for escalation decisions. If the interaction record includes a cache `response_id`, the system SHALL apply the cache score/deletion behavior to that cache entry. If the interaction record has no cache `response_id`, the system SHALL NOT attempt ChromaDB score mutation and SHALL still allow negative-feedback escalation.

Escalation SHALL only be attempted when `rating` is `"negative"`, `interaction_id` is valid, and `messages` is provided and matches the stored request-message hash as defined in the `feedback-escalation` spec.

When escalation returns a cacheable answer, `escalated_response` SHALL include a `response_id` for the newly stored cache document. Clients MAY use this `response_id` for later score attribution on the escalated answer.

#### Scenario: Legacy positive feedback on a cached entry

- **WHEN** a client POSTs `{"response_id": "<namespace>:<doc_id>", "rating": "positive"}` with a valid org API key
- **THEN** the system validates namespace ownership, increments the entry's `score` by 1.0, and returns HTTP 200 with `{"status": "ok", "new_score": <float>}`

#### Scenario: Legacy first negative feedback on a cached entry

- **WHEN** a client POSTs `{"response_id": "<namespace>:<doc_id>", "rating": "negative"}` with a valid org API key and the entry's `negative_count` is 0
- **THEN** the system validates namespace ownership, deletes the entry from ChromaDB, and returns HTTP 200 with `{"status": "deleted"}`

#### Scenario: Interaction feedback for non-cache local answer

- **WHEN** a client POSTs `{"interaction_id": "<id>", "rating": "negative", "messages": [...]}` for an interaction originally served by the local LLM with no cache `response_id`
- **THEN** the system logs the feedback, skips ChromaDB score mutation, performs server-verified escalation, and returns HTTP 200 with `{"status": "ok", "escalated_response": {"content": "<answer>", "tier": "external", "interaction_id": "<new-id>", "response_id": "<optional-cache-id>"}, "escalation_status": "answered"}`

#### Scenario: Interaction feedback for cache hit deletes cache and escalates

- **WHEN** a client POSTs `{"interaction_id": "<id>", "rating": "negative", "messages": [...]}` for an interaction originally served from cache and the cache entry's `negative_count` is 0
- **THEN** the system deletes the cache entry, escalates to local LLM, and returns HTTP 200 with `{"status": "deleted", "escalated_response": {"content": "<answer>", "tier": "local", "interaction_id": "<new-id>", "response_id": "<optional-cache-id>"}, "escalation_status": "answered"}`

#### Scenario: Feedback target belongs to another namespace

- **WHEN** a client POSTs feedback for a `response_id` whose namespace does not belong to the authenticated org and department
- **THEN** the system returns HTTP 422 and does not mutate ChromaDB

#### Scenario: Feedback with invalid rating value

- **WHEN** a client POSTs `{"response_id": "<id>", "rating": "neutral"}`
- **THEN** the system returns HTTP 422

#### Scenario: Feedback without valid API key

- **WHEN** a client POSTs feedback with no valid org Bearer API key
- **THEN** the system returns HTTP 401

### Requirement: Feedback submission is logged with org, department, and interaction attribution

The system SHALL write one row to `feedback_log` for every accepted feedback submission, recording `ts`, `org`, `department`, `rating`, optional `comment`, optional cache `response_id`, and optional `interaction_id`. The write SHALL NOT expose message content. On immediate-delete (first negative), the row SHALL still be written for the feedback target.

#### Scenario: Interaction feedback is logged

- **WHEN** a client POSTs negative feedback with a valid `interaction_id`
- **THEN** a row is inserted into `feedback_log` with the authenticated org/department, rating, and interaction id

#### Scenario: Log write failure does not affect the response

- **WHEN** the SQLite write to `feedback_log` raises an exception
- **THEN** the error is logged via the application logger and the HTTP response is unaffected
