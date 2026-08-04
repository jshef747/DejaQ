"""Image-anchored cache hits: validate question-vs-question, skip the adjuster.

Both text models are blind to the image. Observed live: the gate accepted
(token_jaccard 0.991) and the validator still rejected "how to solve?" against
the stored "how to solve this?", because judging an answer against a question
whose subject lives in the picture is underdetermined. The embedding cannot
replace the validator either — numbered-item swaps (0.0867-0.1351) overlap
legitimate paraphrases (0.0753-0.1094).
"""
import asyncio
import base64

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import openai_compat
from app.services.image_text import OcrResult
from app.services.memory_chromaDB import CacheLookupResult
from app.services.validator import ValidatorService
from tests.test_openai_compat_smoke import (
    _AUTH,
    StubAdjuster,
    StubEnricher,
    StubNormalizer,
)

CACHED_ANSWER = "Solve it by substituting u = x^2, then integrating by parts."
TOKENS = frozenset({"integral", "substitution", "142180", "calculus", "exercise"})


@pytest.fixture(autouse=True)
def _stub_api_key(monkeypatch):
    """Autouse fixtures don't cross modules — redeclare it here."""
    from app.middleware.api_key import _KEY_CACHE

    monkeypatch.setattr(
        _KEY_CACHE, "resolve", lambda token: ("demo", 1) if token == "test-key" else None
    )


class CapturingBackend:
    """Records the messages the validator actually sends."""

    def __init__(self, reply: str = "VALID"):
        self.reply = reply
        self.messages: list[dict] = []

    async def complete(self, request):
        self.messages = request.messages
        return self.reply


class ImageHitMemory:
    """A document entry matching TOKENS, close enough to need validation."""

    def lookup_cache(self, clean_query: str):
        return CacheLookupResult(
            hit=True,
            generalized_answer=CACHED_ANSWER,
            entry_id="doc-img",
            distance=0.0753,  # the live false rejection; above VALIDATOR_SKIP_DISTANCE
            matched_query="how to solve this?",
            image_kind="document",
            image_text=" ".join(sorted(TOKENS)),
        )

    def increment_hit_count(self, doc_id: str):
        return None


class RecordingValidator:
    def __init__(self, accept: bool):
        self.accept = accept
        self.kwargs: dict = {}

    async def validate(self, new_query, cached_query, cached_answer, **kwargs):
        self.kwargs = kwargs
        return self.accept, "VALID" if self.accept else "INVALID"


class TrackingAdjuster(StubAdjuster):
    def __init__(self):
        self.adjust_calls: list[str] = []

    async def adjust(self, original_query: str, general_answer: str) -> str:
        self.adjust_calls.append(general_answer)
        return "ADJUSTED — blind rewrite"


def _patch_pipeline(monkeypatch, *, validator, adjuster, memory, ocr):
    async def _noop_log(*a, **k):
        return None

    monkeypatch.setattr(
        openai_compat, "_services_for_model_profile",
        lambda profile: openai_compat.ModelServices(
            normalizer=StubNormalizer(), llm_router=None,
            adjuster=adjuster, enricher=StubEnricher(), validator=validator,
        ),
    )
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: memory)
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)
    monkeypatch.setattr(openai_compat, "extract_image_text", lambda data: ocr)
    monkeypatch.setattr(openai_compat, "USE_CELERY", False)


def _post_image(query: str = "how to solve?"):
    data_url = "data:image/png;base64," + base64.b64encode(b"IMG").decode()
    return TestClient(app, headers=_AUTH).post(
        "/v1/responses",
        json={
            "model": "gpt-4o",
            "input": [{"role": "user", "content": [
                {"type": "input_text", "text": query},
                {"type": "input_image", "image_url": data_url},
            ]}],
            "stream": False,
        },
    )


def _document_ocr() -> OcrResult:
    return OcrResult(TOKENS, word_count=200, mean_confidence=90.0, ok=True)


# --- prompt shape -----------------------------------------------------------

def test_image_mode_compares_questions_and_never_sends_the_answer():
    backend = CapturingBackend()
    ok, _ = asyncio.run(ValidatorService(backend, "m").validate(
        "how to solve?", "how to solve this?", CACHED_ANSWER, attachment_anchored=True,
    ))
    assert ok
    final = backend.messages[-1]["content"]
    assert "CACHED ANSWER" not in final, "image mode must not send the answer"
    assert "how to solve?" in final and "how to solve this?" in final
    # The whole conversation, few-shots included, must stay answer-free.
    assert CACHED_ANSWER not in "".join(m["content"] for m in backend.messages)


def test_text_mode_still_sends_the_answer():
    backend = CapturingBackend()
    asyncio.run(ValidatorService(backend, "m").validate(
        "what is france's capital?", "capital of france", CACHED_ANSWER,
    ))
    final = backend.messages[-1]["content"]
    assert "CACHED ANSWER" in final and CACHED_ANSWER in final


# --- pipeline ---------------------------------------------------------------

def test_image_hit_validates_in_image_mode_and_skips_the_adjuster(monkeypatch):
    validator, adjuster = RecordingValidator(accept=True), TrackingAdjuster()
    _patch_pipeline(
        monkeypatch, validator=validator, adjuster=adjuster,
        memory=ImageHitMemory(), ocr=_document_ocr(),
    )

    response = _post_image()

    assert response.status_code == 200
    assert response.headers["x-dejaq-model-used"] == "cache"
    assert validator.kwargs.get("attachment_anchored") is True
    assert adjuster.adjust_calls == [], "image hits must be served verbatim"
    assert response.json()["output_text"] == CACHED_ANSWER


def test_image_hit_rejected_by_validator_is_not_served(monkeypatch):
    """The sibling case: same image, but 'question 1' vs 'question 2'."""
    validator, adjuster = RecordingValidator(accept=False), TrackingAdjuster()
    _patch_pipeline(
        monkeypatch, validator=validator, adjuster=adjuster,
        memory=ImageHitMemory(), ocr=_document_ocr(),
    )

    response = _post_image("what is the answer to question 2?")

    assert validator.kwargs.get("attachment_anchored") is True
    assert response.headers.get("x-dejaq-model-used") != "cache"
    assert CACHED_ANSWER not in response.text


def test_text_hit_still_adjusts_and_uses_answer_mode(monkeypatch):
    """No image: nothing about the text path changes."""

    class TextHitMemory(ImageHitMemory):
        def lookup_cache(self, clean_query: str):
            return CacheLookupResult(
                hit=True, generalized_answer=CACHED_ANSWER, entry_id="doc-text",
                distance=0.0753, matched_query="how to solve this?",
            )

    validator, adjuster = RecordingValidator(accept=True), TrackingAdjuster()
    _patch_pipeline(
        monkeypatch, validator=validator, adjuster=adjuster,
        memory=TextHitMemory(), ocr=None,
    )

    response = TestClient(app, headers=_AUTH).post(
        "/v1/chat/completions",
        json={"model": "m", "messages": [{"role": "user", "content": "how to solve?"}], "stream": False},
    )

    assert response.status_code == 200
    # Not merely False — the kwarg is omitted so the pipeline's TypeError fallback
    # (which drops mismatch_hint) is never triggered for text validators.
    assert "attachment_anchored" not in validator.kwargs
    assert adjuster.adjust_calls == [CACHED_ANSWER]


def test_short_image_query_is_still_cached(monkeypatch):
    """"solve it" is 2 words — the text filter dropped it, so nothing ever stored.

    Without a stored entry no image can ever hit, which is how a correct gate
    still produced an endless run of misses.
    """
    from app.services import cache_filter

    assert cache_filter.should_cache("solve it", "solve it")[0] is False
    assert cache_filter.should_cache("solve it", "solve it", has_attachment=True)[0] is True
    # The text path is untouched.
    assert cache_filter.should_cache("what is the capital of france", "capital of france")[0] is True
    assert cache_filter.should_cache("thanks", "thanks")[0] is False


def test_no_alias_is_learned_for_an_image_anchored_hit(monkeypatch):
    """The image half of the alias leak — same mechanism as the file half.

    `store_alias` copies the answer and drops every `image_*` field, so an alias
    of an image-anchored entry is a plain text entry that the kind check can no
    longer refuse. Reproduced live: the photo-derived answer was served at
    `x-dejaq-tier: cache` to a request carrying no image at all.
    """

    class BandImageMemory(ImageHitMemory):
        def lookup_cache(self, clean_query: str):
            return CacheLookupResult(
                hit=True,
                generalized_answer=CACHED_ANSWER,
                entry_id="doc-img",
                distance=0.1802,  # in the band, so alias learning is eligible
                matched_query="how to solve this?",
                image_kind="document",
                image_text=" ".join(sorted(TOKENS)),
                requires_validation=True,
            )

    alias_calls: list[tuple] = []

    def _record_alias(namespace, alias_query, source_entry_id):
        alias_calls.append((namespace, alias_query, source_entry_id))

        async def _already_done():
            return None

        return _already_done()

    _patch_pipeline(
        monkeypatch, validator=RecordingValidator(accept=True), adjuster=TrackingAdjuster(),
        memory=BandImageMemory(), ocr=_document_ocr(),
    )
    monkeypatch.setattr(openai_compat, "_store_alias_bg", _record_alias)

    response = _post_image("hwo to slove this?")

    assert response.headers["x-dejaq-model-used"] == "cache"
    assert alias_calls == []
