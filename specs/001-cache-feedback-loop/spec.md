# Feature Specification: Cache Feedback Loop

**Feature Branch**: `001-cache-feedback-loop`
**Created**: 2026-02-19
**Status**: Draft
**Input**: User description: "Add a user feedback loop to DejaQ to improve cache quality over time."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Submit Feedback on a Response (Priority: P1)

An API consumer receives a response and wants to signal whether it was helpful or not. They submit a thumbs up or thumbs down rating tied to that specific response. The system records the rating and immediately adjusts the quality standing of the cache entry that produced the response.

**Why this priority**: This is the foundational interaction. Without the ability to collect feedback, no downstream quality improvements are possible. All other behaviors depend on this working correctly first.

**Independent Test**: Can be fully tested by submitting a positive or negative rating for a known cache entry and verifying the entry's quality score changes accordingly — delivers the core feedback collection value.

**Acceptance Scenarios**:

1. **Given** a response has been returned with a reference identifier, **When** a caller submits a positive rating for that identifier, **Then** the quality score for the associated cache entry increases by one and the updated score is returned.
2. **Given** a response has been returned with a reference identifier, **When** a caller submits a negative rating for that identifier, **Then** the quality score for the associated cache entry decreases by one and the updated score is returned.
3. **Given** a response identifier that does not exist, **When** a caller submits any rating, **Then** the system returns a clear error indicating the entry was not found.
4. **Given** a valid response identifier, **When** a caller submits a rating without specifying positive or negative, **Then** the system returns a validation error.

---

### User Story 2 - Trusted Entries Match More Broadly (Priority: P2)

Over time, cache entries that consistently receive positive ratings become trusted. When the system encounters a new query similar to a trusted entry, it is willing to serve the cached response even when the match is slightly less exact — broadening the benefit of a well-validated answer.

**Why this priority**: This delivers the primary cost-reduction benefit of the feedback loop. More cache hits on trusted entries means fewer LLM calls, directly reducing API spend.

**Independent Test**: Can be fully tested by accumulating enough positive ratings on a cache entry, then sending a query that is semantically close but not an exact match, and verifying the cached response is returned where it previously would not have been.

**Acceptance Scenarios**:

1. **Given** a cache entry with a high accumulated positive quality score, **When** a query arrives that is a near — but not close — semantic match, **Then** the system serves the cached response rather than calling the LLM.
2. **Given** a cache entry with a neutral or low quality score, **When** the same near-match query arrives, **Then** the system treats it as a cache miss and calls the LLM.

---

### User Story 3 - Low-Quality Entries Are Flagged and Removed (Priority: P3)

When a cache entry accumulates enough negative ratings, the system recognizes it as unreliable. It flags the entry for review and, once a defined threshold is crossed, automatically removes it so it is never served again. Subsequent queries that would have matched the removed entry are treated as fresh requests.

**Why this priority**: Preventing bad cached answers from being repeatedly served is critical to the system's trustworthiness. Without this, negative feedback has no practical effect.

**Independent Test**: Can be fully tested by submitting enough negative ratings to push an entry below the threshold, then querying for that entry and verifying a fresh response is generated rather than the cached one.

**Acceptance Scenarios**:

1. **Given** a cache entry whose quality score drops below the minimum threshold, **When** the next rating is submitted, **Then** the entry is marked as flagged and the response includes the updated status.
2. **Given** a flagged cache entry that has crossed the auto-removal threshold, **When** any query semantically matching that entry arrives, **Then** the system bypasses the cache and generates a fresh response.
3. **Given** a cache entry negatively rated after it was served as a hit, **When** the same query arrives again, **Then** the system skips the cache and generates a fresh response regardless of score.

---

### User Story 4 - Negative Feedback Prevents Low-Quality Storage (Priority: P4)

When a user receives a fresh LLM response (cache miss) and immediately rates it negatively, the system cancels the background process that would have stored that response in the cache. This prevents a known-bad answer from polluting the cache before it ever takes hold.

**Why this priority**: Early interception of bad responses before they enter the cache is more efficient than cleaning them up after they accumulate negative ratings. This closes a quality gap in the cache miss pipeline.

**Independent Test**: Can be fully tested by submitting negative feedback for a cache miss response within the storage window and then querying again to verify the entry was never stored.

**Acceptance Scenarios**:

1. **Given** a fresh response was just generated (cache miss) and background storage has not yet completed, **When** a caller submits a negative rating, **Then** the system cancels the pending storage and the response is never added to the cache.
2. **Given** a fresh response where background storage has already completed before feedback arrives, **When** a caller submits a negative rating, **Then** the system applies the normal negative feedback flow (decrement score, flag if threshold crossed).
3. **Given** a fresh response, **When** a caller submits a positive rating, **Then** normal storage proceeds without interruption.

---

### User Story 5 - Inspect Feedback History for a Cache Entry (Priority: P5)

An operator or developer wants to understand why a cache entry has a given quality score. They retrieve the full feedback history for that entry — a timestamped log of every positive and negative rating it has received — to diagnose cache quality issues.

**Why this priority**: Observability is essential for trust in the system. Operators need to verify the feedback loop is working correctly and audit why entries were flagged or removed.

**Independent Test**: Can be fully tested by submitting several ratings for an entry and retrieving the history, verifying each rating appears with the correct direction and a timestamp.

**Acceptance Scenarios**:

1. **Given** a cache entry with several ratings submitted at different times, **When** a caller requests the feedback history, **Then** the response contains all ratings in chronological order with direction and timestamp.
2. **Given** a cache entry with no feedback submitted, **When** a caller requests the history, **Then** the response returns an empty list (not an error).
3. **Given** an entry identifier that does not exist, **When** feedback history is requested, **Then** the system returns a clear not-found error.

---

### Edge Cases

- What happens when feedback is submitted for an entry that was already auto-deleted (quality threshold crossed)?
- How does the system handle duplicate or rapid sequential feedback submissions for the same entry?
- What happens when the feedback storage system is temporarily unavailable — is the rating lost or retried?
- What occurs when negative feedback for a cache miss arrives after the background storage task has already completed?
- How does the system behave if an entry's score is already at its minimum and another negative rating is submitted?
- What happens when multiple callers simultaneously submit conflicting feedback (positive and negative) for the same entry?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Each response returned by the system MUST include a unique identifier that callers can use to submit feedback.
- **FR-002**: The system MUST accept a positive or negative quality rating tied to a response identifier via a dedicated endpoint.
- **FR-003**: The system MUST increment the quality score of a cache entry when a positive rating is received.
- **FR-004**: The system MUST decrement the quality score of a cache entry when a negative rating is received.
- **FR-005**: The system MUST expand the semantic matching tolerance for cache entries that exceed a defined positive quality score threshold.
- **FR-006**: The system MUST flag a cache entry whose quality score falls below a defined negative threshold, marking it as unreliable.
- **FR-007**: Flagged entries that cross a defined auto-removal threshold MUST be deleted from the cache and no longer served.
- **FR-008**: When a negatively rated entry would have been served as a cache hit, the system MUST force a fresh response for subsequent identical queries, regardless of the current score.
- **FR-009**: The system MUST cancel or ignore pending background caching when a negative rating for a cache miss arrives before storage completes.
- **FR-010**: The feedback mechanism MUST function for both synchronous API calls and real-time streaming connections.
- **FR-011**: The system MUST expose a way to retrieve the complete feedback history (timestamped ratings) for any cache entry.
- **FR-012**: Quality score updates MUST not block the response to the caller — they MUST be applied asynchronously or in a non-blocking manner.
- **FR-013**: The system MUST behave correctly when background task offloading is disabled, applying quality updates in-process instead.
- **FR-014**: All feedback events MUST be persisted for fast access so feedback history can be retrieved without querying the primary cache store.

### Key Entities

- **Feedback Event**: A single quality rating (positive or negative) submitted by a caller, associated with a cache entry identifier and timestamped at submission time.
- **Cache Entry Quality Score**: A cumulative integer representing the net balance of positive and negative ratings received for a cache entry. Starts at zero. Influences matching sensitivity and entry lifecycle.
- **Flagged Entry**: A cache entry whose quality score has fallen below the minimum acceptable threshold. Marked as unreliable; prevents the entry from being served and may trigger auto-removal.
- **Feedback History**: The ordered log of all feedback events for a given cache entry, used for observability and audit.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Callers can submit feedback with a single additional request after receiving a response, with no additional setup required.
- **SC-002**: Cache entries that accumulate net positive ratings result in a measurable increase in cache hit rate for near-match queries compared to entries with neutral scores.
- **SC-003**: Cache entries that cross the negative threshold are no longer served within the same request cycle that triggers removal — zero stale responses after flagging.
- **SC-004**: Negative feedback submitted for a cache miss prevents that response from appearing in the cache, verifiable by re-querying and confirming a fresh response is generated.
- **SC-005**: Feedback history for any cache entry can be retrieved in under one second under normal load.
- **SC-006**: Submitting feedback does not add measurable latency to the original response — quality updates complete independently of the caller's experience.
- **SC-007**: The feedback loop operates correctly whether or not background task offloading is enabled — no quality updates are silently dropped in either mode.

## Assumptions

- Feedback is anonymous. There is no concept of per-user feedback tracking in this feature; ratings reflect aggregate community quality, not individual preferences.
- The quality score starts at zero for all new cache entries. No initial seeding or warm-up is required.
- The specific numeric thresholds for "trusted" (positive threshold) and "flagged/removed" (negative threshold) are configuration values; the spec does not prescribe exact numbers, leaving them to the implementation plan.
- There is no rate limiting or deduplication on feedback submission in this version. Rapid or duplicate submissions are accepted and counted.
- No UI changes are in scope. This feature is entirely API-facing; frontend integration is a separate specification.
- The system need not support bulk feedback submission (rating multiple entries in a single call) in this version.

## Dependencies & Constraints

- Depends on the existing chat pipeline returning a stable, referenceable identifier for each response so callers know which entry to rate.
- Depends on the existing background cache storage task being interruptible or ignorable when negative feedback for a cache miss arrives in time.
- Must remain consistent with the existing toggle that disables background task offloading — feedback quality updates must degrade gracefully to in-process execution in that mode.
- Feedback history persistence must survive service restarts; feedback events cannot be held only in process memory.