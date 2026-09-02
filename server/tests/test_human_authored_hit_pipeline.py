"""Serving a human-authored cache hit through the real pipeline.

The promise Edit & Save makes is "byte-identical on the next hit". The context
adjuster is what would break it: it paraphrases a cached answer to match the new
asker's tone, so left on it would serve a 1.5B rewording of text a person
vouched for. These drive the actual endpoint rather than the store, because the
skip lives in the router and a unit test of MemoryService cannot see it.

The distance is deliberately above ADJUSTER_SKIP_DISTANCE: at a near-zero
distance the adjuster is skipped anyway (single-turn), which would let this pass
for the wrong reason.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import openai_compat
from app.services.memory_chromaDB import CacheLookupResult
from tests.test_openai_compat_smoke import (
    _AUTH,
    MarkerAdjuster,
    StubEnricher,
    StubNormalizer,
)

pytestmark = pytest.mark.no_model

HUMAN_ANSWER = "The refund window is 30 days from delivery, not from purchase."


@pytest.fixture(autouse=True)
def _stub_api_key(monkeypatch):
    """Autouse fixtures don't cross modules — redeclare it here."""
    from app.middleware.api_key import _KEY_CACHE

    monkeypatch.setattr(
        _KEY_CACHE, "resolve", lambda token: ("demo", 1) if token == "test-key" else None
    )
    monkeypatch.setattr(_KEY_CACHE, "namespace", lambda *a, **kw: "test-namespace")


class _HitMemory:
    """A trusted-tier hit, far enough out that the adjuster would normally run."""

    def __init__(self, authored: str | None):
        self.authored = authored

    def lookup_cache(self, clean_query: str):
        return CacheLookupResult(
            hit=True,
            generalized_answer=HUMAN_ANSWER,
            entry_id="doc-1",
            # Inside the trusted tier (0.15) but above ADJUSTER_SKIP_DISTANCE
            # (0.075), so adjust() is reached on merit rather than skipped for
            # being a near-identical single-turn repeat.
            distance=0.12,
            matched_query="what is the refund window",
            authored=self.authored,
        )

    def increment_hit_count(self, doc_id: str):
        return None


class _AcceptingValidator:
    """0.12 is inside the trusted tier but above VALIDATOR_SKIP_DISTANCE (0.05),
    so the validator is reached and has to answer."""

    async def validate(self, new_query, cached_query, cached_answer, **kwargs):
        return True, "VALID"


def _patch_pipeline(monkeypatch, memory):
    async def _noop_log(*a, **k):
        return None

    monkeypatch.setattr(
        openai_compat,
        "_services_for_model_profile",
        lambda profile, llm_config=None: openai_compat.ModelServices(
            normalizer=StubNormalizer(),
            llm_router=None,
            adjuster=MarkerAdjuster(),
            enricher=StubEnricher(),
            validator=_AcceptingValidator(),
        ),
    )
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: memory)
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)
    monkeypatch.setattr(openai_compat, "USE_CELERY", False)


def _ask(query: str = "how long is the refund window?"):
    return TestClient(app, headers=_AUTH).post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": query}], "stream": False},
    )


def test_a_human_authored_hit_is_served_byte_identical(monkeypatch):
    _patch_pipeline(monkeypatch, _HitMemory(authored="human"))

    response = _ask()

    assert response.status_code == 200
    content = response.json()["choices"][0]["message"]["content"]
    assert content == HUMAN_ANSWER
    assert "ADJUSTED" not in content


def test_the_same_hit_without_the_flag_is_adjusted(monkeypatch):
    """The control. Without it, the test above would pass even if the skip were
    keyed on something unrelated — or on nothing at all."""
    _patch_pipeline(monkeypatch, _HitMemory(authored=None))

    response = _ask()

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"].startswith("ADJUSTED: ")


def test_a_human_authored_hit_reports_its_provenance(monkeypatch):
    _patch_pipeline(monkeypatch, _HitMemory(authored="human"))

    response = _ask()

    assert response.headers.get("x-dejaq-answer-authored") == "human"


def test_an_ordinary_hit_carries_no_provenance_header(monkeypatch):
    _patch_pipeline(monkeypatch, _HitMemory(authored=None))

    response = _ask()

    assert "x-dejaq-answer-authored" not in response.headers
