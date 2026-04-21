## ADDED Requirements

### Requirement: Return highest-scored candidate within similarity threshold

When the ChromaDB query returns multiple candidates whose cosine distance is ≤ 0.15, the system SHALL sort them by `score` descending and return the document with the highest score. If `score` metadata is absent on a candidate (legacy entry), treat it as 0.0.

#### Scenario: Multiple candidates within threshold, different scores

- **WHEN** a cache query returns three candidates all within cosine distance 0.15 with scores 2.0, −1.0, and 0.5 respectively
- **THEN** the system returns the candidate with score 2.0

#### Scenario: Single candidate within threshold

- **WHEN** a cache query returns exactly one candidate within cosine distance 0.15
- **THEN** the system returns that candidate without sorting overhead

#### Scenario: Legacy entry without score metadata

- **WHEN** a candidate document has no `score` field in its metadata
- **THEN** the system treats its score as 0.0 for ranking purposes

### Requirement: Cache miss when all candidates exceed threshold

The system SHALL treat the query as a cache miss if no candidate has cosine distance ≤ 0.15, regardless of their scores.

#### Scenario: All candidates above threshold

- **WHEN** the nearest candidate has cosine distance 0.20
- **THEN** the system proceeds to the LLM (cache miss path)
