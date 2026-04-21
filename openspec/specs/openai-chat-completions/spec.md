## ADDED Requirements

### Requirement: Chat pipeline selects MemoryService instance by cache namespace
The system SHALL select the `MemoryService` instance corresponding to `request.state.cache_namespace` for every `/v1/chat/completions` request. A module-level pool (dict keyed by namespace string) SHALL lazily create and reuse `MemoryService` instances. The `"dejaq_default"` collection SHALL no longer be used as the default; all requests use their resolved namespace.

#### Scenario: First request to a namespace creates a new MemoryService
- **WHEN** the first request with `cache_namespace = "acme-corp__support"` arrives
- **THEN** a new `MemoryService("acme-corp__support")` is instantiated, added to the pool, and used for the cache check

#### Scenario: Subsequent requests to the same namespace reuse the instance
- **WHEN** a second request with `cache_namespace = "acme-corp__support"` arrives
- **THEN** the existing `MemoryService` instance from the pool is reused without re-initialization

#### Scenario: Different namespaces use different MemoryService instances
- **WHEN** two requests arrive with `cache_namespace = "acme-corp__support"` and `cache_namespace = "acme-corp/__default__"` respectively
- **THEN** each uses its own `MemoryService` instance pointing to its own ChromaDB collection

### Requirement: Namespace is forwarded to background generalize-and-store task
The system SHALL pass `cache_namespace` to the Celery task `generalize_and_store_task` (or the in-process fallback) so the background store operation writes to the correct ChromaDB collection.

#### Scenario: Background store uses request namespace
- **WHEN** a cache miss triggers a background generalize-and-store with `cache_namespace = "acme-corp__support"`
- **THEN** the Celery task stores the generalized response in `"acme-corp__support"`, not `"dejaq_default"`

### Requirement: Chat handler instruments latency and emits a log record

The system SHALL measure wall-clock latency from the start of the handler to just before returning the response, then call the `RequestLogger` to persist the record. This applies to both `POST /chat` (HTTP) and `WS /ws/chat` (WebSocket) handlers.

#### Scenario: HTTP handler records latency

- **WHEN** a `POST /chat` request completes (hit or miss)
- **THEN** `latency_ms` in the logged row equals the elapsed milliseconds measured inside the handler

#### Scenario: WebSocket handler records each turn

- **WHEN** a WebSocket message is processed and a response is sent
- **THEN** one row is inserted per turn with the correct latency for that turn only
