# stats-cli Specification

## Purpose
Define request-log statistics aggregation and CLI rendering behavior, including the shared service contract used by management API stats endpoints.

## Requirements

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

### Requirement: Stats aggregation logic is shared between CLI and API

The system SHALL extract request-log aggregation queries from `cli/stats.py` into `app/services/stats_service.py`, exposing functions that return typed Pydantic models (e.g., `StatsMetrics`, `OrgStats`, `DepartmentStats`) covering `requests`, `hits`, `misses`, `hit_rate`, `avg_latency_ms`, `est_tokens_saved`, `easy_count`, `hard_count`, `models_used`. `OrgStats` SHALL include org identity fields, `DepartmentStats` SHALL include org and department identity fields, and report objects SHALL include a `total: StatsMetrics` aggregate. Both the existing CLI rendering and the new `/admin/v1/stats/*` HTTP endpoints SHALL call the same service functions so numeric output stays consistent. The CLI command behavior, layout, color rules, and "150 tokens per hit" heuristic SHALL remain unchanged.

The service scope is request-log aggregates only. Any existing CLI-only Cache Health panel or ChromaDB inspection remains owned by `cli/stats.py` unless a later change defines a management API contract for cache health.

#### Scenario: CLI uses the shared service

- **WHEN** the user runs `dejaq-admin stats`
- **THEN** the rendered table is populated by calling `stats_service` functions, not by inline `sqlite3` queries

#### Scenario: API and CLI return identical numbers for the same window

- **WHEN** the CLI is run and `GET /admin/v1/stats/orgs` is called over the same time range
- **THEN** every numeric field for every org row matches exactly

### Requirement: Stats service supports optional date range

The stats service functions SHALL accept optional `from_date` and `to_date` parameters (`datetime.date` or `None`) and apply them to the SQL `WHERE ts >= ? AND ts < ?` clause. Date bounds SHALL be converted to the same UTC ISO timestamp representation used by stored request-log rows: Python `datetime(..., tzinfo=timezone.utc).isoformat()` strings with `+00:00` offsets, not `Z` suffixes. When both are `None`, the service SHALL return aggregates over all rows. If both dates are present and `from_date > to_date`, the service SHALL raise a validation error that the API maps to HTTP 422.

#### Scenario: Service called with date range

- **WHEN** `stats_service.org_stats(from_date=date(2026,4,1), to_date=date(2026,4,15))` is called
- **THEN** only rows with `ts` in `[2026-04-01T00:00:00+00:00, 2026-04-15T00:00:00+00:00)` are aggregated

#### Scenario: Service called without date range

- **WHEN** `stats_service.org_stats(from_date=None, to_date=None)` is called
- **THEN** all rows in `requests` are aggregated

#### Scenario: Service rejects reversed date range

- **WHEN** `stats_service.org_stats(from_date=date(2026,4,15), to_date=date(2026,4,1))` is called
- **THEN** a validation error is raised
