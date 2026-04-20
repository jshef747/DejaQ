## ADDED Requirements

### Requirement: Stats CLI command renders a Rich TUI table
The system SHALL provide a CLI command (`uv run python -m app.cli.stats`) that reads the SQLite request log and renders a Rich table to the terminal. The command SHALL NOT require the FastAPI server to be running.

#### Scenario: Stats command runs standalone
- **WHEN** the user runs `uv run python -m app.cli.stats` with the server stopped
- **THEN** the Rich table renders successfully by reading `dejaq_stats.db` directly

#### Scenario: No data yet
- **WHEN** the stats DB exists but contains zero rows
- **THEN** the CLI displays a message indicating no requests have been recorded yet

#### Scenario: DB file not found
- **WHEN** `dejaq_stats.db` does not exist
- **THEN** the CLI prints a clear error message and exits with a non-zero code

### Requirement: Table shows per-department rows and an org-wide total row
The system SHALL render one row per unique `(org, department)` pair, plus a final **Total** row aggregating all rows across all orgs and departments. Columns SHALL be: Department, Requests, Hit Rate, Avg Latency, Est. Tokens Saved, Easy Misses, Hard Misses, Models Used.

#### Scenario: Multiple departments displayed
- **WHEN** the log contains requests from two departments in the same org
- **THEN** two department rows appear plus one Total row

#### Scenario: Total row aggregates all orgs
- **WHEN** the log contains requests from multiple orgs
- **THEN** the Total row sums across all orgs

### Requirement: Table rows are color-coded by dominant outcome
The system SHALL color-code each row based on its cache hit rate: rows where hit rate ≥ 50% SHALL render in green, rows where hit rate < 50% SHALL render in amber/yellow, and any row containing errors (future) SHALL render in red. The Total row SHALL follow the same color rule.

#### Scenario: High hit-rate department is green
- **WHEN** a department row has cache hit rate ≥ 50%
- **THEN** the row text renders in Rich green style

#### Scenario: Low hit-rate department is amber
- **WHEN** a department row has cache hit rate < 50%
- **THEN** the row text renders in Rich yellow style

### Requirement: Est. Tokens Saved uses a word-count heuristic
The system SHALL estimate tokens saved for cache hits as `sum(len(response_text.split()) * 1.3)` across all hit rows. Since response text is not stored in the log, the estimate SHALL use a fixed average of 150 tokens saved per cache hit. The column header SHALL be labeled "Est. Tokens Saved" to make the approximation explicit.

#### Scenario: Tokens saved calculated per hit
- **WHEN** a department has 10 cache hits
- **THEN** Est. Tokens Saved displays 1500 (10 × 150)

### Requirement: Models Used column lists distinct models for misses
The system SHALL display a comma-separated list of distinct `model_used` values from miss rows for each department row. Cache hits (where `model_used` is NULL) SHALL be excluded from this column.

#### Scenario: Multiple models shown
- **WHEN** a department has easy misses using `llama-3.2-1b` and hard misses using `gpt-4o`
- **THEN** the Models Used column shows `llama-3.2-1b, gpt-4o`
