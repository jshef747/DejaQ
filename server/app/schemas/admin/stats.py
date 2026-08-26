from pydantic import BaseModel


class StatsMetrics(BaseModel):
    requests: int
    hits: int
    misses: int
    hit_rate: float
    avg_latency_ms: float | None
    est_tokens_saved: int
    easy_count: int
    hard_count: int
    models_used: list[str]
    # Fraction of MISSES (generated answers, not cache hits - a hit is never
    # truncated) whose generator reported finish_reason="length". The store
    # guard already refuses to cache a truncated answer with no error raised
    # anywhere, so this is the only visible signal that a workspace's token
    # budgets are too tight for the answers it's actually generating.
    truncation_rate: float
    # Cache writes that never landed in the window. The response - response_id
    # header and all - has already gone out by the time the background store
    # runs, so a failure here has no request-level status to ride on: it used to
    # leave one ERROR line in the log and nothing else, while the cache quietly
    # stopped filling. Any non-zero value is a defect or an outage, never normal
    # traffic. Workspace-level only (see request_logger.record_store_failure),
    # so a per-department report reports its whole workspace's count.
    store_failures: int


class WorkspaceStats(StatsMetrics):
    workspace: str
    workspace_name: str


class DepartmentStats(StatsMetrics):
    workspace: str
    department: str
    department_name: str


class WorkspaceStatsReport(BaseModel):
    items: list[WorkspaceStats]
    total: StatsMetrics


class DepartmentStatsReport(BaseModel):
    workspace: str
    items: list[DepartmentStats]
    total: StatsMetrics
