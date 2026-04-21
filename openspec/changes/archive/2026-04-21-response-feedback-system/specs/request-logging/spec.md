## MODIFIED Requirements

### Requirement: SQLite request log is initialized on startup
The system SHALL create (or open) a SQLite database at a configurable path (default: `dejaq_stats.db`) during FastAPI startup. The `requests` table SHALL be created if it does not exist, with columns: `id` (autoincrement PK), `ts` (ISO-8601 UTC text), `org` (text), `department` (text), `latency_ms` (integer), `cache_hit` (integer 0/1), `difficulty` (text, nullable), `model_used` (text, nullable), `response_id` (text, nullable). The system SHALL execute `ALTER TABLE requests ADD COLUMN response_id TEXT` guarded by existence check on startup so that existing databases gain the column without a migration script.

#### Scenario: Fresh startup creates the table
- **WHEN** the FastAPI application starts with no existing stats DB
- **THEN** `dejaq_stats.db` is created and the `requests` table exists with the correct schema including `response_id`

#### Scenario: Existing DB on restart does not error
- **WHEN** the FastAPI application starts and `dejaq_stats.db` already exists with the correct schema
- **THEN** startup completes without error and existing rows are preserved

#### Scenario: Existing DB without response_id column is migrated
- **WHEN** the FastAPI application starts and `dejaq_stats.db` exists but lacks the `response_id` column
- **THEN** the column is added and startup completes without error

### Requirement: Every chat request is logged after response is sent
The system SHALL log one row per completed chat request. The log write SHALL be fire-and-forget (non-blocking) via `asyncio.create_task` and SHALL NOT add measurable latency to the response path. On cache hits, `response_id` SHALL be set to `<namespace>:<doc_id>` of the matched entry. On cache misses where the response is stored to ChromaDB, `response_id` SHALL be set to `<namespace>:<doc_id>` returned by `store_interaction()`. On cache misses where the filter blocked storage, `response_id` SHALL be NULL. The system SHALL also return `response_id` in the `X-DejaQ-Response-Id` HTTP response header (both streaming and non-streaming); the header SHALL be omitted when `response_id` is NULL.

#### Scenario: Cache hit request is logged with response_id
- **WHEN** a request results in a cache hit
- **THEN** a row is inserted with `cache_hit=1`, `difficulty=NULL`, `model_used=NULL`, correct `latency_ms`, and `response_id` set to the matched ChromaDB document ID

#### Scenario: Easy cache miss request is logged
- **WHEN** a request results in a cache miss classified as `easy` and routed to the local Llama model, and the response passes the cache filter
- **THEN** a row is inserted with `cache_hit=0`, `difficulty='easy'`, `model_used` set to the local model name, and `response_id` set to the new document ID

#### Scenario: Hard cache miss request is logged
- **WHEN** a request results in a cache miss classified as `hard` and routed to an external API, and the response passes the cache filter
- **THEN** a row is inserted with `cache_hit=0`, `difficulty='hard'`, `model_used` set to the external model name, and `response_id` set to the new document ID

#### Scenario: Cache miss blocked by filter is logged without response_id
- **WHEN** a cache miss response is blocked from storage by the cache filter
- **THEN** a row is inserted with `cache_hit=0` and `response_id=NULL`

#### Scenario: Logger write failure does not surface to the user
- **WHEN** the SQLite write raises an exception (e.g., disk full)
- **THEN** the error is logged via the application logger and the user response is unaffected

### Requirement: Org and department default when not present on request
The system SHALL use `"default"` for both `org` and `department` fields when the incoming request does not carry org/department context (i.e., no API key auth resolving these values).

#### Scenario: Unauthenticated request gets default org/department
- **WHEN** a chat request arrives without org/department metadata
- **THEN** the logged row has `org='default'` and `department='default'`
