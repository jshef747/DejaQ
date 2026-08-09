"""RAG (Rug) ingestion: text, file/upload, image OCR, scanned PDF, URL.

Extraction is delegated to file_text / image_text / httpx, all mocked here so the
tests stay offline and fast. What is asserted is rag_ingest's own logic: kind and
source labelling, the OCR/scanned fallbacks, sha identity, and the failure paths.
"""
import pytest

from app.services import rag_ingest

pytestmark = pytest.mark.no_model


def test_from_text_produces_a_text_document():
    r = rag_ingest.from_text("Policy", "Refunds are allowed within 30 days.")
    assert r.ok and r.kind == "text" and r.source == "paste"
    assert r.title == "Policy"
    assert r.sha and r.char_count > 0


def test_from_text_rejects_empty():
    r = rag_ingest.from_text("Title", "   \n  ")
    assert not r.ok and "no readable text" in r.reason


def test_same_text_hashes_the_same_regardless_of_whitespace():
    a = rag_ingest.from_text("t", "hello   world")
    b = rag_ingest.from_text("t", "hello\n\nworld")
    assert a.sha == b.sha


def test_from_upload_uses_file_text_for_a_real_text_layer():
    data = b"# Handbook\n\nBe excellent to each other.\n" * 5
    r = rag_ingest.from_upload("handbook.md", data, "text/markdown")
    assert r.ok and r.kind == "markdown" and r.source == "upload"
    assert r.source_ref == "handbook.md"


def test_from_upload_ocrs_an_image(monkeypatch):
    monkeypatch.setattr(rag_ingest.image_text, "ocr_plaintext", lambda data: "SIGN: no entry")
    r = rag_ingest.from_upload("sign.png", b"\x89PNGfakebytes", "image/png")
    assert r.ok and r.kind == "image" and r.source == "ocr"
    assert "no entry" in r.text


def test_from_upload_image_with_no_ocr_text_fails(monkeypatch):
    monkeypatch.setattr(rag_ingest.image_text, "ocr_plaintext", lambda data: "  ")
    r = rag_ingest.from_upload("blank.png", b"\x89PNG", "image/png")
    assert not r.ok and r.kind == "image"


def test_from_upload_scanned_pdf_falls_back_to_ocr(monkeypatch):
    # file_text returns a not-ok PDF (no text layer); OCR of page images recovers it.
    from app.services.file_text import FileText

    monkeypatch.setattr(
        rag_ingest.file_text, "extract",
        lambda data, mime, filename: FileText("pdf", "", "", 0, ok=False, reason="need >= 200"),
    )
    monkeypatch.setattr(rag_ingest, "_ocr_scanned_pdf", lambda data: "Scanned invoice total 42")
    r = rag_ingest.from_upload("scan.pdf", b"%PDF-1.4", "application/pdf")
    assert r.ok and r.kind == "pdf" and r.source == "ocr"
    assert "invoice" in r.text


def test_from_upload_oversize_is_rejected(monkeypatch):
    monkeypatch.setattr(rag_ingest, "MAX_ATTACHMENT_BYTES", 10)
    r = rag_ingest.from_upload("big.md", b"x" * 50, "text/markdown")
    assert not r.ok and "exceeds" in r.reason


def test_from_url_rejects_non_http():
    r = rag_ingest.from_url("ftp://example.com/x")
    assert not r.ok and "http" in r.reason


def test_from_upload_title_override_keeps_filename_detection():
    # A custom title must not replace the filename that drives kind detection
    # and source_ref.
    data = b"# Handbook\n\nBe excellent to each other.\n" * 5
    r = rag_ingest.from_upload("handbook.md", data, "application/octet-stream", title="Team Handbook")
    assert r.ok and r.kind == "markdown"
    assert r.title == "Team Handbook"
    assert r.source_ref == "handbook.md"


def _mock_streaming_client(monkeypatch, chunks):
    class _Resp:
        def raise_for_status(self):
            return None

        def iter_bytes(self):
            yield from chunks

    class _Stream:
        def __enter__(self):
            return _Resp()

        def __exit__(self, *a):
            return False

    class _Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def stream(self, method, url, headers=None):
            return _Stream()

    import httpx

    monkeypatch.setattr(httpx, "Client", _Client)


def test_from_url_extracts_readable_text(monkeypatch):
    html = b"<html><head><title>Docs</title></head><body><script>x=1</script><p>Hello world</p></body></html>"
    _mock_streaming_client(monkeypatch, [html])
    r = rag_ingest.from_url("https://example.com/docs")
    assert r.ok and r.kind == "url" and r.source == "url"
    assert r.title == "Docs"
    assert "Hello world" in r.text
    assert "x=1" not in r.text  # <script> stripped


def test_from_url_stops_reading_at_the_byte_cap(monkeypatch):
    monkeypatch.setattr(rag_ingest, "_URL_MAX_BYTES", 100)
    head = b"<html><body><p>capped page</p>"
    _mock_streaming_client(monkeypatch, [head] + [b"x" * 64] * 1000)
    r = rag_ingest.from_url("https://example.com/huge")
    assert r.ok
    assert len(r.text) < 200  # only the capped prefix was parsed
