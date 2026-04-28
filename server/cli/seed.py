"""Demo seed: idempotent setup of demo org, departments, local user, membership, and sample stats."""
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone

import app.config as config
from app.db import user_repo
from app.db.models.org import Organization
from app.db.session import get_session
from app.services import admin_service
from app.dependencies.management_auth import ManagementAuthContext

logger = logging.getLogger("dejaq.seed")

DEMO_ORG_NAME = "Demo"
DEMO_ORG_SLUG = "demo"
DEMO_DEPT_NAMES = ["Engineering", "Support"]
DEMO_USER_EMAIL = "demo@dejaq.local"
DEMO_USER_PASSWORD = "demo1234"

_SYSTEM_CTX = ManagementAuthContext.system()

_SEED_STATS: list[dict] = [
    {"org": DEMO_ORG_SLUG, "department": "engineering", "latency_ms": 120, "cache_hit": 1, "difficulty": "easy", "model_used": "cache", "response_id": "demo-seed:r1"},
    {"org": DEMO_ORG_SLUG, "department": "engineering", "latency_ms": 850, "cache_hit": 0, "difficulty": "easy", "model_used": "gemma-local", "response_id": "demo-seed:r2"},
    {"org": DEMO_ORG_SLUG, "department": "engineering", "latency_ms": 2100, "cache_hit": 0, "difficulty": "hard", "model_used": "gemini-2.5-flash", "response_id": "demo-seed:r3"},
    {"org": DEMO_ORG_SLUG, "department": "support", "latency_ms": 95, "cache_hit": 1, "difficulty": "easy", "model_used": "cache", "response_id": "demo-seed:r4"},
    {"org": DEMO_ORG_SLUG, "department": "support", "latency_ms": 780, "cache_hit": 0, "difficulty": "easy", "model_used": "gemma-local", "response_id": "demo-seed:r5"},
    {"org": DEMO_ORG_SLUG, "department": "engineering", "latency_ms": 105, "cache_hit": 1, "difficulty": "easy", "model_used": "cache", "response_id": "demo-seed:r6"},
    {"org": DEMO_ORG_SLUG, "department": "support", "latency_ms": 1950, "cache_hit": 0, "difficulty": "hard", "model_used": "gemini-2.5-flash", "response_id": "demo-seed:r7"},
    {"org": DEMO_ORG_SLUG, "department": "engineering", "latency_ms": 88, "cache_hit": 1, "difficulty": "easy", "model_used": "cache", "response_id": "demo-seed:r8"},
]

_CREATE_REQUESTS_TABLE = """
CREATE TABLE IF NOT EXISTS requests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT    NOT NULL,
    org         TEXT    NOT NULL,
    department  TEXT    NOT NULL,
    latency_ms  INTEGER NOT NULL,
    cache_hit   INTEGER NOT NULL,
    difficulty  TEXT,
    model_used  TEXT,
    response_id TEXT
)
"""

_CREATE_FEEDBACK_TABLE = """
CREATE TABLE IF NOT EXISTS feedback_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT    NOT NULL,
    response_id TEXT    NOT NULL,
    org         TEXT    NOT NULL,
    department  TEXT    NOT NULL,
    rating      TEXT    NOT NULL,
    comment     TEXT
)
"""

_CREATE_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_requests_ts ON requests(ts)",
    "CREATE INDEX IF NOT EXISTS idx_requests_org_department_ts ON requests(org, department, ts)",
    "CREATE INDEX IF NOT EXISTS idx_feedback_log_ts_id ON feedback_log(ts, id)",
    "CREATE INDEX IF NOT EXISTS idx_feedback_log_org_department ON feedback_log(org, department)",
    "CREATE INDEX IF NOT EXISTS idx_feedback_log_response_id ON feedback_log(response_id)",
)


def _init_stats_db(con: sqlite3.Connection) -> None:
    con.execute(_CREATE_REQUESTS_TABLE)
    con.execute(_CREATE_FEEDBACK_TABLE)
    for stmt in _CREATE_INDEXES:
        con.execute(stmt)
    con.commit()


def seed_demo(
    stats_db_path: str | None = None,
    provider_key_provider: str | None = None,
    provider_key: str | None = None,
) -> dict:
    """Idempotently seed demo org, departments, user, membership, and sample stats.

    Returns a summary dict with what was created vs. already existed.
    """
    db_path = stats_db_path or config.STATS_DB_PATH
    env_provider, env_key = _provider_key_from_env()
    if provider_key_provider is None and provider_key is None:
        provider_key_provider = env_provider
        provider_key = env_key

    summary = {
        "org": None,
        "departments": [],
        "user": None,
        "membership": None,
        "stats_rows": 0,
        "credential": "not_supplied",
    }

    with get_session() as session:
        # 1. Org
        org = session.query(Organization).filter_by(slug=DEMO_ORG_SLUG).first()
        if org is None:
            try:
                org_read = admin_service.create_org(DEMO_ORG_NAME, ctx=_SYSTEM_CTX)
                with get_session() as s2:
                    org = s2.query(Organization).filter_by(slug=DEMO_ORG_SLUG).first()
                summary["org"] = "created"
            except admin_service.DuplicateSlug:
                with get_session() as s2:
                    org = s2.query(Organization).filter_by(slug=DEMO_ORG_SLUG).first()
                summary["org"] = "exists"
        else:
            summary["org"] = "exists"

    # Refresh org to get a valid session-independent id
    with get_session() as session:
        org = session.query(Organization).filter_by(slug=DEMO_ORG_SLUG).first()
        org_id = org.id

        # 2. Departments
        for dept_name in DEMO_DEPT_NAMES:
            dept_slug = dept_name.lower()
            from app.db.models.department import Department
            existing = session.query(Department).filter_by(org_id=org_id, slug=dept_slug).first()
            if existing is None:
                try:
                    admin_service.create_department(DEMO_ORG_SLUG, dept_name, ctx=_SYSTEM_CTX)
                    summary["departments"].append(f"{dept_slug}:created")
                except admin_service.DuplicateSlug:
                    summary["departments"].append(f"{dept_slug}:exists")
            else:
                summary["departments"].append(f"{dept_slug}:exists")

        # 3. Local user (supabase_user_id placeholder when no real Supabase configured)
        supabase_uid = _ensure_supabase_user()
        local_user = user_repo.upsert_user(session, supabase_uid, DEMO_USER_EMAIL)
        summary["user"] = "upserted"

        # 4. Membership
        from app.db.models.user_org_membership import UserOrgMembership
        existing_membership = session.query(UserOrgMembership).filter_by(
            user_id=local_user.id, org_id=org_id
        ).first()
        if existing_membership is None:
            user_repo.create_membership_idempotent(session, local_user.id, org_id)
            summary["membership"] = "created"
        else:
            summary["membership"] = "exists"

    # 5. Sample stats
    with sqlite3.connect(db_path) as con:
        _init_stats_db(con)
        base_ts = datetime(2026, 4, 1, 10, 0, 0, tzinfo=timezone.utc)
        inserted = 0
        for i, row in enumerate(_SEED_STATS):
            exists = con.execute(
                "SELECT 1 FROM requests WHERE response_id = ?", (row["response_id"],)
            ).fetchone()
            if not exists:
                ts = (base_ts + timedelta(hours=i)).isoformat()
                con.execute(
                    "INSERT INTO requests (ts, org, department, latency_ms, cache_hit, difficulty, model_used, response_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (ts, row["org"], row["department"], row["latency_ms"], row["cache_hit"],
                     row["difficulty"], row["model_used"], row["response_id"]),
                )
                inserted += 1
        con.commit()
        summary["stats_rows"] = inserted

    # 6. Optional encrypted provider credential
    if provider_key_provider or provider_key:
        if not provider_key_provider or provider_key is None:
            raise ValueError("Provider credential requires both provider and key.")

        encryption_key = os.getenv("DEJAQ_CREDENTIAL_ENCRYPTION_KEY", config.CREDENTIAL_ENCRYPTION_KEY).strip()
        if not encryption_key:
            summary["credential"] = "skipped_missing_encryption_key"
            return summary

        config.CREDENTIAL_ENCRYPTION_KEY = encryption_key
        from app.services.credential_service import CredentialService

        with get_session() as session:
            org = session.query(Organization).filter_by(slug=DEMO_ORG_SLUG).first()
            CredentialService().upsert(session, org.id, provider_key_provider, provider_key)
        summary["credential"] = f"{provider_key_provider}:upserted"

    return summary


def _provider_key_from_env() -> tuple[str | None, str | None]:
    value = os.getenv("DEJAQ_SEED_PROVIDER_KEY", "").strip()
    if not value:
        return None, None
    provider, sep, key = value.partition(":")
    if not sep or not provider.strip() or not key.strip():
        raise ValueError("DEJAQ_SEED_PROVIDER_KEY must use <provider>:<key> format.")
    return provider.strip(), key.strip()


def _ensure_supabase_user() -> str:
    """Create/update Supabase demo user if service-role key configured.

    Returns the Supabase user id (real or placeholder).
    """
    url = config.SUPABASE_URL.strip()
    key = config.SUPABASE_SERVICE_ROLE_KEY.strip()

    if not url or not key:
        logger.info("SUPABASE_SERVICE_ROLE_KEY not set; skipping Supabase Auth user creation")
        return f"demo-placeholder:{DEMO_USER_EMAIL}"

    try:
        from app.services.management_auth_service import get_service_role_client
        client = get_service_role_client()
        resp = client.admin.create_user({
            "email": DEMO_USER_EMAIL,
            "password": DEMO_USER_PASSWORD,
            "email_confirm": True,
        })
        logger.info("Supabase demo user created: %s", DEMO_USER_EMAIL)
        return resp.user.id
    except Exception as exc:
        err_str = str(exc)
        if "already" in err_str.lower() or "exists" in err_str.lower() or "422" in err_str:
            logger.info("Supabase demo user already exists, fetching id")
            try:
                from app.services.management_auth_service import get_service_role_client
                client = get_service_role_client()
                users = client.admin.list_users()
                for u in users:
                    if u.email == DEMO_USER_EMAIL:
                        return u.id
            except Exception:
                pass
        logger.warning("Could not create Supabase demo user: %s", exc)
        return f"demo-placeholder:{DEMO_USER_EMAIL}"
