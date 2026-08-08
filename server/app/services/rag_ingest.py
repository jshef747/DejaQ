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
import logging
import re
from dataclasses import dataclass

from app.config import MAX_ATTACHMENT_BYTES
from app.services import file_text, image_text

logger = logging.getLogger("dejaq.rag")

_WHITESPACE_RE = re.compile(r"\s+")
_IMAGE_MIME_PREFIX = "image/"
# A URL fetch that returns more than this is almost certainly not an article.
_URL_MAX_BYTES = MAX_ATTACHMENT_BYTES


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
    reason: str = ""


def _normalize(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


def _finalize(*, title: str, kind: str, source: str, source_ref: str | None, text: str) -> IngestResult:
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
    )


def from_text(title: str, content: str) -> IngestResult:
    return _finalize(title=title, kind="text", source="paste", source_ref=None, text=content)


def from_upload(filename: str | None, data: bytes, mime: str | None) -> IngestResult:
    """Extract text from an uploaded file, OCR'ing images and scanned PDFs."""
    if len(data) > MAX_ATTACHMENT_BYTES:
        return IngestResult(ok=False, reason=f"file exceeds {MAX_ATTACHMENT_BYTES} bytes")

    display = (filename or "").strip() or "upload"
    ft = file_text.extract(data, mime, filename)

    # 1. A file with a real text layer (PDF/DOCX/Markdown/code) — the common case.
    if ft.ok and ft.text.strip():
        return _finalize(
            title=display, kind=ft.kind, source="upload", source_ref=filename, text=ft.text
        )

    # 2. An image upload — OCR it. file_text.kind_for returns "" for images.
    if (mime or "").split(";", 1)[0].strip().lower().startswith(_IMAGE_MIME_PREFIX):
        text = image_text.ocr_plaintext(data)
        if not text.strip():
            return IngestResult(ok=False, kind="image", source="ocr",
                                reason="OCR found no readable text in the image")
        return _finalize(title=display, kind="image", source="ocr", source_ref=filename, text=text)

    # 3. A PDF with no text layer (a scan) — OCR its embedded page images.
    if ft.kind == "pdf":
        text = _ocr_scanned_pdf(data)
        if text.strip():
            return _finalize(title=display, kind="pdf", source="ocr", source_ref=filename, text=text)
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
        for page in reader.pages:
            try:
                for img in page.images:
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


def from_url(url: str, title: str | None = None) -> IngestResult:
    """Fetch a URL and extract its readable text via BeautifulSoup."""
    url = (url or "").strip()
    if not re.match(r"^https?://", url, re.IGNORECASE):
        return IngestResult(ok=False, kind="url", source="url",
                            reason="URL must start with http:// or https://")
    try:
        import httpx

        with httpx.Client(follow_redirects=True, timeout=20.0) as client:
            resp = client.get(url, headers={"User-Agent": "DejaQ-RAG/1.0"})
            resp.raise_for_status()
            raw = resp.content[:_URL_MAX_BYTES]
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
    return _finalize(title=page_title, kind="url", source="url", source_ref=url, text=text)
