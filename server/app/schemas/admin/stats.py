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
