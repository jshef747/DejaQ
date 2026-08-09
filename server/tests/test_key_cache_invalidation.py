import time


def test_invalidate_fires_after_commit_not_before(isolated_org_db, monkeypatch):
    """admin_service mutations must commit before busting the key cache, else a
    concurrent request refreshing between invalidate() and commit() can
    re-cache pre-mutation state for a full TTL."""
    from app.services import admin_service
    from app.db.base import SessionLocal
    from app.db.models.workspace import Workspace

    seen_committed = []

    def _spy_invalidate():
        with SessionLocal() as session:
            seen_committed.append(session.query(Workspace).filter_by(slug="acme").first() is not None)

    monkeypatch.setattr(admin_service, "_invalidate_key_cache", _spy_invalidate)

    admin_service.create_workspace("Acme")

    assert seen_committed == [True]


def test_key_cache_picks_up_out_of_process_db_change_before_ttl(isolated_org_db):
    """A dejaq-admin CLI mutation runs in a separate process from the server,
    so only a signal both processes can observe (the DB file itself changing)
    lets the server pick up the new key without waiting out KEY_CACHE_TTL."""
    from app.services import admin_service
    from app.middleware.api_key import _KeyCache

    admin_service.create_workspace("Acme")

    # Long TTL: any pickup must come from the mtime signal, not TTL expiry.
    cache = _KeyCache(ttl=3600)
    assert cache.resolve("does-not-exist-yet") is None

    # Ensure the filesystem mtime actually advances before the next commit.
    time.sleep(0.01)
    key = admin_service.generate_key("acme", force=False)

    resolved = cache.resolve(key.token)
    assert resolved is not None
    assert resolved[0] == "acme"
