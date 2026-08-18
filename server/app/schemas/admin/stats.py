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
