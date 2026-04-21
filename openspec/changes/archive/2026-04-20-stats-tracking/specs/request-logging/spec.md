## ADDED Requirements

### Requirement: SQLite request log is initialized on startup
The system SHALL create (or open) a SQLite database at a configurable path (default: `dejaq_stats.db`) during FastAPI startup. The `requests` table SHALL be created if it does not exist, with columns: `id` (autoincrement PK), `ts` (ISO-8601 UTC text), `org` (text), `department` (text), `latency_ms` (integer), `cache_hit` (integer 0/1), `difficulty` (text, nullable), `model_used` (text, nullable).

#### Scenario: Fresh startup creates the table
- **WHEN** the FastAPI application starts with no existing stats DB
- **THEN** `dejaq_stats.db` is created and the `requests` table exists with the correct schema

#### Scenario: Existing DB on restart does not error
- **WHEN** the FastAPI application starts and `dejaq_stats.db` already exists with the correct schema
- **THEN** startup completes without error and existing rows are preserved

### Requirement: Every chat request is logged after response is sent
The system SHALL log one row per completed chat request (both HTTP `POST /chat` and WebSocket `WS /ws/chat`). The log write SHALL be fire-and-forget (non-blocking) via `asyncio.create_task` and SHALL NOT add measurable latency to the response path.

#### Scenario: Cache hit request is logged
- **WHEN** a request results in a cache hit
- **THEN** a row is inserted with `cache_hit=1`, `difficulty=NULL`, `model_used=NULL`, and correct `latency_ms`

#### Scenario: Easy cache miss request is logged
- **WHEN** a request results in a cache miss classified as `easy` and routed to the local Llama model
- **THEN** a row is inserted with `cache_hit=0`, `difficulty='easy'`, and `model_used` set to the local model name

#### Scenario: Hard cache miss request is logged
- **WHEN** a request results in a cache miss classified as `hard` and routed to an external API
- **THEN** a row is inserted with `cache_hit=0`, `difficulty='hard'`, and `model_used` set to the external model name

#### Scenario: Logger write failure does not surface to the user
- **WHEN** the SQLite write raises an exception (e.g., disk full)
- **THEN** the error is logged via the application logger and the user response is unaffected

### Requirement: Org and department default when not present on request
The system SHALL use `"default"` for both `org` and `department` fields when the incoming request does not carry org/department context (i.e., no API key auth resolving these values).

#### Scenario: Unauthenticated request gets default org/department
- **WHEN** a chat request arrives without org/department metadata
- **THEN** the logged row has `org='default'` and `department='default'`
