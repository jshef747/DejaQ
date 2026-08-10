import os


def db_mtime() -> float:
    """mtime of the SQLite file backing the app's SQLAlchemy session.

    A shared signal any process can produce just by committing a write —
    unlike an in-process invalidate(), this is visible to a process that
    never made the mutation itself (a separate `dejaq-admin` CLI run, or a
    Celery worker reading a change a FastAPI request just wrote). Used by
    every in-process TTL cache that needs early invalidation on a
    cross-process DB write — see middleware/api_key.py's _KeyCache and
    services/pipeline_config_cache.py.
    """
    try:
        from app.db.base import SessionLocal

        return os.path.getmtime(SessionLocal.kw["bind"].url.database)
    except OSError:
        return 0.0
