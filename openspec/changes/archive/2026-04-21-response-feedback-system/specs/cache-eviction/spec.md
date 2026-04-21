## ADDED Requirements

### Requirement: Periodic eviction of low-score entries
The system SHALL run a Celery beat task (`evict_low_score_entries`) every 30 minutes that queries ChromaDB for all documents whose `score` metadata is below the configured floor (default −5.0, overridable via `DEJAQ_EVICTION_FLOOR` env var) and deletes them.

#### Scenario: Entry score drops below floor
- **WHEN** an entry's score is −6.0 (below the floor of −5.0)
- **THEN** the next eviction task run deletes that document from ChromaDB

#### Scenario: Entry score at or above floor is retained
- **WHEN** an entry's score is −4.9
- **THEN** the eviction task does not delete it

#### Scenario: Eviction task with empty collection
- **WHEN** no documents exist in ChromaDB
- **THEN** the eviction task completes without error

#### Scenario: Eviction count logged
- **WHEN** the eviction task deletes one or more documents
- **THEN** the task logs the count of deleted documents at INFO level

### Requirement: Configurable eviction floor
The system SHALL read the eviction floor from the `DEJAQ_EVICTION_FLOOR` environment variable as a float. If the variable is absent or non-numeric, the system SHALL default to −5.0.

#### Scenario: Custom floor via environment variable
- **WHEN** `DEJAQ_EVICTION_FLOOR=-3.0` is set and an entry has score −3.5
- **THEN** the eviction task deletes that entry

#### Scenario: Invalid environment variable value
- **WHEN** `DEJAQ_EVICTION_FLOOR=bad` is set
- **THEN** the system uses the default floor of −5.0 and logs a warning
