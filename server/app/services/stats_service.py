import sqlite3
from datetime import date, datetime, time, timezone

import app.config as config
from app.db.models.department import Department
from app.db.models.org import Organization
from app.db.session import get_session
from app.schemas.admin.stats import (
    DepartmentStats,
    DepartmentStatsReport,
    OrgStats,
    OrgStatsReport,
    StatsMetrics,
)

_TOKENS_PER_HIT = 150


class InvalidDateRange(Exception):
    pass


def _bound(value: date | None) -> str | None:
    if value is None:
        return None
    return datetime.combine(value, time.min, tzinfo=timezone.utc).isoformat()


def _validate_range(from_date: date | None, to_date: date | None) -> tuple[str | None, str | None]:
    if from_date is not None and to_date is not None and from_date > to_date:
        raise InvalidDateRange("from_date must be before or equal to to_date")
    return _bound(from_date), _bound(to_date)


def _where(
    from_date: date | None,
    to_date: date | None,
    extra: str | None = None,
) -> tuple[str, list[object]]:
    lower, upper = _validate_range(from_date, to_date)
    clauses: list[str] = []
    params: list[object] = []
    if lower is not None:
        clauses.append("ts >= ?")
        params.append(lower)
    if upper is not None:
        clauses.append("ts < ?")
        params.append(upper)
    if extra:
        clauses.append(extra)
    return ("WHERE " + " AND ".join(clauses) if clauses else ""), params


def _models(value: str | None) -> list[str]:
    return sorted(model for model in (value or "").split(",") if model)


def _metrics(row) -> StatsMetrics:
    requests = int(row[0] or 0)
    hits = int(row[1] or 0)
    misses = int(row[2] or 0)
    avg_latency = row[3]
    easy = int(row[4] or 0)
    hard = int(row[5] or 0)
    models = _models(row[6])
    return StatsMetrics(
        requests=requests,
        hits=hits,
        misses=misses,
        hit_rate=(hits / requests if requests else 0.0),
        avg_latency_ms=float(avg_latency) if avg_latency is not None else None,
        est_tokens_saved=hits * _TOKENS_PER_HIT,
        easy_count=easy,
        hard_count=hard,
        models_used=models,
    )


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(config.STATS_DB_PATH)


def _org_name_map() -> dict[str, str]:
    """Return slug → display name for all orgs."""
    with get_session() as session:
        rows = session.query(Organization.slug, Organization.name).all()
    return {slug: name for slug, name in rows}


def _dept_name_map(org_slug: str) -> dict[str, str]:
    """Return dept slug → display name for all departments under org_slug."""
    with get_session() as session:
        org = session.query(Organization).filter_by(slug=org_slug).first()
        if org is None:
            return {}
        rows = session.query(Department.slug, Department.name).filter_by(org_id=org.id).all()
    return {slug: name for slug, name in rows}


def _aggregate_sql(where_clause: str, group_by: str = "") -> str:
    return f"""
        SELECT
            COUNT(*) AS total,
            COALESCE(SUM(cache_hit), 0) AS hits,
            COUNT(*) - COALESCE(SUM(cache_hit), 0) AS misses,
            AVG(latency_ms) AS avg_lat,
            SUM(CASE WHEN difficulty = 'easy' THEN 1 ELSE 0 END) AS easy,
            SUM(CASE WHEN difficulty = 'hard' THEN 1 ELSE 0 END) AS hard,
            GROUP_CONCAT(DISTINCT model_used) AS models
        FROM requests
        {where_clause}
        {group_by}
    """


def org_stats(
    from_date: date | None = None,
    to_date: date | None = None,
    accessible_org_slugs: set[str] | None = None,
) -> OrgStatsReport:
    """Return per-org stats. Pass accessible_org_slugs=None for system/full access."""
    where_clause, params = _where(from_date, to_date)
    name_map = _org_name_map()
    with _connect() as con:
        rows = con.execute(
            f"""
            SELECT
                org,
                COUNT(*) AS total,
                COALESCE(SUM(cache_hit), 0) AS hits,
                COUNT(*) - COALESCE(SUM(cache_hit), 0) AS misses,
                AVG(latency_ms) AS avg_lat,
                SUM(CASE WHEN difficulty = 'easy' THEN 1 ELSE 0 END) AS easy,
                SUM(CASE WHEN difficulty = 'hard' THEN 1 ELSE 0 END) AS hard,
                GROUP_CONCAT(DISTINCT model_used) AS models
            FROM requests
            {where_clause}
            GROUP BY org
            ORDER BY org
            """,
            params,
        ).fetchall()
        total_row = con.execute(_aggregate_sql(where_clause), params).fetchone()

    items = []
    total_items = []
    for row in rows:
        slug = row[0]
        if accessible_org_slugs is not None and slug not in accessible_org_slugs:
            continue
        metrics = _metrics(row[1:])
        items.append(OrgStats(org=slug, org_name=name_map.get(slug, slug), **metrics.model_dump()))
        total_items.append(metrics)

    if accessible_org_slugs is not None:
        # Recompute total from visible rows only
        if not total_items:
            agg_total = StatsMetrics(
                requests=0, hits=0, misses=0, hit_rate=0.0,
                avg_latency_ms=None, est_tokens_saved=0,
                easy_count=0, hard_count=0, models_used=[],
            )
        else:
            total_requests = sum(m.requests for m in total_items)
            total_hits = sum(m.hits for m in total_items)
            total_misses = sum(m.misses for m in total_items)
            latencies = [m.avg_latency_ms for m in total_items if m.avg_latency_ms is not None]
            all_models: set[str] = set()
            for m in total_items:
                all_models.update(m.models_used)
            agg_total = StatsMetrics(
                requests=total_requests,
                hits=total_hits,
                misses=total_misses,
                hit_rate=total_hits / total_requests if total_requests else 0.0,
                avg_latency_ms=sum(latencies) / len(latencies) if latencies else None,
                est_tokens_saved=total_hits * _TOKENS_PER_HIT,
                easy_count=sum(m.easy_count for m in total_items),
                hard_count=sum(m.hard_count for m in total_items),
                models_used=sorted(all_models),
            )
        return OrgStatsReport(items=items, total=agg_total)

    return OrgStatsReport(items=items, total=_metrics(total_row))


def department_stats(
    org_slug: str,
    from_date: date | None = None,
    to_date: date | None = None,
) -> DepartmentStatsReport:
    where_clause, params = _where(from_date, to_date, "org = ?")
    params.append(org_slug)
    with _connect() as con:
        rows = con.execute(
            f"""
            SELECT
                department,
                COUNT(*) AS total,
                COALESCE(SUM(cache_hit), 0) AS hits,
                COUNT(*) - COALESCE(SUM(cache_hit), 0) AS misses,
                AVG(latency_ms) AS avg_lat,
                SUM(CASE WHEN difficulty = 'easy' THEN 1 ELSE 0 END) AS easy,
                SUM(CASE WHEN difficulty = 'hard' THEN 1 ELSE 0 END) AS hard,
                GROUP_CONCAT(DISTINCT model_used) AS models
            FROM requests
            {where_clause}
            GROUP BY department
            ORDER BY department
            """,
            params,
        ).fetchall()
        total_row = con.execute(_aggregate_sql(where_clause), params).fetchone()

    dept_name_map = _dept_name_map(org_slug)
    items = []
    for row in rows:
        slug = row[0]
        if dept_name_map and slug not in dept_name_map:
            continue
        metrics = _metrics(row[1:])
        items.append(
            DepartmentStats(
                org=org_slug,
                department=slug,
                department_name=dept_name_map.get(slug, slug),
                **metrics.model_dump(),
            )
        )
    return DepartmentStatsReport(org=org_slug, items=items, total=_metrics(total_row))
