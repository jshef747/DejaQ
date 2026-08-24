"""Stage 5: image requests answered by the local model when it can see.

Before this change, `_request_has_image` unconditionally forced the "hard"
(external) route (openai_compat.py, the `if _request_has_image:` branch) -
Stage 3's capability lookup (ollama_catalog.supports_vision) and Stage 4's
image plumbing (LLMRouterService/model_backends `images` param) both already
existed but nothing joined them. This proves the join: the classification
step now asks capability, routes local when it says yes, keeps the
`hard_external` override as a policy ceiling above it, and translates
Ollama's own rejection of a capability-mismatched local call into a specific
error instead of the generic apology - the safety net for the window between
here and a stale capability-cache read.
"""
import base64

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import openai_compat
from app.services.image_text import OcrResult
from app.services.model_backends import LocalVisionUnsupportedError
from tests.conftest import StreamingLocalRouterMixin
from tests.test_openai_compat_smoke import (
    _AUTH,
    StubAdjuster,
    StubEnricher,
    StubNormalizer,
)

pytestmark = pytest.mark.no_model

IMAGE_BYTES = b"\x89PNG\r\n\x1a\nfake-but-good-enough-for-a-mock"
QUESTION = "what shapes and colors do you see?"
ANSWER = "Blue square, red circle."

# Document-kind OCR result (confidence/word floor both cleared) so the gate
# never reaches for the real CLIP fingerprinter - no torch model load needed.
DOCUMENT_OCR = OcrResult(
    frozenset(f"word{i}" for i in range(10)), word_count=200, mean_confidence=90.0, ok=True
)


@pytest.fixture(autouse=True)
def _stub_api_key(monkeypatch):
    from app.middleware.api_key import _KEY_CACHE

    monkeypatch.setattr(
        _KEY_CACHE, "resolve", lambda token: ("demo", 1) if token == "test-key" else None
    )


class _NoHitMemory:
    def lookup_cache(self, clean_query: str):
        from app.services.memory_chromaDB import CacheLookupResult

        return CacheLookupResult(hit=False)

    def store_interaction(self, *a, **k):
        raise AssertionError("a failed/rejected generation must never be cached")


class VisionCapturingRouter(StreamingLocalRouterMixin):
    """Stand-in local model: records whether/what images it was called with,
    so a passing test proves the bytes actually reached local generation -
    not just that the endpoint returned 200."""

    def __init__(self, answer: str = ANSWER):
        self.answer = answer
        self.last_images: list[str] | None = None
        self.calls = 0

    async def generate_local_response(
        self, query, history=None, max_tokens=1024, system_prompt=None, images=None, temperature=0.7
    ):
        self.calls += 1
        self.last_images = images
        return self.answer, 12.0, "stop"


class RejectingRouter:
    """Simulates the day-2-drift case: the capability cache said the model
    could see, but Ollama itself rejects the call - the model was swapped
    out from under the workspace after the last cache refresh."""

    async def generate_local_response(self, query, history=None, max_tokens=1024, system_prompt=None, images=None):
        raise LocalVisionUnsupportedError(
            "qwen2.5:1.5b",
            "Multimodal data provided, but model does not support multimodal requests.",
        )


class StreamingRejectingRouter:
    """Same day-2-drift rejection as RejectingRouter, but on the streaming
    call - the only path the real chat app (which always streams) uses."""

    def __init__(self, detail: str = "Multimodal data provided, but model does not support multimodal requests."):
        self.detail = detail

    async def stream_local_response(self, query, history=None, max_tokens=1024, system_prompt=None, images=None):
        raise LocalVisionUnsupportedError("qwen2.5:1.5b", self.detail)
        yield  # pragma: no cover - never reached, makes this an async generator


class ExplodingExternalLLM:
    async def generate_response(self, request, provider=None, api_key=None):
        raise AssertionError("external route must not be used when the local model can see")

    async def stream_response(self, request, provider=None, api_key=None):
        raise AssertionError("external route must not be used when the local model can see")
        yield  # pragma: no cover - never reached, makes this an async generator


def _patch_pipeline(monkeypatch, router, *, external_model: str | None = None, supports_vision: bool = True):
    async def _noop_log(*a, **k):
        return None

    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_adjuster", StubAdjuster())
    monkeypatch.setattr(openai_compat, "_llm_router", router)
    monkeypatch.setattr(openai_compat, "_external_llm", ExplodingExternalLLM())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: _NoHitMemory())
    monkeypatch.setattr(
        openai_compat, "extract_image_text", lambda data: DOCUMENT_OCR
    )
    # The hard-content judge's own OCR pass (image_text.ocr_plaintext) is a
    # second, separate tesseract call from extract_image_text above - stub it
    # too so these tests don't depend on real OCR of a fake PNG.
    monkeypatch.setattr(openai_compat, "ocr_image_plaintext", lambda data: "some ordinary document text")
    monkeypatch.setattr(
        openai_compat.ollama_catalog, "supports_vision", lambda model, force_refresh=False: supports_vision
    )
    monkeypatch.setattr(
        openai_compat,
        "_read_effective_llm_config",
        lambda workspace_slug, workspace_id: openai_compat.EffectiveLlmConfig(
            external_model=external_model, routing_threshold=0.9,
        ),
    )
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)
    monkeypatch.setattr(openai_compat.cache_filter, "should_cache", lambda enriched, clean, **kw: (False, "test"))
    monkeypatch.setattr(openai_compat, "USE_CELERY", False)


def _post_image(
    query: str, image: bytes = IMAGE_BYTES, *, mime: str = "image/png",
    headers: dict | None = None, stream: bool = False,
):
    content = [
        {"type": "input_text", "text": query},
        {"type": "input_image", "image_url": f"data:{mime};base64," + base64.b64encode(image).decode()},
    ]
    req_headers = dict(_AUTH)
    req_headers.update(headers or {})
    return TestClient(app, headers=req_headers).post(
        "/v1/responses",
        json={"model": "gpt-4o", "input": [{"role": "user", "content": content}], "stream": stream},
    )


def _sse_events(response) -> list[dict]:
    """Parse `data:` payloads out of an SSE body."""
    import json

    return [
        json.loads(line[len("data: "):])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


def test_image_answered_locally_with_no_external_credential(monkeypatch, caplog):
    """The headline case: a vision-capable local model, no external credential
    configured at all - proves the feature and proves it needs no provider key."""
    router = VisionCapturingRouter()
    _patch_pipeline(monkeypatch, router, external_model=None, supports_vision=True)

    with caplog.at_level("INFO", logger="dejaq.router.openai_compat"):
        resp = _post_image(QUESTION)

    assert resp.status_code == 200
    assert resp.json()["output_text"] == ANSWER
    assert resp.headers["x-dejaq-model-used"] == openai_compat.LOCAL_LLM_MODEL_NAME
    # 2 calls: the hard-content judge on the OCR'd text, then generation. The
    # stub answers every call with ANSWER, which doesn't parse as HARD, so the
    # judge defaults to easy and the route stays local - same outcome as
    # before the judge existed, just one extra call to reach it.
    assert router.calls == 2
    assert router.last_images == [base64.b64encode(IMAGE_BYTES).decode("ascii")], (
        "the image bytes must reach the local generation call"
    )

    done_line = next(
        r.message for r in caplog.records
        if r.name == "dejaq.router.openai_compat" and r.message.startswith("done cache=miss")
    )
    assert "route=local" in done_line


def test_hard_external_override_forces_external_even_when_local_model_can_see(monkeypatch):
    """Regression: the explicit routing-mode override remains a policy ceiling
    above image capability, exactly as it already is for files and text."""
    router = VisionCapturingRouter()
    _patch_pipeline(monkeypatch, router, external_model=None, supports_vision=True)

    resp = _post_image(QUESTION, headers={"X-DejaQ-Routing-Mode": "hard_external"})

    assert resp.status_code == 422  # no external credential configured either
    assert router.calls == 0


def test_text_only_local_model_still_routes_external(monkeypatch):
    """When the capability lookup says no, behavior is unchanged from before
    this stage: external, exactly as every image request used to route."""
    router = VisionCapturingRouter()
    _patch_pipeline(monkeypatch, router, external_model=None, supports_vision=False)

    resp = _post_image(QUESTION)

    assert resp.status_code == 422  # no external credential configured
    assert router.calls == 0


def test_local_vision_mismatch_surfaces_a_specific_error_not_the_generic_apology(monkeypatch, caplog):
    """The safety net: capability said yes (cache stale), Ollama disagrees at
    call time. Caller must get a clear, specific error naming the real cause -
    not the generic "I'm sorry, I couldn't process your request" - and nothing
    gets cached (_NoHitMemory.store_interaction asserts this on its own)."""
    router = RejectingRouter()
    _patch_pipeline(monkeypatch, router, external_model=None, supports_vision=True)

    resp = _post_image(QUESTION)

    assert resp.status_code == 422
    detail = resp.json()["detail"] if "detail" in resp.json() else resp.text
    assert "does not support image input" in detail
    assert "qwen2.5:1.5b" in detail
    assert "I'm sorry" not in detail


def test_local_vision_mismatch_does_not_only_blame_capability_for_a_malformed_image(monkeypatch):
    """Defect: the message always said "does not support image input", even
    when Ollama's own text (a 400/500 on any image-bearing call is matched
    defensively, per LocalVisionUnsupportedError's docstring) says the image
    itself could not be loaded - a clear message pointing at the wrong cause.
    The real Ollama text must survive into the surfaced detail."""
    class MalformedImageRouter:
        async def generate_local_response(self, query, history=None, max_tokens=1024, system_prompt=None, images=None):
            raise LocalVisionUnsupportedError(
                "gemma4:e4b", "Failed to load image or audio file",
            )

    _patch_pipeline(monkeypatch, MalformedImageRouter(), external_model=None, supports_vision=True)

    resp = _post_image(QUESTION)

    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "Failed to load image or audio file" in detail, "Ollama's real text must survive into the message"
    assert "could not be processed" in detail, "must not assert capability as the only possible cause"


def test_failed_local_image_on_the_streaming_path_reaches_the_user_as_a_failure(monkeypatch, caplog):
    """Defect 2, the headline bug: the real chat app always streams, and on
    that path a failed local image generation used to fall through to the
    generic apology yielded as ordinary answer text - `route=error` in the
    log, but nothing in the SSE stream told the client the request failed.
    The stream must now end on a distinct `response.failed` event, carrying
    the real detail, with no output_text.delta/response.completed hiding it
    as an answered response."""
    router = StreamingRejectingRouter()
    _patch_pipeline(monkeypatch, router, external_model=None, supports_vision=True)

    with caplog.at_level("INFO", logger="dejaq.router.openai_compat"):
        resp = _post_image(QUESTION, stream=True)

    assert resp.status_code == 200  # SSE headers already flushed; the failure is in-band
    events = _sse_events(resp)

    assert "event: response.failed\n" in resp.text
    assert "event: response.completed\n" not in resp.text
    assert not any(e.get("type") == "response.output_text.delta" for e in events), (
        "no apology text may be streamed as if it were the answer"
    )

    failed_events = [e for e in events if e.get("type") == "response.failed"]
    assert len(failed_events) == 1
    failed = failed_events[0]
    assert failed["response"]["status"] == "failed"
    assert "does not support image input" in failed["response"]["error"]["message"]
    assert "qwen2.5:1.5b" in failed["response"]["error"]["message"]
    assert "I'm sorry" not in failed["response"]["error"]["message"]

    done_line = next(
        r.message for r in caplog.records
        if r.name == "dejaq.router.openai_compat" and r.message.startswith("done cache=miss")
    )
    assert "route=error" in done_line


def test_successful_streamed_local_image_answer_still_reports_completed(monkeypatch):
    """Control: the fix must not turn a real successful streamed answer into
    a failure - only the actual failure path ends on response.failed."""
    router = VisionCapturingRouter()
    _patch_pipeline(monkeypatch, router, external_model=None, supports_vision=True)

    resp = _post_image(QUESTION, stream=True)

    assert resp.status_code == 200
    events = _sse_events(resp)
    assert "event: response.completed\n" in resp.text
    assert "event: response.failed\n" not in resp.text
    full_text = "".join(
        e["delta"] for e in events if e.get("type") == "response.output_text.delta"
    )
    assert full_text == ANSWER
