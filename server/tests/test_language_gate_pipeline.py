"""The cross-lingual cache leak, end-to-end through /v1/chat/completions.

Reproduces and locks down the regression found in the model-refresh A/B run:
a Hebrew question landing close enough (by embedding distance) to an
English-cached entry was served that English answer verbatim, no
translation, no rejection - because the validator only checks topic
coverage and never checks language, and it and the context adjuster are
both SKIPPED entirely below their respective distance thresholds, so there
was no stage left to catch it on the cases that matter most (the closest,
most "trusted" matches).

The fix lives in the per-candidate gate loop in openai_compat.py, in the
same shape as the image/file/`@`-reference gates: a REJECT falls through to
the next pool candidate, and if nothing survives, the request becomes an
ordinary cache miss and is answered fresh, in its own language. These tests
use ExplodingValidator/MarkerAdjuster to prove the gate runs (and blocks)
*before* either of those stages gets a chance to - including in the
trusted-tier zone where both are normally skipped, which is exactly the
zone the original leak was found in.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import openai_compat
from app.services.memory_chromaDB import CacheLookupResult
from tests.test_openai_compat_smoke import (
    _AUTH,
    ExplodingValidator,
    MarkerAdjuster,
    StubEnricher,
    StubExternalLLM,
    StubHitMemoryVeryClose,
    StubNormalizer,
    StubRouter,
    StubValidatorValid,
)


@pytest.fixture(autouse=True)
def _stub_api_key(monkeypatch):
    from app.middleware.api_key import _KEY_CACHE

    monkeypatch.setattr(
        _KEY_CACHE, "resolve", lambda token: ("demo", 1) if token == "test-key" else None
    )
    monkeypatch.setattr(_KEY_CACHE, "namespace", lambda *a, **kw: "test-namespace")

ENGLISH_ANSWER = "The capital of France is Paris."
HEBREW_ANSWER = "הבירה של צרפת היא פריז."


def _post(question: str):
    return TestClient(app, headers=_AUTH).post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": question}],
            "stream": False,
        },
    )


class EasyClassifier:
    def predict_complexity(self, query: str) -> dict:
        return {"complexity": "easy", "score": 0.0, "task_type": "qa"}


def _patch_for_a_possible_miss(monkeypatch, *, memory, validator, adjuster):
    """Every stub a cache MISS needs to complete successfully - the catch
    case here always resolves as a miss (the gate rejects the only
    candidate), so it has to fall all the way through to local generation."""
    async def _noop_log(*args, **kwargs):
        return None

    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_adjuster", adjuster)
    monkeypatch.setattr(openai_compat, "_validator", validator)
    monkeypatch.setattr(openai_compat, "_llm_router", StubRouter())
    monkeypatch.setattr(openai_compat, "_labse_classifier", EasyClassifier())
    monkeypatch.setattr(openai_compat, "_external_llm", StubExternalLLM())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: memory)
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)
    monkeypatch.setattr(openai_compat.cache_filter, "should_cache", lambda enriched, clean, **kw: (False, "test"))
    monkeypatch.setattr(openai_compat, "USE_CELERY", False)


class HebrewQueryEnglishCachedAnswerMemory:
    """The exact shape of the reproduced leak: a trusted-tier match
    (distance under VALIDATOR_SKIP_DISTANCE) flagged lexically_exact=True -
    which is precisely what makes the PRE-GATE code skip the validator AND
    (single-turn, same distance also under ADJUSTER_SKIP_DISTANCE) the
    adjuster. Before the language gate, nothing downstream would ever have
    looked at what language the cached answer is in."""

    def lookup_cache(self, clean_query: str):
        return CacheLookupResult(
            hit=True,
            generalized_answer=ENGLISH_ANSWER,
            entry_id="doc-en",
            distance=0.001,
            matched_query="what is the capital of france?",
            nearest_distance=0.001,
            nearest_prompt="what is the capital of france?",
            lexically_exact=True,
        )

    def check_cache(self, clean_query: str):
        return None

    def increment_hit_count(self, doc_id: str):
        return None


class HebrewQueryHebrewCachedAnswerMemory:
    """Same shape as above, but the cached answer is ALSO Hebrew - the
    no-break case. Must still serve verbatim from cache."""

    def lookup_cache(self, clean_query: str):
        return CacheLookupResult(
            hit=True,
            generalized_answer=HEBREW_ANSWER,
            entry_id="doc-he",
            distance=0.001,
            matched_query="מה הבירה של צרפת?",
            nearest_distance=0.001,
            nearest_prompt="מה הבירה של צרפת?",
            lexically_exact=True,
        )

    def check_cache(self, clean_query: str):
        return None

    def increment_hit_count(self, doc_id: str):
        return None


class HebrewQueryEnglishCachedAnswerBandMemory:
    """Same leak, but in the validator-guarded band instead of the
    skip-validator trusted zone - proves the gate runs (and blocks) BEFORE
    the validator is ever reached, not just in the one distance regime the
    original leak happened to be measured at."""

    def lookup_cache(self, clean_query: str):
        return CacheLookupResult(
            hit=True,
            generalized_answer=ENGLISH_ANSWER,
            entry_id="doc-en-band",
            distance=0.18,
            matched_query="what is the capital of france?",
            nearest_distance=0.18,
            nearest_prompt="what is the capital of france?",
            requires_validation=True,
        )

    def check_cache(self, clean_query: str):
        return None

    def increment_hit_count(self, doc_id: str):
        return None


def test_hebrew_question_does_not_get_english_cached_answer_verbatim(monkeypatch):
    """The regression itself: reproduced 5 times in the A/B run (2 Hebrew),
    root-caused to the validator never checking language and being skipped
    entirely at this distance. ExplodingValidator proves the fix does not
    rely on the validator to catch this - the gate rejects the candidate
    before the validator (or the adjuster) is ever called."""
    _patch_for_a_possible_miss(
        monkeypatch,
        memory=HebrewQueryEnglishCachedAnswerMemory(),
        validator=ExplodingValidator(),
        adjuster=MarkerAdjuster(),
    )

    response = _post("מה הבירה של צרפת?")

    assert response.status_code == 200
    payload = response.json()
    content = payload["choices"][0]["message"]["content"]
    assert content != ENGLISH_ANSWER
    assert ENGLISH_ANSWER not in content
    assert response.headers["x-dejaq-tier"] != "cache"


def test_hebrew_question_does_not_get_english_cached_answer_from_the_band_either(monkeypatch):
    """Same leak, band tier instead of the skip-validator trusted zone -
    the gate must reject before the (still-exploding) validator is reached
    here too."""
    _patch_for_a_possible_miss(
        monkeypatch,
        memory=HebrewQueryEnglishCachedAnswerBandMemory(),
        validator=ExplodingValidator(),
        adjuster=MarkerAdjuster(),
    )

    response = _post("מה הבירה של צרפת?")

    assert response.status_code == 200
    payload = response.json()
    content = payload["choices"][0]["message"]["content"]
    assert content != ENGLISH_ANSWER
    assert ENGLISH_ANSWER not in content
    assert response.headers["x-dejaq-tier"] != "cache"


def test_hebrew_question_still_hits_a_hebrew_cached_answer(monkeypatch):
    """Must-not-break case 1: same-script (Hebrew/Hebrew) trusted-tier hit
    is untouched by the gate - still served verbatim from cache, validator
    and adjuster both still correctly skipped."""
    async def _noop_log(*args, **kwargs):
        return None

    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_adjuster", MarkerAdjuster())
    monkeypatch.setattr(openai_compat, "_validator", ExplodingValidator())
    monkeypatch.setattr(
        openai_compat, "get_memory_service", lambda namespace: HebrewQueryHebrewCachedAnswerMemory()
    )
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)

    response = _post("מה הבירה של צרפת?")

    assert response.status_code == 200
    payload = response.json()
    assert payload["choices"][0]["message"]["content"] == HEBREW_ANSWER
    assert response.headers["x-dejaq-tier"] == "cache"


def test_english_question_still_hits_an_english_cached_answer(monkeypatch):
    """Must-not-break case 2: same-script (English/English) trusted-tier
    hit is untouched by the gate. Reuses the existing StubHitMemoryVeryClose
    fixture - same scenario test_adjust_skipped_for_close_single_turn_repeat
    already covers, asserted here explicitly as part of this gate's own
    regression coverage rather than only incidentally."""
    async def _noop_log(*args, **kwargs):
        return None

    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_adjuster", MarkerAdjuster())
    monkeypatch.setattr(openai_compat, "_validator", ExplodingValidator())
    monkeypatch.setattr(
        openai_compat, "get_memory_service", lambda namespace: StubHitMemoryVeryClose()
    )
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)

    response = _post("what is teh capitol of frnace?")

    assert response.status_code == 200
    payload = response.json()
    assert payload["choices"][0]["message"]["content"] == "Cached Paris answer."
    assert response.headers["x-dejaq-tier"] == "cache"


def test_band_hit_with_matching_script_is_unaffected_by_the_gate(monkeypatch):
    """Must-not-break, band tier: a same-script band candidate must still
    reach and be served through the validator exactly as before - the gate
    only rejects on a genuine script disagreement."""
    async def _noop_log(*args, **kwargs):
        return None

    class EnglishBandMemory:
        def lookup_cache(self, clean_query: str):
            return CacheLookupResult(
                hit=True,
                generalized_answer=ENGLISH_ANSWER,
                entry_id="doc-en-band-ok",
                distance=0.18,
                matched_query="what is the capital of france?",
                nearest_distance=0.18,
                nearest_prompt="what is the capital of france?",
                requires_validation=True,
            )

        def check_cache(self, clean_query: str):
            return None

        def increment_hit_count(self, doc_id: str):
            return None

    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_adjuster", MarkerAdjuster())
    monkeypatch.setattr(openai_compat, "_validator", StubValidatorValid())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: EnglishBandMemory())
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)

    response = _post("what's the capital of france anyway?")

    assert response.status_code == 200
    payload = response.json()
    assert payload["choices"][0]["message"]["content"] == "ADJUSTED: " + ENGLISH_ANSWER
    assert response.headers["x-dejaq-tier"] == "cache"
