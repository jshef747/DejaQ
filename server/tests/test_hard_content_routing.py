"""Hard-content routing: file and OCR-document-image attachments are judged by
the local model instead of always answering "easy" once they fit the local
context window - see _judge_hard_content / _HARD_CONTENT_JUDGE_SYSTEM_PROMPT
in app/routers/openai_compat.py.

These tests are about the ROUTING DECISION, not the judge model itself - the
judge is mocked throughout (either by monkeypatching _judge_hard_content
directly to control its verdict, or by driving _judge_hard_content itself
with a stub router, when the point of the test IS its own parsing/fallback
behavior). No real Ollama call happens here.
"""
import asyncio
import base64

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.main import app
from app.routers import openai_compat
from app.schemas.chat import ExternalLLMResponse
from app.services.image_text import OcrResult
from tests.conftest import StreamingLocalRouterMixin
from tests.test_openai_compat_smoke import (
    _AUTH,
    StubAdjuster,
    StubEnricher,
    StubNormalizer,
    stored_credential,
)

pytestmark = pytest.mark.no_model

QUESTION = "what does this say?"
LOCAL_ANSWER = "It's a lunch schedule."

# Comfortably under any plausible local-answering budget, same shape as the
# size-guard tests - large enough to clear CACHE_FILE_MIN_CHARS, small enough
# to always fit.
SMALL_FILE = b"Lunch is served at noon. " * 5

# A real photo (or ambiguous low-confidence OCR) must never reach the judge -
# only a confident OCR'd document does.
PHOTO_OCR = OcrResult(frozenset(), word_count=0, mean_confidence=0.0, ok=True)
DOCUMENT_OCR = OcrResult(
    frozenset(f"word{i}" for i in range(10)), word_count=200, mean_confidence=90.0, ok=True
)
IMAGE_BYTES = b"\x89PNG\r\n\x1a\nfake-but-good-enough-for-a-mock"


@pytest.fixture(autouse=True)
def _stub_api_key(monkeypatch):
    from app.middleware.api_key import _KEY_CACHE

    monkeypatch.setattr(
        _KEY_CACHE, "resolve", lambda token: ("demo", 1) if token == "test-key" else None
    )
    monkeypatch.setattr(_KEY_CACHE, "namespace", lambda *a, **kw: "test-namespace")


class _NoHitMemory:
    def lookup_cache(self, clean_query: str):
        from app.services.memory_chromaDB import CacheLookupResult

        return CacheLookupResult(hit=False)

    def store_interaction(self, *a, **k):
        return "id"

    def increment_hit_count(self, doc_id: str):
        return None

    def count_file_entries(self, file_sha: str) -> int:
        return 0


class StubRouter(StreamingLocalRouterMixin):
    """Records how many times local generation actually ran."""

    def __init__(self, answer: str = LOCAL_ANSWER):
        self.answer = answer
        self.calls = 0

    async def generate_local_response(self, query, history=None, max_tokens=1024, system_prompt=None, images=None):
        self.calls += 1
        return self.answer, 12.0, "stop"


class CapturingExternalLLM:
    def __init__(self):
        self.request = None

    async def generate_response(self, request, provider=None, api_key=None):
        self.request = request
        return ExternalLLMResponse(
            text="answered externally", model_used=request.model,
            prompt_tokens=5, completion_tokens=6, latency_ms=10.0,
        )


class ExplodingExternalLLM:
    async def generate_response(self, request, provider=None, api_key=None):
        raise AssertionError("external route must not be used for a locally-judged-easy request")


def _judge_must_not_be_called(*a, **k):
    raise AssertionError("the hard-content judge must not run here")


def _patch_pipeline(
    monkeypatch, router, *,
    external=None, external_model=None, judge_result=None,
    supports_vision=True, skip_judge=False, judge_fn=None,
    local_attachment_max_tokens=None, ollama_num_ctx=None,
    attachment_routing=None,
):
    async def _noop_log(*a, **k):
        return None

    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_adjuster", StubAdjuster())
    monkeypatch.setattr(openai_compat, "_llm_router", router)
    monkeypatch.setattr(openai_compat, "_external_llm", external or ExplodingExternalLLM())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: _NoHitMemory())
    monkeypatch.setattr(
        openai_compat.ollama_catalog, "supports_vision", lambda model, force_refresh=False: supports_vision
    )
    _config_kwargs = {"external_model": external_model, "routing_threshold": 0.9}
    if local_attachment_max_tokens is not None:
        _config_kwargs["local_attachment_max_tokens"] = local_attachment_max_tokens
    if ollama_num_ctx is not None:
        _config_kwargs["ollama_num_ctx"] = ollama_num_ctx
    if attachment_routing is not None:
        _config_kwargs["attachment_routing"] = attachment_routing
    monkeypatch.setattr(
        openai_compat,
        "_read_effective_llm_config",
        lambda workspace_slug, workspace_id: openai_compat.EffectiveLlmConfig(**_config_kwargs),
    )
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)
    monkeypatch.setattr(openai_compat.cache_filter, "should_cache", lambda enriched, clean, **kw: (False, "test"))
    monkeypatch.setattr(openai_compat, "USE_CELERY", False)
    if external_model is not None:
        monkeypatch.setattr("app.config.CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())
        monkeypatch.setattr(
            openai_compat, "get_workspace_provider_key",
            stored_credential("sk-ant-live", providers=("anthropic",)),
        )
    if skip_judge:
        monkeypatch.setattr(openai_compat, "_judge_hard_content", _judge_must_not_be_called)
    elif judge_fn is not None:
        monkeypatch.setattr(openai_compat, "_judge_hard_content", judge_fn)
    elif judge_result is not None:
        async def _fake_judge(llm_router, judge_text, system_prompt=None):
            return judge_result

        monkeypatch.setattr(openai_compat, "_judge_hard_content", _fake_judge)


def _post_file(query: str, data: bytes, *, filename: str = "doc.txt", mime: str = "text/plain"):
    part = {
        "type": "input_file",
        "filename": filename,
        "file_data": f"data:{mime};base64," + base64.b64encode(data).decode(),
    }
    return TestClient(app, headers=_AUTH).post(
        "/v1/responses",
        json={
            "model": "gpt-4o",
            "input": [{"role": "user", "content": [{"type": "input_text", "text": query}, part]}],
            "stream": False,
        },
    )


def _post_image(query: str, image: bytes = IMAGE_BYTES, *, mime: str = "image/png"):
    content = [
        {"type": "input_text", "text": query},
        {"type": "input_image", "image_url": f"data:{mime};base64," + base64.b64encode(image).decode()},
    ]
    return TestClient(app, headers=_AUTH).post(
        "/v1/responses",
        json={"model": "gpt-4o", "input": [{"role": "user", "content": content}], "stream": False},
    )


# --- _judge_hard_content itself: parsing and failure-mode behavior ---------

def test_judge_hard_content_parses_a_hard_verdict():
    class HardRouter:
        async def generate_local_response(self, *a, **k):
            return "HARD", 5.0, "stop"

    result = asyncio.run(openai_compat._judge_hard_content(HardRouter(), "some text"))
    assert result is True


def test_judge_hard_content_parses_an_easy_verdict():
    class EasyRouter:
        async def generate_local_response(self, *a, **k):
            return "EASY", 5.0, "stop"

    result = asyncio.run(openai_compat._judge_hard_content(EasyRouter(), "some text"))
    assert result is False


def test_judge_hard_content_defaults_to_easy_on_exception():
    """Judge failure is not a request failure - it defaults to the cheap
    direction (easy, routes local), never propagates."""

    class ExplodingRouter:
        async def generate_local_response(self, *a, **k):
            raise RuntimeError("Ollama unreachable")

    result = asyncio.run(openai_compat._judge_hard_content(ExplodingRouter(), "some text"))
    assert result is False


def test_judge_hard_content_defaults_to_easy_on_unparseable_answer():
    class RamblingRouter:
        async def generate_local_response(self, *a, **k):
            return "uh, this is kind of tricky to say", 5.0, "stop"

    result = asyncio.run(openai_compat._judge_hard_content(RamblingRouter(), "some text"))
    assert result is False


# --- Pipeline-level routing: file ------------------------------------------

def test_file_judged_hard_routes_external(monkeypatch):
    router = StubRouter()
    external = CapturingExternalLLM()
    _patch_pipeline(monkeypatch, router, external=external, external_model="claude-sonnet-4-6", judge_result=True)

    resp = _post_file(QUESTION, SMALL_FILE)

    assert resp.status_code == 200
    assert resp.json()["output_text"] == "answered externally"
    assert router.calls == 0, "local generation must never run once the judge says hard"
    assert external.request is not None


def test_file_judged_easy_routes_local(monkeypatch):
    router = StubRouter()
    _patch_pipeline(monkeypatch, router, judge_result=False)

    resp = _post_file(QUESTION, SMALL_FILE)

    assert resp.status_code == 200
    assert resp.json()["output_text"] == LOCAL_ANSWER
    assert router.calls == 1


def test_oversized_file_routes_external_without_ever_calling_the_judge(monkeypatch):
    """The size gate still runs first: a file too large for the local context
    window goes external on size alone, exactly as before this change - the
    judge (an extra Ollama round trip) must not run for a request that was
    always going external regardless of content difficulty."""
    router = StubRouter()
    external = CapturingExternalLLM()
    _patch_pipeline(monkeypatch, router, external=external, external_model="claude-sonnet-4-6", skip_judge=True)

    large_file = b"filler " * 200_000
    resp = _post_file(QUESTION, large_file, filename="large.txt")

    assert resp.status_code == 200
    assert resp.json()["output_text"] == "answered externally"
    assert router.calls == 0


# --- Pipeline-level routing: image ------------------------------------------

def test_document_image_judged_hard_routes_external(monkeypatch):
    router = StubRouter()
    external = CapturingExternalLLM()
    monkeypatch.setattr(openai_compat, "extract_image_text", lambda data: DOCUMENT_OCR)
    monkeypatch.setattr(openai_compat, "ocr_image_plaintext", lambda data: "some ocr'd document text")
    # Images default to the "local" route (skip judge); map png -> "auto" so the
    # content-difficulty judge runs, which is what this test is about.
    _patch_pipeline(
        monkeypatch, router, external=external, external_model="claude-sonnet-4-6",
        judge_result=True, attachment_routing={"png": "auto"},
    )

    resp = _post_image(QUESTION)

    assert resp.status_code == 200
    assert resp.json()["output_text"] == "answered externally"
    assert router.calls == 0


def test_document_image_judged_easy_routes_local(monkeypatch):
    router = StubRouter()
    monkeypatch.setattr(openai_compat, "extract_image_text", lambda data: DOCUMENT_OCR)
    monkeypatch.setattr(openai_compat, "ocr_image_plaintext", lambda data: "some ocr'd document text")
    # png -> "auto" so the judge actually runs (default is "local", skip judge).
    _patch_pipeline(monkeypatch, router, judge_result=False, attachment_routing={"png": "auto"})

    resp = _post_image(QUESTION)

    assert resp.status_code == 200
    assert resp.json()["output_text"] == LOCAL_ANSWER
    assert router.calls == 1


def test_non_document_image_path_unchanged(monkeypatch):
    """A photo (or an ambiguous low-confidence OCR read) has no reliable text
    to judge - the judge must not run at all, and routing stays exactly what
    it was before this change: local, whenever the local model can see."""
    router = StubRouter()
    monkeypatch.setattr(openai_compat, "extract_image_text", lambda data: PHOTO_OCR)
    _patch_pipeline(monkeypatch, router, skip_judge=True)

    resp = _post_image(QUESTION)

    assert resp.status_code == 200
    assert resp.json()["output_text"] == LOCAL_ANSWER
    assert router.calls == 1


# --- Chunked judging --------------------------------------------------------

def test_chunk_for_judge_leaves_a_short_document_as_one_chunk():
    assert openai_compat._chunk_for_judge("short text") == ["short text"]


def test_chunk_for_judge_splits_a_long_document_with_overlap():
    import string

    alphabet = string.ascii_lowercase
    text = "".join(alphabet[i % len(alphabet)] for i in range(25_000))
    chunks = openai_compat._chunk_for_judge(text)
    assert len(chunks) > 1
    assert all(len(c) <= openai_compat._JUDGE_CHUNK_CHARS for c in chunks)
    # consecutive chunks overlap by exactly the configured amount, at the
    # correct absolute position (non-repeating content makes this a real
    # positional check, not just "the same character shows up twice")
    assert chunks[0][-openai_compat._JUDGE_CHUNK_OVERLAP_CHARS:] == \
        chunks[1][:openai_compat._JUDGE_CHUNK_OVERLAP_CHARS]


def _marker_only_in_last_chunk_doc():
    """A document long enough to need 2 judge chunks, with a marker placed so
    it lands only in the LAST chunk - built against the real _chunk_for_judge
    so the placement is verified, not hand-computed."""
    filler = ("This is routine memo filler text. " * 600)[:18_000]
    # 15,000 is past chunk 0's end (12,000) and the shared overlap zone
    # (10,000-12,000), so it is only ever visible to chunk 1.
    text = filler[:15_000] + " MARKERHARD " + filler[15_000:]
    chunks = openai_compat._chunk_for_judge(text)
    assert len(chunks) == 2, "test needs a document producing exactly 2 chunks"
    assert "MARKERHARD" not in chunks[0]
    assert "MARKERHARD" in chunks[-1]
    return text


async def _judge_on_marker(llm_router, judge_text, system_prompt=None):
    return "MARKERHARD" in judge_text


def test_multi_slice_file_with_hard_content_only_in_the_last_slice_routes_external(monkeypatch):
    text = _marker_only_in_last_chunk_doc()
    router = StubRouter()
    external = CapturingExternalLLM()
    _patch_pipeline(
        monkeypatch, router, external=external, external_model="claude-sonnet-4-6",
        judge_fn=_judge_on_marker, local_attachment_max_tokens=1_000_000, ollama_num_ctx=1_000_000,
    )

    resp = _post_file(QUESTION, text.encode())

    assert resp.status_code == 200
    assert resp.json()["output_text"] == "answered externally"
    assert router.calls == 0, "local generation must never run once any slice judges hard"


def test_multi_slice_file_with_no_hard_slice_routes_local(monkeypatch):
    """False-positive check on the chunked path: an ordinary long document,
    no marker anywhere, must still route local - chunking must not itself
    introduce false alarms on ordinary long text."""
    filler = ("This is routine memo filler text. " * 1000)[:32_000]
    chunks = openai_compat._chunk_for_judge(filler)
    assert len(chunks) >= 3, "test needs a document producing at least 3 chunks"
    router = StubRouter()
    _patch_pipeline(
        monkeypatch, router, judge_fn=_judge_on_marker,
        local_attachment_max_tokens=1_000_000, ollama_num_ctx=1_000_000,
    )

    resp = _post_file(QUESTION, filler.encode())

    assert resp.status_code == 200
    assert resp.json()["output_text"] == LOCAL_ANSWER
    assert router.calls == 1


def test_single_slice_file_makes_exactly_one_judge_call(monkeypatch):
    """A document small enough to fit one chunk must behave exactly as before
    chunking existed: one judge call, not a chunking pass over a 1-item list."""
    calls = []

    async def _counting_judge(llm_router, judge_text, system_prompt=None):
        calls.append(judge_text)
        return False

    router = StubRouter()
    _patch_pipeline(monkeypatch, router, judge_fn=_counting_judge)

    resp = _post_file(QUESTION, SMALL_FILE)

    assert resp.status_code == 200
    assert len(calls) == 1


# --- Configurable local-answer size cap -------------------------------------

def test_file_above_the_attachment_cap_routes_external_without_judge_call(monkeypatch):
    """Above LOCAL_ATTACHMENT_MAX_TOKENS (here overridden low), a file routes
    external on the existing oversized-file path and the judge - an extra
    Ollama round trip - must never run, even though the file would easily
    fit the (large, default) context window."""
    router = StubRouter()
    external = CapturingExternalLLM()
    # ~1000 chars comfortably exceeds a 50-token (~150 char) cap.
    text = ("Lunch is served at noon. " * 40).encode()
    _patch_pipeline(
        monkeypatch, router, external=external, external_model="claude-sonnet-4-6",
        skip_judge=True, local_attachment_max_tokens=50,
    )

    resp = _post_file(QUESTION, text)

    assert resp.status_code == 200
    assert resp.json()["output_text"] == "answered externally"
    assert router.calls == 0


def test_file_under_the_default_attachment_cap_still_reaches_the_judge(monkeypatch):
    """Control for the test above: the same-shaped request, no cap override,
    must reach the judge normally - the cap is doing the work above, not an
    unrelated size check."""
    router = StubRouter()
    text = ("Lunch is served at noon. " * 40).encode()
    _patch_pipeline(monkeypatch, router, judge_result=False)

    resp = _post_file(QUESTION, text)

    assert resp.status_code == 200
    assert resp.json()["output_text"] == LOCAL_ANSWER
    assert router.calls == 1


def test_local_attachment_cap_respects_a_per_workspace_override(monkeypatch):
    """A file that exceeds the SHIPPED DEFAULT cap (routes external, judge
    skipped) must reach the judge and answer locally once a workspace raises
    its own override past the file's size - proves the override is actually
    read, not just the global default."""
    from app.config import LOCAL_ATTACHMENT_MAX_TOKENS

    # Sized to exceed the shipped default cap on estimated tokens (len // 3)
    # but comfortably clear a raised override.
    oversized_for_default = "x " * (LOCAL_ATTACHMENT_MAX_TOKENS * 2)
    assert len(oversized_for_default) // 3 > LOCAL_ATTACHMENT_MAX_TOKENS

    router_default = StubRouter()
    _patch_pipeline(monkeypatch, router_default, skip_judge=True)
    resp_default = _post_file(QUESTION, oversized_for_default.encode(), filename="a.txt")
    assert resp_default.status_code == 422  # no external credential; hard/oversized path
    assert router_default.calls == 0

    router_override = StubRouter()
    _patch_pipeline(
        monkeypatch, router_override, judge_result=False,
        local_attachment_max_tokens=LOCAL_ATTACHMENT_MAX_TOKENS * 10,
    )
    resp_override = _post_file(QUESTION, oversized_for_default.encode(), filename="b.txt")
    assert resp_override.status_code == 200
    assert resp_override.json()["output_text"] == LOCAL_ANSWER
    assert router_override.calls == 1
