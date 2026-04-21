## ADDED Requirements

### Requirement: Chat handler instruments latency and emits a log record
The system SHALL measure wall-clock latency from the start of the handler to just before returning the response, then call the `RequestLogger` to persist the record. This applies to both `POST /chat` (HTTP) and `WS /ws/chat` (WebSocket) handlers.

#### Scenario: HTTP handler records latency
- **WHEN** a `POST /chat` request completes (hit or miss)
- **THEN** `latency_ms` in the logged row equals the elapsed milliseconds measured inside the handler

#### Scenario: WebSocket handler records each turn
- **WHEN** a WebSocket message is processed and a response is sent
- **THEN** one row is inserted per turn with the correct latency for that turn only
