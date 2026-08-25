"""Turn an admin's raw input (text, file, URL, image) into RAG-ready text.

This is the messy extraction layer for the four ingestion sources. It has no
auth, DB, or vector concerns — it only answers "what is the readable text of this
thing, and what should we call it?". `rag_admin_service` orchestrates; this module
extracts.

Extraction reuses what already exists rather than adding heavy dependencies:
- PDF/DOCX/text/code → `file_text.extract` (pypdf / python-docx / UTF-8 sniff),
  the exact same path the file gate uses.
- Image → `image_text.ocr_plaintext` (tesseract), the existing OCR binary.
- Scanned PDF (no text layer) → its embedded page images are pulled out with
  pypdf (already a dependency, MIT) and OCR'd. This avoids AGPL `pymupdf`, which
  the file gate deliberately declined (see pyproject.toml).
- URL → httpx fetch + BeautifulSoup text extraction.
"""
from __future__ import annotations

import hashlib
import ipaddress
import logging
import re
import socket
import time
from dataclasses import dataclass
from urllib.parse import urlparse

from app.config import MAX_ATTACHMENT_BYTES
from app.services import file_text, image_text

logger = logging.getLogger("dejaq.rag")

_WHITESPACE_RE = re.compile(r"\s+")
_IMAGE_MIME_PREFIX = "image/"
# A URL fetch that returns more than this is almost certainly not an article.
_URL_MAX_BYTES = MAX_ATTACHMENT_BYTES
# Redirects are followed by hand so every hop can be re-checked against the
# private-address rules; this bounds the chain.
_URL_MAX_REDIRECTS = 5
# Scanned-PDF OCR runs one tesseract pass per embedded image on a FastAPI
# threadpool worker, so a many-page scan needs a hard ceiling: whichever of
# these budgets is hit first stops the loop and keeps the text read so far.
# The time budget is re-checked per IMAGE, not only per page: a single page can
# embed hundreds of rasters, and a per-page check lets one page run unbounded.
_SCANNED_PDF_MAX_PAGES = 50
_SCANNED_PDF_MAX_IMAGES = 100
_SCANNED_PDF_MAX_SECONDS = 120.0


@dataclass(frozen=True)
class IngestResult:
    """The extracted, normalised form of one ingestion input.

    `ok=False` carries a human `reason` for the API error; `ok=True` guarantees a
    non-empty `text` and a `sha` identity.
    """

    ok: bool
    title: str = ""
    kind: str = ""          # text | pdf | docx | markdown | url | image
    source: str = ""        # paste | upload | url | ocr
    source_ref: str | None = None
    text: str = ""
    sha: str = ""
    char_count: int = 0
    # Size in bytes of the raw input as given to us (pasted text's UTF-8
    # encoding, the uploaded file's bytes, or the fetched page's bytes) - what
    # the dashboard shows as "file size". Distinct from char_count, which is
    # extracted-text length and can differ a lot for PDF/DOCX.
    byte_size: int = 0
    reason: str = ""


def _normalize(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


def _finalize(
    *, title: str, kind: str, source: str, source_ref: str | None, text: str, byte_size: int
) -> IngestResult:
    normalized = _normalize(text)
    if not normalized:
        return IngestResult(ok=False, kind=kind, source=source, reason="no readable text found")
    return IngestResult(
        ok=True,
        title=title.strip() or (source_ref or kind),
        kind=kind,
        source=source,
        source_ref=source_ref,
        text=text,
        sha=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        char_count=len(normalized),
        byte_size=byte_size,
    )


def from_text(title: str, content: str) -> IngestResult:
    return _finalize(
        title=title, kind="text", source="paste", source_ref=None, text=content,
        byte_size=len(content.encode("utf-8")),
    )


def from_upload(
    filename: str | None, data: bytes, mime: str | None, title: str | None = None
) -> IngestResult:
    """Extract text from an uploaded file, OCR'ing images and scanned PDFs.

    `filename` is the real name of the uploaded file — it feeds extension-based
    kind detection and is stored as source_ref. `title` is only a display-name
    override and never influences extraction.
    """
    if len(data) > MAX_ATTACHMENT_BYTES:
        return IngestResult(ok=False, reason=f"file exceeds {MAX_ATTACHMENT_BYTES} bytes")

    display = (title or "").strip() or (filename or "").strip() or "upload"
    ft = file_text.extract(data, mime, filename)

    # 1. A file with a real text layer (PDF/DOCX/Markdown/code) — the common case.
    if ft.ok and ft.text.strip():
        return _finalize(
            title=display, kind=ft.kind, source="upload", source_ref=filename, text=ft.text,
            byte_size=len(data),
        )

    # 2. An image upload — OCR it. file_text.kind_for returns "" for images.
    if (mime or "").split(";", 1)[0].strip().lower().startswith(_IMAGE_MIME_PREFIX):
        text = image_text.ocr_plaintext(data)
        if not text.strip():
            return IngestResult(ok=False, kind="image", source="ocr",
                                reason="OCR found no readable text in the image")
        return _finalize(title=display, kind="image", source="ocr", source_ref=filename, text=text,
                          byte_size=len(data))

    # 3. A PDF with no text layer (a scan) — OCR its embedded page images.
    if ft.kind == "pdf":
        text = _ocr_scanned_pdf(data)
        if text.strip():
            return _finalize(title=display, kind="pdf", source="ocr", source_ref=filename, text=text,
                              byte_size=len(data))
        return IngestResult(ok=False, kind="pdf", source="ocr",
                            reason="scanned PDF: no text layer and OCR found nothing")

    # 4. Anything else file_text refused (unsupported/corrupt).
    return IngestResult(ok=False, kind=ft.kind or "", reason=ft.reason or "unsupported file")


def _ocr_scanned_pdf(data: bytes) -> str:
    """OCR every embedded image of a scanned PDF, page by page.

    A scanned PDF is typically one full-page raster per page. pypdf exposes those
    via `page.images`; we OCR each and concatenate. Best-effort — any failure just
    yields less text, never an exception.
    """
    try:
        import io
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                return ""
        parts: list[str] = []
        deadline = time.monotonic() + _SCANNED_PDF_MAX_SECONDS
        total_pages = len(reader.pages)
        images_done = 0
        exhausted = False
        for page_index, page in enumerate(reader.pages):
            if page_index >= _SCANNED_PDF_MAX_PAGES or time.monotonic() > deadline:
                exhausted = True
            if exhausted:
                logger.info(
                    "Scanned-PDF OCR stopped at page %d/%d (page/image/time budget reached)",
                    page_index, total_pages,
                )
                break
            try:
                for img in page.images:
                    if images_done >= _SCANNED_PDF_MAX_IMAGES or time.monotonic() > deadline:
                        exhausted = True
                        break
                    images_done += 1
                    page_text = image_text.ocr_plaintext(img.data)
                    if page_text.strip():
                        parts.append(page_text)
            except Exception:
                logger.debug("Could not OCR a scanned PDF page", exc_info=True)
        return "\n".join(parts)
    except ModuleNotFoundError:
        return ""
    except Exception:
        logger.info("Scanned-PDF OCR failed", exc_info=True)
        return ""


def _resolve_ips(host: str, port: int) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Every address `host` resolves to, with IPv4-mapped IPv6 unwrapped."""
    out = []
    for info in socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP):
        ip = ipaddress.ip_address(info[4][0])
        out.append(getattr(ip, "ipv4_mapped", None) or ip)
    return out


def _url_block_reason(url: str) -> str | None:
    """Why this URL must not be fetched server-side, or None when it is allowed.

    The server sits on the operator's network, so an ingestion URL pointing at
    loopback, a private range, or the cloud metadata endpoint would turn the
    admin API into a read primitive for internal services. Only globally
    routable addresses are fetched; a hostname is refused if ANY address it
    resolves to is non-global. Every redirect hop is re-checked, since a public
    URL can 302 into an internal one.

    A DNS entry that changes between this check and the connect (rebinding) is
    not covered — closing that needs a pinned-IP transport, not a stricter rule.
    """
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        return "URL must start with http:// or https://"
    try:
        host = parsed.hostname
        port = parsed.port or (443 if scheme == "https" else 80)
    except ValueError:
        return "URL has an invalid host or port"
    if not host:
        return "URL has no host"
    try:
        ips = _resolve_ips(host, port)
    except (OSError, ValueError):
        return f"could not resolve host '{host}'"
    for ip in ips:
        if not ip.is_global:
            return (
                f"refusing to fetch '{host}': {ip} is a loopback, private, "
                "link-local, or otherwise non-public address"
            )
    return None


def from_url(url: str, title: str | None = None) -> IngestResult:
    """Fetch a URL and extract its readable text via BeautifulSoup."""
    url = (url or "").strip()
    try:
        import httpx

        raw = b""
        with httpx.Client(follow_redirects=False, timeout=20.0) as client:
            current = url
            for _ in range(_URL_MAX_REDIRECTS + 1):
                blocked = _url_block_reason(current)
                if blocked is not None:
                    return IngestResult(ok=False, kind="url", source="url", reason=blocked)
                with client.stream(
                    "GET", current, headers={"User-Agent": "DejaQ-RAG/1.0"}
                ) as resp:
                    location = (
                        resp.headers.get("location")
                        if 300 <= resp.status_code < 400
                        else None
                    )
                    if location:
                        current = str(httpx.URL(current).join(location))
                        continue
                    resp.raise_for_status()
                    buf = bytearray()
                    for chunk in resp.iter_bytes():
                        buf.extend(chunk)
                        if len(buf) >= _URL_MAX_BYTES:
                            break
                    raw = bytes(buf[:_URL_MAX_BYTES])
                    break
            else:
                return IngestResult(ok=False, kind="url", source="url",
                                    reason=f"too many redirects (>{_URL_MAX_REDIRECTS})")
    except Exception as exc:
        return IngestResult(ok=False, kind="url", source="url",
                            reason=f"could not fetch URL ({type(exc).__name__})")

    try:
        from bs4 import BeautifulSoup
    except ModuleNotFoundError:
        return IngestResult(ok=False, kind="url", source="url",
                            reason="beautifulsoup4 is not installed — run `uv sync`")

    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    page_title = title or (soup.title.string.strip() if soup.title and soup.title.string else url)
    text = soup.get_text(separator="\n")
    return _finalize(title=page_title, kind="url", source="url", source_ref=url, text=text,
                      byte_size=len(raw))
