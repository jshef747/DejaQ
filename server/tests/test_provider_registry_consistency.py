"""Fails when any of the five hand-written provider/model lists drifts from
`app.services.provider_registry`.

`dashboard/lib/types.ts` still declares its own `LIVE_PROVIDERS` list, read
with a small regex extractor rather than a real TS parser - proportionate for
one small literal list. `dashboard/lib/external-models.ts` is gone as of
piece 1e (the dashboard now fetches its model catalogue from `GET
/admin/v1/providers`), so there is nothing left to check it against.

The `workspace_provider_credentials` CHECK constraint used to be a sixth
mirror checked here; it was dropped (migration e5f6a7b8c9d0) because this
registry already validates provider names in Python, so there is nothing left
to assert against it.
"""

import re
from pathlib import Path

import pytest

from app.schemas.credentials import ProviderEnum
from app.services import provider_registry
from app.services.credential_service import SUPPORTED_PROVIDERS
from app.services.external_llm import _PROVIDER_CLIENTS
from app.services.llm_providers import LIVE_PROVIDERS

pytestmark = pytest.mark.no_model

DASHBOARD_LIB = Path(__file__).resolve().parents[2] / "dashboard" / "lib"


def _extract_ts_live_providers() -> set[str]:
    """Provider values out of `export const LIVE_PROVIDERS: Provider[] = [...]`."""
    text = (DASHBOARD_LIB / "types.ts").read_text()
    match = re.search(r"LIVE_PROVIDERS:\s*Provider\[\]\s*=\s*\[([^\]]*)\]", text)
    assert match, "could not find LIVE_PROVIDERS array in dashboard/lib/types.ts"
    return set(re.findall(r'"(\w+)"', match.group(1)))


def test_live_providers_match_client_wiring():
    registry_live = provider_registry.live_providers()
    assert registry_live == set(_PROVIDER_CLIENTS.keys())
    assert registry_live == LIVE_PROVIDERS


def test_known_providers_match_credential_surfaces():
    registry_known = provider_registry.known_providers()
    assert registry_known == SUPPORTED_PROVIDERS
    assert registry_known == {member.value for member in ProviderEnum}


def test_dashboard_live_providers_match_registry():
    assert provider_registry.live_providers() == _extract_ts_live_providers()
