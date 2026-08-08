## ADDED Requirements

### Requirement: Thumbs-down triggers server-verified escalation to next serving tier

When a client submits negative feedback with a valid `interaction_id` and the exact original request-message snapshot, the system SHALL re-run the request at the next serving tier and return the result inline in the feedback response.

The system SHALL NOT trust client-supplied `tier` to choose escalation. It SHALL use the stored `served_tier` from the response identity record.

Escalation order:

- stored `served_tier: "cache"` → escalate to local LLM
- stored `served_tier: "local"` → escalate to external LLM
- stored `served_tier: "external"` → no further escalation

The feedback response SHALL use `status` for feedback/cache mutation and `escalation_status` for the escalation result. `status` SHALL NOT be set to `no_further_escalation` or `no_credential`.

When escalation returns an answer, the system SHALL evaluate the original query with the normal cache policy. If the answer is cacheable, the system SHALL store the escalated answer in the interaction's cache namespace and include the cache `response_id` on the escalated response.

The system SHALL NOT store an escalated answer whose generator reported truncation (the local backend's `done_reason` or the provider's normalized `finish_reason` is `length`), at either tier. Such an answer is still returned to the caller, with no cache `response_id`.

Valid escalation statuses are:

- `answered`
- `not_requested`
- `no_further_escalation`
- `no_credential`
- `provider_error`
- `timeout`
- `message_mismatch`
- `already_escalated`

#### Scenario: Thumbs-down on cache hit escalates to local LLM

- **WHEN** a client POSTs negative feedback with a valid cache-hit `interaction_id` and matching `messages`
- **THEN** the system applies cache deletion/score behavior, calls the local LLM with the supplied messages, creates a new interaction record for the escalated answer, and returns HTTP 200 with `{"status": "deleted"|"ok", "escalated_response": {"content": "<local LLM answer>", "tier": "local", "interaction_id": "<new-id>", "response_id": "<optional-cache-id>"}, "escalation_status": "answered"}`

#### Scenario: Thumbs-down on local LLM escalates to external LLM

- **WHEN** a client POSTs negative feedback with a valid local-tier `interaction_id` and matching `messages`
- **THEN** the system calls the external LLM using server-side org configuration and credentials, creates a new interaction record for the escalated answer, logs the escalation request, and returns HTTP 200 with `{"status": "ok", "escalated_response": {"content": "<external LLM answer>", "tier": "external", "interaction_id": "<new-id>", "response_id": "<optional-cache-id>"}, "escalation_status": "answered"}`

#### Scenario: Cacheable escalated answer records cache response id

- **WHEN** escalation returns an answer and the original query passes normal cache filtering
- **THEN** the system stores the answer in the authenticated department cache namespace, registers the child interaction with the cache `response_id`, and returns that `response_id` in `escalated_response`

#### Scenario: Non-cacheable escalated answer still returns

- **WHEN** escalation returns an answer but the original query does not pass normal cache filtering
- **THEN** the system does not store a cache entry, registers the child interaction with no cache `response_id`, and still returns the escalated answer with `escalation_status="answered"`

#### Scenario: Thumbs-down on external LLM returns no further escalation

- **WHEN** a client POSTs negative feedback with a valid external-tier `interaction_id` and matching `messages`
- **THEN** the system does not call another LLM and returns HTTP 200 with `{"status": "ok", "escalated_response": null, "escalation_status": "no_further_escalation"}`

#### Scenario: Thumbs-down without interaction_id does not escalate

- **WHEN** a client POSTs `{"response_id": "<id>", "rating": "negative"}` without `interaction_id`
- **THEN** the system applies legacy cache feedback behavior and returns a legacy response without `escalated_response`

#### Scenario: Missing messages skips escalation

- **WHEN** a client POSTs `{"interaction_id": "<id>", "rating": "negative"}` without `messages`
- **THEN** the system logs feedback, applies any cache-backed score behavior, does not call an LLM, and returns HTTP 200 with `{"status": "ok"|"deleted", "escalated_response": null, "escalation_status": "not_requested"}`

#### Scenario: Message snapshot mismatch blocks escalation

- **WHEN** a client POSTs negative feedback with a valid `interaction_id` but `messages` whose hash does not match the stored interaction hash
- **THEN** the system does not call an LLM and returns HTTP 200 with `{"status": "ok"|"deleted", "escalated_response": null, "escalation_status": "message_mismatch"}`

#### Scenario: Forged client tier cannot force external escalation

- **WHEN** a client POSTs feedback for a cache-tier interaction and includes `tier: "local"` in the request body
- **THEN** the system ignores the client tier, uses stored `served_tier: "cache"`, and escalates only to the local LLM

#### Scenario: Escalation to external LLM fails due to missing org credential

- **WHEN** a client POSTs negative feedback for a local-tier interaction and the authenticated org has no credential for the configured external provider
- **THEN** the system does not expose credential details and returns HTTP 200 with `{"status": "ok", "escalated_response": null, "escalation_status": "no_credential"}`

#### Scenario: External provider failure is graceful

- **WHEN** external escalation fails due to timeout or provider error
- **THEN** the system logs the failure and returns HTTP 200 with `{"status": "ok", "escalated_response": null, "escalation_status": "timeout"|"provider_error"}`

#### Scenario: Duplicate thumbs-down does not trigger duplicate generation

- **WHEN** the same interaction receives a second negative feedback request after escalation was already attempted
- **THEN** the system does not call an LLM again and returns HTTP 200 with `{"status": "ok"|"deleted", "escalated_response": null, "escalation_status": "already_escalated"}`

### Requirement: Chat completions response includes serving tier and interaction headers

The system SHALL include `X-DejaQ-Interaction-Id` and `X-DejaQ-Tier` on every `POST /v1/chat/completions` response that returns a cache, local, or external answer. Valid tier values are `cache`, `local`, and `external`.

The system SHALL continue to include `X-DejaQ-Response-Id` only when a cache document id exists. Clients SHALL use `interaction_id` for feedback escalation and `response_id` only for cache score attribution.

#### Scenario: Cache hit response includes headers

- **WHEN** a request is answered from ChromaDB cache
- **THEN** the response includes `X-DejaQ-Interaction-Id`, `X-DejaQ-Tier: cache`, and `X-DejaQ-Response-Id`

#### Scenario: Local LLM response includes headers

- **WHEN** a request is answered by the local model
- **THEN** the response includes `X-DejaQ-Interaction-Id` and `X-DejaQ-Tier: local`

#### Scenario: External LLM response includes headers

- **WHEN** a request is routed to an external provider and succeeds
- **THEN** the response includes `X-DejaQ-Interaction-Id` and `X-DejaQ-Tier: external`

#### Scenario: Streaming answer response includes headers

- **WHEN** a chat answer response is streamed
- **THEN** the streaming response includes the same `X-DejaQ-Interaction-Id` and `X-DejaQ-Tier` headers as the non-streaming path
