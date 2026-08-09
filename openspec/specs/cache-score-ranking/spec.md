## ADDED Requirements

### Requirement: Rank candidates across the trusted, band, and rescue tiers

A cache lookup SHALL classify every ChromaDB candidate by cosine distance into one of three tiers and rank them in tier priority order, sorted by `score` descending within each tier. If `score` metadata is absent on a candidate (legacy entry), treat it as 0.0.

- **trusted** - distance ≤ `DEJAQ_CACHE_TRUST_DISTANCE` (0.15): served directly.
- **band** - distance in (trust, `DEJAQ_CACHE_BAND_MAX_DISTANCE`] (0.20): served only if the cache validator accepts.
- **lexical rescue** - distance ≤ `DEJAQ_CACHE_RESCUE_MAX_DISTANCE` (0.60) and word-aligned with the stored query (`services/lexical_match.py::align`): validator-gated as well.

Each candidate SHALL carry the `requires_validation` / `rescued` flags of its own tier, so a caller that falls past the trusted candidates still knows the later ones need the validator.

#### Scenario: Multiple candidates in one tier, different scores

- **WHEN** a cache query returns three trusted candidates with scores 2.0, −1.0, and 0.5 respectively
- **THEN** they rank 2.0, 0.5, −1.0 and the candidate with score 2.0 is the winner

#### Scenario: Candidates spread across tiers

- **WHEN** a query returns a band candidate with score 5.0 and a trusted candidate with score 0.0
- **THEN** the trusted candidate ranks first regardless of score, and the band candidate follows flagged `requires_validation`

#### Scenario: Legacy entry without score metadata

- **WHEN** a candidate document has no `score` field in its metadata
- **THEN** the system treats its score as 0.0 for ranking purposes

#### Scenario: Entry missing its stored answer

- **WHEN** a candidate's metadata has no `generalized_answer` field
- **THEN** the system logs a warning and skips that candidate, ranking the remaining candidates normally

### Requirement: Cache miss when no candidate qualifies for any tier

The system SHALL treat the query as a cache miss if no candidate qualifies for the trusted, band, or rescue tier, regardless of their scores. The nearest candidate's distance and prompt SHALL still be reported for diagnostics.

#### Scenario: All candidates outside every tier

- **WHEN** the nearest candidate has cosine distance 0.35 and does not word-align with the query
- **THEN** the system proceeds to the LLM (cache miss path) and still reports nearest distance 0.35

### Requirement: Attachment gates filter the candidate pool

A request carrying an image or a file SHALL be gated against the full ranked candidate list (`MemoryService.lookup_cache_pool`) rather than the single top-ranked candidate: each candidate is put through the image and file gates in rank order, and the first one passing both is served. A gate REJECT SHALL advance to the next candidate instead of ending the lookup. The gates themselves are unchanged, so a candidate anchored to a different attachment is still never served; only what happens after a REJECT changes. Gate mechanics and the limits of this walk: [docs/image-gate.md](../../../docs/image-gate.md#sibling-entries-and-the-candidate-pool).

#### Scenario: Top-ranked candidate belongs to a different attachment

- **WHEN** two documents are cached under the same question and the entry anchored to the *other* document ranks first
- **THEN** the file gate rejects that candidate and this request is served its own document's entry from further down the pool

#### Scenario: No candidate passes the gates

- **WHEN** every candidate in the pool is rejected by the attachment gate
- **THEN** the request is a clean cache miss whose nearest-distance and nearest-prompt diagnostics still describe the pool's nearest text match, not the last candidate rejected

#### Scenario: Text request against an attachment-anchored candidate

- **WHEN** a request carries no attachment and the top-ranked candidate is anchored to an image or a file
- **THEN** that candidate is rejected and the walk continues, so an unanchored entry further down the pool can still be served
