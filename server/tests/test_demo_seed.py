"""Tests: demo seed is idempotent and does not duplicate rows."""
import sqlite3

import pytest


@pytest.mark.no_model
def test_demo_seed_creates_org_dept_user_membership(isolated_org_db, isolated_stats_db):
    from cli.seed import seed_demo, DEMO_ORG_SLUG, DEMO_DEPT_NAMES, DEMO_USER_EMAIL

    summary = seed_demo(stats_db_path=str(isolated_stats_db))

    assert summary["org"] in ("created", "exists")
    assert summary["user"] == "upserted"
    assert summary["membership"] in ("created", "exists")

    from app.db.session import get_session
    from app.db.models.org import Organization
    from app.db.models.department import Department
    from app.db.models.user import ManagementUser
    from app.db.models.user_org_membership import UserOrgMembership

    with get_session() as session:
        org = session.query(Organization).filter_by(slug=DEMO_ORG_SLUG).first()
        assert org is not None

        for dept_name in DEMO_DEPT_NAMES:
            dept = session.query(Department).filter_by(org_id=org.id, slug=dept_name.lower()).first()
            assert dept is not None, f"Department {dept_name} not found"

        user = session.query(ManagementUser).filter_by(email=DEMO_USER_EMAIL).first()
        assert user is not None

        membership = session.query(UserOrgMembership).filter_by(
            user_id=user.id, org_id=org.id
        ).first()
        assert membership is not None


@pytest.mark.no_model
def test_demo_seed_is_idempotent(isolated_org_db, isolated_stats_db):
    from cli.seed import seed_demo, DEMO_ORG_SLUG, DEMO_DEPT_NAMES, DEMO_USER_EMAIL

    seed_demo(stats_db_path=str(isolated_stats_db))
    seed_demo(stats_db_path=str(isolated_stats_db))

    from app.db.session import get_session
    from app.db.models.org import Organization
    from app.db.models.department import Department
    from app.db.models.user import ManagementUser
    from app.db.models.user_org_membership import UserOrgMembership

    with get_session() as session:
        org_count = session.query(Organization).filter_by(slug=DEMO_ORG_SLUG).count()
        assert org_count == 1, "Duplicate orgs after double seed"

        org = session.query(Organization).filter_by(slug=DEMO_ORG_SLUG).first()
        for dept_name in DEMO_DEPT_NAMES:
            dept_count = session.query(Department).filter_by(
                org_id=org.id, slug=dept_name.lower()
            ).count()
            assert dept_count == 1, f"Duplicate department {dept_name}"

        user_count = session.query(ManagementUser).filter_by(email=DEMO_USER_EMAIL).count()
        assert user_count == 1, "Duplicate users after double seed"

        user = session.query(ManagementUser).filter_by(email=DEMO_USER_EMAIL).first()
        membership_count = session.query(UserOrgMembership).filter_by(
            user_id=user.id, org_id=org.id
        ).count()
        assert membership_count == 1, "Duplicate memberships after double seed"


@pytest.mark.no_model
def test_demo_seed_stats_not_duplicated(isolated_org_db, isolated_stats_db):
    from cli.seed import seed_demo, _SEED_STATS

    seed_demo(stats_db_path=str(isolated_stats_db))
    seed_demo(stats_db_path=str(isolated_stats_db))

    with sqlite3.connect(str(isolated_stats_db)) as con:
        for row in _SEED_STATS:
            count = con.execute(
                "SELECT COUNT(*) FROM requests WHERE response_id = ?", (row["response_id"],)
            ).fetchone()[0]
            assert count == 1, f"Duplicate stats row for {row['response_id']}"


@pytest.mark.no_model
def test_demo_seed_initializes_stats_schema(isolated_org_db, isolated_stats_db):
    """Seed must work even when stats DB has no schema yet."""
    from cli.seed import seed_demo

    summary = seed_demo(stats_db_path=str(isolated_stats_db))
    assert summary["stats_rows"] > 0

    with sqlite3.connect(str(isolated_stats_db)) as con:
        tables = [row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        assert "requests" in tables
        assert "feedback_log" in tables


@pytest.mark.no_model
def test_demo_seed_second_run_inserts_zero_stats(isolated_org_db, isolated_stats_db):
    from cli.seed import seed_demo

    first = seed_demo(stats_db_path=str(isolated_stats_db))
    assert first["stats_rows"] > 0

    second = seed_demo(stats_db_path=str(isolated_stats_db))
    assert second["stats_rows"] == 0


@pytest.mark.no_model
def test_demo_seed_provider_key_upserts_credential(isolated_org_db, isolated_stats_db, monkeypatch):
    from cryptography.fernet import Fernet

    import app.config as config
    from app.db.models.org import Organization
    from app.db.session import get_session
    from app.services.credential_service import CredentialService
    from cli.seed import seed_demo

    key = Fernet.generate_key().decode()
    monkeypatch.setenv("DEJAQ_CREDENTIAL_ENCRYPTION_KEY", key)
    monkeypatch.setattr(config, "CREDENTIAL_ENCRYPTION_KEY", key, raising=False)

    summary = seed_demo(
        stats_db_path=str(isolated_stats_db),
        provider_key_provider="google",
        provider_key="AIzaFoo123Bar",
    )

    assert summary["credential"] == "google:upserted"
    with get_session() as session:
        org = session.query(Organization).filter_by(slug="demo").first()
        assert CredentialService().get_decrypted_key(session, org.id, "google") == "AIzaFoo123Bar"


@pytest.mark.no_model
def test_demo_seed_provider_key_skips_without_encryption_key(
    isolated_org_db,
    isolated_stats_db,
    monkeypatch,
):
    import app.config as config
    from app.db import credential_repo
    from app.db.models.org import Organization
    from app.db.session import get_session
    from cli.seed import seed_demo

    monkeypatch.delenv("DEJAQ_CREDENTIAL_ENCRYPTION_KEY", raising=False)
    monkeypatch.setattr(config, "CREDENTIAL_ENCRYPTION_KEY", "", raising=False)

    summary = seed_demo(
        stats_db_path=str(isolated_stats_db),
        provider_key_provider="google",
        provider_key="AIzaFoo123Bar",
    )

    assert summary["credential"] == "skipped_missing_encryption_key"
    with get_session() as session:
        org = session.query(Organization).filter_by(slug="demo").first()
        assert credential_repo.list_credentials(session, org.id) == []
