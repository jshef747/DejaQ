import sqlite3
from datetime import date

import pytest


def _seed_requests(db_path, rows):
    con = sqlite3.connect(db_path)
    con.execute(
        """CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            org TEXT NOT NULL,
            department TEXT NOT NULL,
            latency_ms INTEGER NOT NULL,
            cache_hit INTEGER NOT NULL,
            difficulty TEXT,
            model_used TEXT,
            response_id TEXT
        )"""
    )
    con.executemany(
        "INSERT INTO requests (ts, org, department, latency_ms, cache_hit, difficulty, model_used, response_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    con.commit()
    con.close()


def test_org_stats_aggregates_identity_rows_and_total(isolated_stats_db):
    from app.services import stats_service

    _seed_requests(
        isolated_stats_db,
        [
            ("2026-04-01T00:00:00+00:00", "acme", "eng", 100, 1, "easy", "cache", "r1"),
            ("2026-04-01T01:00:00+00:00", "acme", "support", 300, 0, "hard", "gemini", "r2"),
            ("2026-04-02T00:00:00+00:00", "beta", "default", 200, 1, "easy", "cache", "r3"),
        ],
    )

    report = stats_service.org_stats()

    assert [(item.org, item.requests, item.hits, item.misses) for item in report.items] == [
        ("acme", 2, 1, 1),
        ("beta", 1, 1, 0),
    ]
    assert report.total.requests == 3
    assert report.total.hits == 2
    assert report.total.est_tokens_saved == 300
    assert sorted(report.total.models_used) == ["cache", "gemini"]


def test_department_stats_honors_exact_date_boundaries(isolated_stats_db):
    from app.services import stats_service

    _seed_requests(
        isolated_stats_db,
        [
            ("2026-03-31T23:59:59+00:00", "acme", "eng", 99, 1, "easy", "before", "r0"),
            ("2026-04-01T00:00:00+00:00", "acme", "eng", 100, 1, "easy", "cache", "r1"),
            ("2026-04-14T23:59:59+00:00", "acme", "eng", 300, 0, "hard", "gemini", "r2"),
            ("2026-04-15T00:00:00+00:00", "acme", "eng", 200, 1, "easy", "after", "r3"),
        ],
    )

    report = stats_service.department_stats(
        "acme",
        from_date=date(2026, 4, 1),
        to_date=date(2026, 4, 15),
    )

    assert report.org == "acme"
    assert len(report.items) == 1
    row = report.items[0]
    assert row.department == "eng"
    assert row.requests == 2
    assert row.hits == 1
    assert row.misses == 1
    assert sorted(row.models_used) == ["cache", "gemini"]


def test_stats_service_rejects_reversed_date_range(isolated_stats_db):
    from app.services import stats_service

    with pytest.raises(stats_service.InvalidDateRange):
        stats_service.org_stats(from_date=date(2026, 4, 15), to_date=date(2026, 4, 1))
