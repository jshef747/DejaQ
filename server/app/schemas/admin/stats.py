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


class OrgStats(StatsMetrics):
    org: str
    org_name: str


class DepartmentStats(StatsMetrics):
    org: str
    department: str
    department_name: str


class OrgStatsReport(BaseModel):
    items: list[OrgStats]
    total: StatsMetrics


class DepartmentStatsReport(BaseModel):
    org: str
    items: list[DepartmentStats]
    total: StatsMetrics
