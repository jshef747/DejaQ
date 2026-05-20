import asyncio

import pytest

pytestmark = pytest.mark.no_model


def test_message_hash_is_stable_for_json_key_order():
    from app.services.response_registry import compute_messages_hash

    left = [
        {"role": "system", "content": "Be brief."},
        {"role": "user", "content": "Hello"},
    ]
    right = [
        {"content": "Be brief.", "role": "system"},
        {"content": "Hello", "role": "user"},
    ]

    assert compute_messages_hash(left) == compute_messages_hash(right)


def test_message_hash_changes_when_message_order_changes():
    from app.services.response_registry import compute_messages_hash

    first = [
        {"role": "user", "content": "First"},
        {"role": "assistant", "content": "Second"},
    ]
    second = [
        {"role": "assistant", "content": "Second"},
        {"role": "user", "content": "First"},
    ]

    assert compute_messages_hash(first) != compute_messages_hash(second)


def test_response_registry_registers_and_validates_interaction(tmp_path):
    from app.services.response_registry import ResponseRegistry, compute_messages_hash

    db_path = str(tmp_path / "registry.db")
    registry = ResponseRegistry(db_path)
    messages = [{"role": "user", "content": "What is DejaQ?"}]

    async def run():
        await registry.init()
        interaction = await registry.register(
            org_id=42,
            org_slug="acme",
            department="support",
            cache_namespace="acme__support",
            served_tier="local",
            response_id=None,
            messages=messages,
        )
        found = await registry.get(interaction.interaction_id)
        await registry.close()
        return interaction, found

    interaction, found = asyncio.run(run())

    assert interaction.interaction_id
    assert found is not None
    assert found.org_id == 42
    assert found.org_slug == "acme"
    assert found.department == "support"
    assert found.cache_namespace == "acme__support"
    assert found.served_tier == "local"
    assert found.response_id is None
    assert found.message_hash == compute_messages_hash(messages)


def test_response_registry_ownership_validation(tmp_path):
    from app.services.response_registry import ResponseRegistry

    registry = ResponseRegistry(str(tmp_path / "registry.db"))

    async def run():
        await registry.init()
        interaction = await registry.register(
            org_id=7,
            org_slug="acme",
            department="support",
            cache_namespace="acme__support",
            served_tier="cache",
            response_id="acme__support:doc1",
            messages=[{"role": "user", "content": "Hello"}],
        )
        same_owner = await registry.validate_owner(
            interaction.interaction_id,
            org_id=7,
            org_slug="acme",
            department="support",
        )
        wrong_org = await registry.validate_owner(
            interaction.interaction_id,
            org_id=8,
            org_slug="globex",
            department="support",
        )
        wrong_department = await registry.validate_owner(
            interaction.interaction_id,
            org_id=7,
            org_slug="acme",
            department="sales",
        )
        await registry.close()
        return same_owner, wrong_org, wrong_department

    same_owner, wrong_org, wrong_department = asyncio.run(run())

    assert same_owner is not None
    assert wrong_org is None
    assert wrong_department is None


def test_response_registry_duplicate_escalation_guard(tmp_path):
    from app.services.response_registry import ResponseRegistry

    registry = ResponseRegistry(str(tmp_path / "registry.db"))

    async def run():
        await registry.init()
        interaction = await registry.register(
            org_id=7,
            org_slug="acme",
            department="support",
            cache_namespace="acme__support",
            served_tier="local",
            response_id=None,
            messages=[{"role": "user", "content": "Hello"}],
        )
        first = await registry.acquire_escalation(interaction.interaction_id)
        second = await registry.acquire_escalation(interaction.interaction_id)
        updated = await registry.get(interaction.interaction_id)
        await registry.close()
        return first, second, updated

    first, second, updated = asyncio.run(run())

    assert first is True
    assert second is False
    assert updated is not None
    assert updated.escalation_attempted is True
