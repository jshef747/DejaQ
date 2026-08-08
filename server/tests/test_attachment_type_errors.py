"""What /v1/responses does with a file type it cannot read.

Two populations that look alike from the outside and must not be treated alike:

  * a type we have NO extractor for (csv, docx, an untyped data URL) - nothing
    downstream can ever see its content, so the request is refused with 400
    rather than answered as if nothing had been attached;
  * a type we DO recognise but cannot get text out of (a scanned PDF, a corrupt
    PDF, a Markdown file too short to identify) - the provider still gets it, or
    it is still inlined, and only the cache entry is refused.

The second group is the easy one to break while fixing the first, so it is
pinned here alongside it.
"""
import base64

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import openai_compat
from app.services.file_text import DOCX_MIME
from tests.test_file_gate import make_docx, make_pdf
from tests.test_openai_compat_smoke import (
    _AUTH,
    StubAdjuster,
    StubEnricher,
    StubNormalizer,
)

pytestmark = pytest.mark.no_model

LONG_TEXT = " ".join(f"word{i}" for i in range(200))


@pytest.fixture(autouse=True)
def _stub_api_key(monkeypatch):
    from app.middleware.api_key import _KEY_CACHE

    monkeypatch.setattr(
        _KEY_CACHE, "resolve", lambda token: ("demo", 1) if token == "test-key" else None
    )


class _NoHitMemory:
    """Never a hit, and remembers whether anything was written."""

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


def _patch_pipeline(monkeypatch, memory):
    async def _noop_log(*a, **k):
        return None

    class _Validator:
        async def validate(self, *a, **k):
            return True, "VALID"

    monkeypatch.setattr(
        openai_compat, "_services_for_model_profile",
        lambda profile: openai_compat.ModelServices(
            normalizer=StubNormalizer(), llm_router=None,
            adjuster=StubAdjuster(), enricher=StubEnricher(), validator=_Validator(),
        ),
    )
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: memory)
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)
    monkeypatch.setattr(openai_compat, "USE_CELERY", False)


def _post_file(query: str, data: bytes, *, mime: str | None, filename: str | None):
    part: dict = {
        "type": "input_file",
        "file_data": f"data:{mime or ''};base64," + base64.b64encode(data).decode(),
    }
    if filename is not None:
        part["filename"] = filename
    return TestClient(app, headers=_AUTH).post(
        "/v1/responses",
        json={
            "model": "gpt-4o",
            "input": [{"role": "user", "content": [{"type": "input_text", "text": query}, part]}],
            "stream": False,
        },
    )


def test_unsupported_file_type_is_rejected_not_silently_dropped():
    """A file whose bytes are not valid UTF-8 - and that is not a PDF or DOCX by
    MIME/extension - was decoded, size-checked, classified, then dropped, and
    the model answered from the question alone with a confident 200 and no
    signal at all."""
    resp = _post_file(
        "what is in this image?", b"\x89PNG\x0d\x0a\x1a\x0a\x00\x01\xff",
        mime="image/png", filename="notes.png",
    )

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "image/png" in detail, "the message must name the type it rejected"
    assert "PDF" in detail and "Markdown" in detail, "and what is accepted"


def test_csv_is_accepted_as_a_text_file(monkeypatch):
    """CSV has no dedicated extractor, but its bytes decode as plain UTF-8 text,
    so it is accepted the same way any other text/code file is - the whole point
    of content-sniffing instead of a maintained format list."""
    memory = _NoHitMemory()
    _patch_pipeline(monkeypatch, memory)

    resp = _post_file(
        "what is in this spreadsheet?", b"a,b,c\n1,2,3\n", mime="text/csv", filename="notes.csv"
    )

    assert resp.status_code != 400


def test_office_document_is_rejected_with_the_same_shape():
    resp = _post_file(
        "summarise this",
        b"\x00\x01\xffnot a real office file",
        mime="application/vnd.ms-excel",
        filename="report.xls",
    )

    assert resp.status_code == 400
    assert "ms-excel" in resp.json()["detail"]


def test_untyped_data_url_is_not_assumed_to_be_a_pdf():
    """`data:;base64,` used to mean application/pdf to the router and Markdown to
    file_text - the same attachment, two answers. An untyped upload with bytes
    that are not valid UTF-8 is now simply unknown."""
    resp = _post_file("what does this say?", b"\xff\xfe\x00binary garbage", mime=None, filename=None)

    assert resp.status_code == 400
    assert "no type given" in resp.json()["detail"]


def test_untyped_data_url_with_text_bytes_is_accepted_as_text(monkeypatch):
    """The same untyped, unnamed upload - but with bytes that ARE valid UTF-8 -
    is no longer refused just for lacking a MIME and a filename: the content
    itself is enough to identify it as text."""
    memory = _NoHitMemory()
    _patch_pipeline(monkeypatch, memory)

    resp = _post_file("what does this say?", b"just some plain text content here", mime=None, filename=None)

    assert resp.status_code != 400


def test_untyped_markdown_upload_still_works_by_its_extension(monkeypatch):
    """Browsers routinely send no MIME for a .md file; the name carries it."""
    memory = _NoHitMemory()
    _patch_pipeline(monkeypatch, memory)

    resp = _post_file("summarise this", LONG_TEXT.encode(), mime=None, filename="notes.md")

    assert resp.status_code != 400


@pytest.mark.parametrize(
    "label,data,mime,filename",
    [
        ("scanned pdf (no text layer)", make_pdf(""), "application/pdf", "scan.pdf"),
        ("corrupt pdf", b"%PDF-1.4 truncated garbage", "application/pdf", "broken.pdf"),
        ("docx too short to identify", make_docx(["hi"]), DOCX_MIME, "short.docx"),
        ("corrupt docx", b"PK\x03\x04 not really a docx", DOCX_MIME, "broken.docx"),
    ],
)
def test_recognised_but_uncacheable_files_are_answered_not_rejected(
    monkeypatch, label, data, mime, filename
):
    """The distinction the 400 must not swallow.

    These are supported types we simply cannot identify. They still reach the
    provider (or the prompt); refusing them a cache entry is the whole of the
    intended behaviour. 402 here is "no provider credential in tests" - what
    matters is that it is not a 400, and that nothing was cached.
    """
    memory = _NoHitMemory()
    _patch_pipeline(monkeypatch, memory)

    resp = _post_file("what does this say?", data, mime=mime, filename=filename)

    assert resp.status_code != 400, f"{label} is a recognised type and must not be refused"
    assert resp.status_code in (200, 402, 422)
    assert memory.stored == [], f"{label} must never be cached"
