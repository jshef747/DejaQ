import pytest


def test_admin_service_org_department_round_trip(isolated_org_db):
    from app.services import admin_service

    org = admin_service.create_org("Acme Inc")
    dept = admin_service.create_department("acme-inc", "Engineering")

    assert org.slug == "acme-inc"
    assert dept.org_slug == "acme-inc"
    assert dept.slug == "engineering"
    assert dept.cache_namespace == "acme-inc__engineering"

    all_depts = admin_service.list_departments()
    assert [(item.org_slug, item.slug) for item in all_depts] == [
        ("acme-inc", "engineering")
    ]

    deleted = admin_service.delete_org("acme-inc")
    assert deleted.deleted is True
    assert deleted.departments_removed == 1
    assert admin_service.list_orgs() == []


def test_admin_service_duplicate_org_raises(isolated_org_db):
    from app.services import admin_service

    admin_service.create_org("Acme")

    with pytest.raises(admin_service.DuplicateSlug) as exc:
        admin_service.create_org("Acme")

    assert exc.value.slug == "acme"


def test_admin_service_department_errors_and_delete_result(isolated_org_db):
    from app.services import admin_service

    admin_service.create_org("Acme")
    admin_service.create_department("acme", "Support")

    with pytest.raises(admin_service.DuplicateSlug):
        admin_service.create_department("acme", "Support")

    deleted = admin_service.delete_department("acme", "support")
    assert deleted.deleted is True
    assert deleted.cache_namespace == "acme__support"

    with pytest.raises(admin_service.DeptNotFound):
        admin_service.delete_department("acme", "support")


def test_admin_service_key_generate_force_and_revoke(isolated_org_db):
    from app.services import admin_service

    admin_service.create_org("Acme")
    first = admin_service.generate_key("acme", force=False)

    assert first.org_slug == "acme"
    assert first.token

    with pytest.raises(admin_service.ActiveKeyExists) as exc:
        admin_service.generate_key("acme", force=False)
    assert exc.value.key_id == first.id

    second = admin_service.generate_key("acme", force=True)
    assert second.id != first.id

    listed = admin_service.list_keys("acme")
    prefixes = {item.token_prefix for item in listed}
    assert first.token[:12] + "..." in prefixes
    assert second.token[:12] + "..." in prefixes
    assert all(not hasattr(item, "token") for item in listed)

    revoked = admin_service.revoke_key(second.id)
    assert revoked.revoked is True
    assert revoked.already_revoked is False

    revoked_again = admin_service.revoke_key(second.id)
    assert revoked_again.revoked is True
    assert revoked_again.already_revoked is True

    with pytest.raises(admin_service.KeyNotFound):
        admin_service.revoke_key(999999)
