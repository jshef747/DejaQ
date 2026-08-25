"""RAG ingestion: text, file/upload, image OCR, scanned PDF, URL.

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


_REAL_RESOLVE = rag_ingest._resolve_ips


def _fake_resolver(host, port):
    """Resolve without DNS: IP literals stay put, hostnames look public.

    Mirrors _resolve_ips, including the IPv4-mapped-IPv6 unwrap.
    """
    import ipaddress

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = ipaddress.ip_address("93.184.216.34")
    return [getattr(ip, "ipv4_mapped", None) or ip]


def _mock_streaming_client(monkeypatch, chunks, responses=None):
    """Stub httpx.Client. `responses` optionally scripts per-hop redirects as
    (status_code, location) tuples; the last hop serves `chunks`."""
    monkeypatch.setattr(rag_ingest, "_resolve_ips", _fake_resolver)
    scripted = list(responses or [])
    visited = []

    class _Resp:
        def __init__(self, status_code, location):
            self.status_code = status_code
            self.headers = {"location": location} if location else {}

        def raise_for_status(self):
            return None

        def iter_bytes(self):
            yield from chunks

    class _Stream:
        def __init__(self, resp):
            self._resp = resp

        def __enter__(self):
            return self._resp

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
            visited.append(url)
            if scripted:
                status_code, location = scripted.pop(0)
                return _Stream(_Resp(status_code, location))
            return _Stream(_Resp(200, None))

    import httpx

    monkeypatch.setattr(httpx, "Client", _Client)
    return visited


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


# --- SSRF: the server must never be steered at its own network ----------------

@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8001/api/v1/collections",   # loopback (ChromaDB)
        "http://169.254.169.254/latest/meta-data/",   # cloud metadata
        "http://10.0.0.5/internal",                   # private
        "http://192.168.1.1/admin",                   # private
        "http://172.16.4.2/internal",                 # private
        "http://[::1]:8001/",                         # IPv6 loopback
        "http://[::ffff:127.0.0.1]/",                 # IPv4-mapped loopback
        "http://0.0.0.0/",                            # unspecified
    ],
)
def test_from_url_refuses_private_and_loopback_addresses(monkeypatch, url):
    visited = _mock_streaming_client(monkeypatch, [b"<html><body>secret</body></html>"])
    r = rag_ingest.from_url(url)
    assert not r.ok and r.kind == "url"
    assert "non-public" in r.reason
    assert visited == []  # nothing was fetched at all


def test_from_url_refuses_a_hostname_that_resolves_to_loopback(monkeypatch):
    # Real resolution: "localhost" is in every hosts file, so this needs no network.
    visited = _mock_streaming_client(monkeypatch, [b"<html><body>secret</body></html>"])
    monkeypatch.setattr(rag_ingest, "_resolve_ips", _REAL_RESOLVE)
    r = rag_ingest.from_url("http://localhost:8000/admin/v1/whoami")
    assert not r.ok and "non-public" in r.reason
    assert visited == []


def test_from_url_refuses_a_redirect_into_an_internal_host(monkeypatch):
    # The submitted URL is public; the server it reaches redirects inward.
    visited = _mock_streaming_client(
        monkeypatch,
        [b"<html><body>metadata</body></html>"],
        responses=[(302, "http://169.254.169.254/latest/meta-data/")],
    )
    r = rag_ingest.from_url("https://example.com/redirector")
    assert not r.ok and "non-public" in r.reason
    assert visited == ["https://example.com/redirector"]  # the internal hop never ran


def test_from_url_follows_a_public_redirect(monkeypatch):
    visited = _mock_streaming_client(
        monkeypatch,
        [b"<html><head><title>Moved</title></head><body><p>final page</p></body></html>"],
        responses=[(301, "https://docs.example.com/final")],
    )
    r = rag_ingest.from_url("https://example.com/start")
    assert r.ok and "final page" in r.text
    assert visited == ["https://example.com/start", "https://docs.example.com/final"]


def test_from_url_gives_up_on_a_redirect_loop(monkeypatch):
    _mock_streaming_client(
        monkeypatch,
        [b"<html></html>"],
        responses=[(302, "https://example.com/loop")] * 20,
    )
    r = rag_ingest.from_url("https://example.com/loop")
    assert not r.ok and "too many redirects" in r.reason


def test_from_url_refuses_an_unresolvable_host(monkeypatch):
    def _boom(host, port):
        raise OSError("no such host")

    monkeypatch.setattr(rag_ingest, "_resolve_ips", _boom)
    r = rag_ingest.from_url("https://no-such-host.invalid/page")
    assert not r.ok and "could not resolve host" in r.reason


# --- scanned-PDF OCR budget ---------------------------------------------------

def test_scanned_pdf_ocr_stops_mid_page_when_the_time_budget_is_spent(monkeypatch):
    """One page with many embedded images must not run past the deadline."""
    class _Img:
        data = b"fake-raster"

    class _Page:
        images = [_Img()] * 500

    class _Reader:
        is_encrypted = False
        pages = [_Page(), _Page()]

    import sys
    import types

    fake_pypdf = types.ModuleType("pypdf")
    fake_pypdf.PdfReader = lambda stream: _Reader()
    monkeypatch.setitem(sys.modules, "pypdf", fake_pypdf)

    clock = {"t": 0.0}
    monkeypatch.setattr(rag_ingest.time, "monotonic", lambda: clock["t"])

    calls = {"n": 0}

    def _slow_ocr(data):
        calls["n"] += 1
        clock["t"] += 30.0  # each OCR pass burns 30s of the 120s budget
        return "page text"

    monkeypatch.setattr(rag_ingest.image_text, "ocr_plaintext", _slow_ocr)
    text = rag_ingest._ocr_scanned_pdf(b"%PDF-1.4")
    # 30s per image against a 120s budget: passes at t=0/30/60/90 all start
    # inside the budget, the one at t=120 is still not *past* it, and the next
    # check (t=150) stops the loop mid-page — without the per-image check all
    # 500 images of page 1 would have run.
    assert calls["n"] == 5
    assert "page text" in text


def test_scanned_pdf_ocr_stops_at_the_image_cap(monkeypatch):
    class _Img:
        data = b"fake-raster"

    class _Page:
        images = [_Img()] * 500

    class _Reader:
        is_encrypted = False
        pages = [_Page()]

    import sys
    import types

    fake_pypdf = types.ModuleType("pypdf")
    fake_pypdf.PdfReader = lambda stream: _Reader()
    monkeypatch.setitem(sys.modules, "pypdf", fake_pypdf)

    calls = {"n": 0}

    def _instant_ocr(data):
        calls["n"] += 1
        return "x"

    monkeypatch.setattr(rag_ingest.image_text, "ocr_plaintext", _instant_ocr)
    rag_ingest._ocr_scanned_pdf(b"%PDF-1.4")
    assert calls["n"] == rag_ingest._SCANNED_PDF_MAX_IMAGES
