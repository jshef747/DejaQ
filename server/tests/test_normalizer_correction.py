"""Model-free tests for NormalizerService.normalize_ex correction-probe logic.

These don't touch the LLM: the passthrough path never calls the backend, and the
opinion path is driven by a fake backend. Kept out of test_normalizer.py so they
don't inherit that file's `qwen` marker.
"""

import asyncio

import pytest

import app.services.normalizer as normalizer_mod
from app.services.normalizer import NormalizerService, NormalizedQuery

pytestmark = pytest.mark.no_model


class _FakeBackend:
    def __init__(self, reply: str = "best pillow") -> None:
        self.reply = reply
        self.calls = 0

    async def complete(self, request) -> str:
        self.calls += 1
        return self.reply


def _svc(reply: str = "best pillow") -> NormalizerService:
    return NormalizerService(backend=_FakeBackend(reply), model_name="fake")


def test_corrected_key_set_when_correction_changes(monkeypatch):
    monkeypatch.setattr(normalizer_mod, "_spell_correct", lambda q: "how to receive mail")
    svc = _svc()
    result = asyncio.run(svc.normalize_ex("how to recieve mail"))
    assert isinstance(result, NormalizedQuery)
    assert result.cache_key == "how to recieve mail"
    assert result.corrected_key == "how to receive mail"


def test_corrected_key_none_when_no_change(monkeypatch):
    monkeypatch.setattr(normalizer_mod, "_spell_correct", lambda q: q)
    svc = _svc()
    result = asyncio.run(svc.normalize_ex("capital of japan"))
    assert result.cache_key == "capital of japan"
    assert result.corrected_key is None


def test_corrected_key_ignores_case_only_diff(monkeypatch):
    # Correction that only differs in case must not create a redundant second probe.
    monkeypatch.setattr(normalizer_mod, "_spell_correct", lambda q: "Capital Of Japan")
    svc = _svc()
    result = asyncio.run(svc.normalize_ex("capital of japan"))
    assert result.cache_key == "capital of japan"
    assert result.corrected_key is None


def test_opinion_path_has_no_corrected_key():
    backend = _FakeBackend(reply="best pillow")
    svc = NormalizerService(backend=backend, model_name="fake")
    result = asyncio.run(svc.normalize_ex("what is the best pillow to buy"))
    assert result.cache_key == "best pillow"
    assert result.corrected_key is None
    assert backend.calls == 1  # opinion rewrite invoked the LLM


def test_normalize_returns_cache_key_string(monkeypatch):
    monkeypatch.setattr(normalizer_mod, "_spell_correct", lambda q: q)
    svc = _svc()
    out = asyncio.run(svc.normalize("Hello World"))
    assert out == "hello world"
