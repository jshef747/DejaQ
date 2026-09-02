"""Stage 3: an unreadable PDF (no text layer, or genuinely corrupt) gets a
real local answer instead of the external capability gate's bare 422.

dejaq-200-test-fixes defect #2: with an external model that has no PDF
support configured (or none configured at all), a scanned/corrupt PDF used to
be forced external with nothing usable to send it - `file_doc.readable` is
False, so the local branch never even considered it - and the external
branch's own capability check then raised a 422 with no answer whatsoever.

This is a genuine fallback, not a general preference for local over
external: when the workspace's external model CAN read PDFs, this same
scanned/corrupt PDF still routes external instead (tests/test_local_pdf_answers.py
covers that path and stays green with this file's changes) - see
`_external_pdf_capable` in openai_compat.py's file classification branch.
"""
import base64
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.main import app
from app.routers import openai_compat
from tests.conftest import StreamingLocalRouterMixin
from tests.test_openai_compat_smoke import _AUTH, StubAdjuster, StubEnricher, StubNormalizer

pytestmark = pytest.mark.no_model

QUESTION = "what does this document say?"


def make_scanned_pdf(caption: str = "scanned page") -> bytes:
    """A single-page PDF with NO text layer - one embedded raster image, the
    same shape pypdf sees from a real scanner: `extract_text()` returns "",
    but `page.images` finds the page's own picture."""
    img = Image.new("RGB", (200, 100), color="white")
    ImageDraw.Draw(img).text((10, 10), caption, fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PDF")
    return buf.getvalue()


CORRUPT_PDF = b"%PDF-1.4 not really a pdf, no valid structure at all"


@pytest.fixture(autouse=True)
def _stub_api_key(monkeypatch):
    from app.middleware.api_key import _KEY_CACHE

    monkeypatch.setattr(
        _KEY_CACHE, "resolve", lambda token: ("demo", 1) if token == "test-key" else None
    )
    monkeypatch.setattr(_KEY_CACHE, "namespace", lambda *a, **kw: "test-namespace")


class _NoHitMemory:
    def __init__(self):
        self.stored: list[tuple] = []

    def lookup_cache(self, clean_query: str):
        from app.services.memory_chromaDB import CacheLookupResult

        return CacheLookupResult(hit=False)

    def store_interaction(self, *args, **kwargs):
        self.stored.append((args, kwargs))
        return "id"

    def increment_hit_count(self, doc_id: str):
        return None

    def count_file_entries(self, file_sha: str) -> int:
        return 0


class VisionCapturingRouter(StreamingLocalRouterMixin):
    """Records whatever local generation actually received - text and images -
    so a test can prove the rescued page image (not just the bare question)
    reached the model, or that an unreadable file got an honest prompt rather
    than being answered as if nothing were attached."""

    def __init__(self, answer: str = "I can see the page now."):
        self._answer = answer
        self.last_query: str | None = None
        self.last_images: list[str] | None = None

    async def generate_local_response(self, query, history=None, max_tokens=1024, system_prompt=None, images=None):
        self.last_query = query
        self.last_images = images
        return self._answer, 12.0, "stop"


class ExplodingExternalLLM:
    async def generate_response(self, request, provider=None, api_key=None):
        raise AssertionError("external route must not be used when it cannot read PDFs")

    async def stream_response(self, request, provider=None, api_key=None):
        raise AssertionError("external route must not be used when it cannot read PDFs")
        yield  # pragma: no cover - never reached, makes this an async generator


def _patch_pipeline(monkeypatch, router, *, external_model: str | None, memory=None):
    async def _noop_log(*a, **k):
        return None

    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_adjuster", StubAdjuster())
    monkeypatch.setattr(openai_compat, "_llm_router", router)
    monkeypatch.setattr(openai_compat, "_external_llm", ExplodingExternalLLM())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: memory or _NoHitMemory())
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
    monkeypatch.setattr(openai_compat.ollama_catalog, "supports_vision", lambda model: True)


def _post_pdf(query: str, pdf_bytes: bytes, *, filename: str = "doc.pdf"):
    part = {
        "type": "input_file",
        "filename": filename,
        "file_data": "data:application/pdf;base64," + base64.b64encode(pdf_bytes).decode(),
    }
    return TestClient(app, headers=_AUTH).post(
        "/v1/responses",
        json={
            "model": "gpt-4o",
            "input": [{"role": "user", "content": [{"type": "input_text", "text": query}, part]}],
            "stream": False,
        },
    )


def test_scanned_pdf_with_no_external_model_is_answered_via_local_vision_rescue(monkeypatch, caplog):
    router = VisionCapturingRouter("The page says: scanned page")
    memory = _NoHitMemory()
    _patch_pipeline(monkeypatch, router, external_model=None, memory=memory)

    with caplog.at_level("INFO", logger="dejaq.router.openai_compat"):
        resp = _post_pdf(QUESTION, make_scanned_pdf())

    assert resp.status_code == 200
    assert resp.json()["output_text"] == "The page says: scanned page"
    assert router.last_images, "the rescued page image must reach local generation"
    assert memory.stored == [], "an unreadable file must never be cached, rescued or not"

    done_line = next(
        r.message for r in caplog.records
        if r.name == "dejaq.router.openai_compat" and r.message.startswith("done cache=miss")
    )
    assert "route=local" in done_line


def test_scanned_pdf_still_prefers_external_when_it_can_actually_read_pdfs(monkeypatch):
    """The fallback is conditional, not a blanket preference: a workspace
    whose external model DOES support PDFs keeps using its native document
    part (richer than the local rescue's single embedded image)."""
    router = VisionCapturingRouter()
    monkeypatch.setattr(openai_compat, "external_supports_pdf", lambda model: True)

    class CapturingExternal:
        async def generate_response(self, request, provider=None, api_key=None):
            from app.schemas.chat import ExternalLLMResponse

            return ExternalLLMResponse(
                text="answered from the native document part", model_used=request.model,
                prompt_tokens=5, completion_tokens=6, latency_ms=10.0,
            )

    _patch_pipeline(monkeypatch, router, external_model="gpt-4o")
    monkeypatch.setattr(openai_compat, "_external_llm", CapturingExternal())
    monkeypatch.setattr(
        openai_compat, "get_workspace_provider_key",
        lambda session, workspace_id, provider: "sk-test-live",
    )

    resp = _post_pdf(QUESTION, make_scanned_pdf())

    assert resp.status_code == 200
    assert resp.json()["output_text"] == "answered from the native document part"
    assert router.last_query is None, "local generation must not run when external can read the PDF"


def test_corrupt_pdf_with_no_external_model_gets_an_honest_answer_not_a_bare_422(monkeypatch, caplog):
    router = VisionCapturingRouter("I couldn't read that PDF - could you try re-uploading it?")
    memory = _NoHitMemory()
    _patch_pipeline(monkeypatch, router, external_model=None, memory=memory)

    with caplog.at_level("INFO", logger="dejaq.router.openai_compat"):
        resp = _post_pdf(QUESTION, CORRUPT_PDF)

    assert resp.status_code == 200, "a corrupt PDF must get a real response, never a bare 422"
    assert resp.json()["output_text"] == "I couldn't read that PDF - could you try re-uploading it?"
    assert router.last_images is None, "there is no image to rescue from a file pypdf could not even open"
    assert "could not be read" in router.last_query
    assert memory.stored == []

    done_line = next(
        r.message for r in caplog.records
        if r.name == "dejaq.router.openai_compat" and r.message.startswith("done cache=miss")
    )
    assert "route=local" in done_line
