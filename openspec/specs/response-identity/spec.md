## ADDED Requirements

### Requirement: Served chat answers are registered with a server-side interaction identity

The system SHALL create a response identity record for every `/v1/chat/completions` response that returns a cache, local, or external answer before returning the HTTP response. This registration means DejaQ served an answer; it does not mean the user liked the answer or that no later negative feedback will be submitted. The record SHALL be keyed by `interaction_id`, a server-generated opaque string.

Each record SHALL contain:

- `interaction_id`
- authenticated `org_id` and `org_slug`
- department slug and cache namespace
- `served_tier` (`cache`, `local`, or `external`)
- optional cache `response_id`
- deterministic hash of the exact OpenAI-compatible `messages` array used to produce the answer
- creation timestamp
- escalation-attempt metadata

The system SHALL NOT store full message content in the response identity record.

#### Scenario: Cache hit creates response identity

- **WHEN** a chat request is answered from cache
- **THEN** the system stores a response identity record with `served_tier="cache"` and the matched cache `response_id`

#### Scenario: Local answer creates response identity without cache response id

- **WHEN** a chat request is answered by the local LLM and no cache document exists yet
- **THEN** the system stores a response identity record with `served_tier="local"` and `response_id=NULL`

#### Scenario: External answer creates response identity without trusting client input

- **WHEN** a chat request is answered by an external provider
- **THEN** the system stores a response identity record with `served_tier="external"` from server routing state

#### Scenario: Immediate feedback can find the interaction

- **WHEN** the chat response has already been returned to the client
- **THEN** a subsequent feedback request using `X-DejaQ-Interaction-Id` can look up the interaction without racing background cache storage

### Requirement: Response identity enforces tenant and department ownership

The system SHALL use the authenticated org and department context on feedback requests to verify ownership of the `interaction_id`. A feedback request for an interaction owned by another org or department SHALL fail without mutating ChromaDB and without calling an LLM.

#### Scenario: Cross-org interaction feedback is rejected

- **WHEN** an API key for org `acme` submits feedback for an interaction owned by org `globex`
- **THEN** the system returns an authorization or validation error and does not call an LLM

#### Scenario: Cross-department interaction feedback is rejected

- **WHEN** an API key for department `support` submits feedback for an interaction owned by department `sales`
- **THEN** the system returns an authorization or validation error and does not call an LLM

### Requirement: Message hash validates client-supplied replay content

The system SHALL compute a deterministic hash of the exact OpenAI-compatible `messages` array used for the original chat answer. When feedback supplies `messages` for escalation, the system SHALL compute the same hash format and compare it to the stored interaction hash.

The hash SHALL be stable across JSON key ordering and SHALL preserve message order. The hash SHALL change when role, content, or message order changes.

#### Scenario: Exact message snapshot matches

- **WHEN** feedback includes the same message array used for the original chat request
- **THEN** the computed hash matches and escalation may proceed

#### Scenario: Current chat history differs from original snapshot

- **WHEN** feedback includes later conversation turns that were not part of the rejected answer's original request
- **THEN** the computed hash differs and escalation is blocked with `message_mismatch`
