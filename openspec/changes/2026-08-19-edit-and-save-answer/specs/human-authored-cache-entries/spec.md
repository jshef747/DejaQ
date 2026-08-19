## ADDED Requirements

### Requirement: A cache entry can hold an answer written by a person

The system SHALL allow a cache entry's answer to be replaced with text supplied by a user, and SHALL
mark such an entry with `authored="human"` metadata.

Replacing the answer SHALL preserve the entry's identity and every other field it carries:
`score`, `hit_count`, `negative_count`, `original_query`, `user_id`, and all image (`image_kind`,
`image_text`, `image_dhash`, `image_clip`) and file (`file_sha`, `file_kind`) identity fields. The
system SHALL NOT perform this replacement by re-storing the entry, because a store resets the
counters and drops identity fields that are not re-supplied.

#### Scenario: Overwriting keeps the entry's counters

- **WHEN** an entry with `score=4.0`, `hit_count=11` and `negative_count=1` has its answer replaced
- **THEN** the entry serves the new answer and still reports `score=4.0`, `hit_count=11`, `negative_count=1`

#### Scenario: Overwriting keeps an attachment-anchored entry gated

- **WHEN** an entry carrying `file_sha` and `file_kind` has its answer replaced
- **THEN** the entry still carries the same `file_sha` and `file_kind`, and is still reachable only when that file is attached

#### Scenario: Replacing the answer of an entry that does not exist

- **WHEN** a replacement targets an id no entry holds
- **THEN** the system reports the entry as missing rather than creating one under that id

### Requirement: The replaced answer does not survive anywhere

The system SHALL ensure that after a human answer replaces a model answer, no lookup can return the
replaced text.

An alias entry holds its own copy of its root's answer. The system SHALL rewrite every alias of the
edited entry with the new answer, and SHALL redirect a replacement addressed to an alias so that it
is applied to the root. A replacement SHALL report the id it was actually applied to.

#### Scenario: Aliases are rewritten with the new answer

- **WHEN** an entry with two alias entries has its answer replaced
- **THEN** both aliases serve the new answer, and no alias of a different entry is modified

#### Scenario: Editing through an alias applies to the root

- **WHEN** a replacement is addressed to an alias id
- **THEN** the root entry serves the new answer, the alias serves the new answer, and the reported id is the root's

### Requirement: A human-authored entry is protected from being overwritten, paraphrased, or evicted

The system SHALL NOT replace a human-authored entry with a model-generated answer through the
background store path, in either the Celery task or the in-process fallback. This applies to the
task dispatched for the same query before the edit was made.

The system SHALL NOT run the context adjuster over a human-authored answer when serving a cache hit,
so the stored text is returned unchanged.

The system SHALL NOT delete a human-authored entry during score-floor eviction. Negative feedback
SHALL still delete it.

#### Scenario: The background store refuses to overwrite an edit

- **WHEN** `generalize_and_store_task` runs for a key whose entry carries `authored="human"`
- **THEN** the task does not call the generalizer, does not store, and reports that it was skipped

#### Scenario: The in-process fallback refuses too

- **WHEN** the same store runs through the `DEJAQ_USE_CELERY=false` / Celery-outage path
- **THEN** it does not store and the human answer remains

#### Scenario: A cache hit on a human answer is served verbatim

- **WHEN** a cache hit resolves to an entry with `authored="human"`
- **THEN** the context adjuster is skipped and the response body is byte-identical to the stored answer

#### Scenario: Eviction spares a human answer

- **WHEN** the score-floor sweep finds a human-authored entry and a model-authored entry both below the floor
- **THEN** only the model-authored entry is deleted

#### Scenario: Negative feedback still removes a bad edit

- **WHEN** a user submits negative feedback on a human-authored entry with `negative_count == 0`
- **THEN** the entry is deleted, so a wrong edit remains undoable

### Requirement: A served human-authored answer is reported as such

The system SHALL set `x-dejaq-answer-authored: human` on a cache-hit response whose entry carries
`authored="human"`, and SHALL NOT set the header otherwise.

#### Scenario: Header present on a human-authored hit

- **WHEN** a request is answered from a human-authored cache entry
- **THEN** the response carries `x-dejaq-answer-authored: human`

#### Scenario: Header absent on an ordinary hit or a miss

- **WHEN** a request is answered from an ordinary cache entry, or by a model on a miss
- **THEN** the response carries no `x-dejaq-answer-authored` header
