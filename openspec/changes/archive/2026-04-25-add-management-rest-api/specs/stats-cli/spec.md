## ADDED Requirements

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
