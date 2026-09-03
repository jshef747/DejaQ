## MODIFIED Requirements

### Requirement: Positive feedback may carry a corrected answer

The system SHALL accept an optional `edited_answer` on `POST /v1/feedback`. The field SHALL be valid
only when `rating` is `"positive"` and an `interaction_id` is supplied; either condition unmet SHALL
return HTTP 422. Requests without `edited_answer` SHALL behave exactly as before, including their
existing response shapes.

When `edited_answer` is present, the system SHALL apply it to the cache **before** applying the
positive score, so that the `+1.0` lands on the human text rather than on the answer it replaced,
and so that an entry created by the edit exists before it is scored.

The response SHALL include `edit_status`, one of:

- `saved` — an existing entry's answer was replaced
- `created` — no entry existed, and one was written under a re-derived cache key
- `not_cached` — there was no entry to replace and no usable request replay to create one from
- `message_mismatch` — the supplied replay did not match the interaction's stored message hash

The response SHALL include the `response_id` the edit was applied to whenever an entry was written.
This may differ from the `response_id` the client supplied, because an alias-addressed edit is
applied to its root and a created entry is keyed by a freshly derived normalized query.

When `edit_status` is `not_cached` or `message_mismatch`, the system SHALL NOT attempt to score a
cache entry, since the id in hand names no entry. A client SHALL NOT present such a submission as a
recorded positive rating, because none was applied.

The system SHALL verify that the target `response_id` belongs to the authenticated workspace and
department **before** writing the edited answer. `response_id` is client-supplied and names the
collection to open, so validating it only during the scoring step would check ownership after the
answer had already been replaced.

If the write succeeds and the subsequent score update finds no entry — a concurrent deletion — the
system SHALL still report the edit outcome rather than failing the request, so a client is never
told a save failed while the text is in the cache.

#### Scenario: Save an edit over an existing entry

- **WHEN** a client POSTs `{"interaction_id": "<id>", "rating": "positive", "edited_answer": "<text>"}` for an interaction whose cache entry exists
- **THEN** the entry serves `<text>`, its score increases by 1.0, and the response is HTTP 200 with `{"status": "ok", "new_score": <float>, "edit_status": "saved", "response_id": "<id>"}`

#### Scenario: Save an edit when the entry was never stored

- **WHEN** a client POSTs an edit with a matching `messages` replay for an interaction whose cache entry does not exist
- **THEN** the system derives the cache key from the replay, stores the edited text verbatim as a human-authored entry, and returns `edit_status: "created"` with the derived `response_id`

#### Scenario: An edit outranks the cache filter

- **WHEN** the create path runs for a query the cache filter would reject as too short
- **THEN** the entry is still created, because a person vouching for an answer is stronger evidence than the heuristic

#### Scenario: Save an edit on an attachment turn with no entry

- **WHEN** a client POSTs an edit with no `messages` (an image or file turn) and no cache entry exists
- **THEN** the system writes nothing, does not score, and returns `edit_status: "not_cached"`

#### Scenario: Save an edit addressed to an alias

- **WHEN** the supplied `response_id` names an alias entry
- **THEN** the root entry and every alias of it serve the edited text, and the response reports the root's `response_id`

#### Scenario: Edit with a mismatched replay

- **WHEN** a client POSTs an edit whose `messages` hash does not match the interaction's stored hash and no entry exists to overwrite
- **THEN** the system writes nothing and returns `edit_status: "message_mismatch"`

#### Scenario: An edit naming another workspace's entry writes nothing

- **WHEN** a client authenticated for workspace `acme` POSTs an edit with its own valid `interaction_id` and a `response_id` in workspace `globex`'s namespace
- **THEN** the system returns HTTP 422 and no answer in `globex`'s cache is modified

#### Scenario: Edit with a negative rating is rejected

- **WHEN** a client POSTs `{"interaction_id": "<id>", "rating": "negative", "edited_answer": "<text>"}`
- **THEN** the system returns HTTP 422 and mutates nothing

#### Scenario: Edit without an interaction id is rejected

- **WHEN** a client POSTs `{"response_id": "<id>", "rating": "positive", "edited_answer": "<text>"}`
- **THEN** the system returns HTTP 422 and mutates nothing

#### Scenario: An empty or oversized edit is rejected

- **WHEN** a client POSTs an `edited_answer` that is blank, whitespace-only, or over the size limit
- **THEN** the system returns HTTP 422 and mutates nothing

### Requirement: Feedback submission records whether it carried an edit

The `feedback_log` row written for an accepted submission SHALL record whether the submission
carried an `edited_answer`, so a save can be told apart from a plain thumbs-up.

#### Scenario: A saved edit is logged as an edit

- **WHEN** a client POSTs positive feedback carrying `edited_answer`
- **THEN** the `feedback_log` row records `rating="positive"` and `edited=1`

#### Scenario: A plain thumbs-up is not logged as an edit

- **WHEN** a client POSTs positive feedback with no `edited_answer`
- **THEN** the `feedback_log` row records `edited=0`
