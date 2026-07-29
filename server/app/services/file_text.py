"""Fingerprint for uploaded FILES (PDF, Markdown) — the file gate.

Read this before reaching for anything in image_text.py or image_fingerprint.py:
the file gate is deliberately NOT built like the image gate, and the difference is
not a shortcut.

The image gate needs CLIP, dHash, tile variety, OCR confidence floors and a swept
token-overlap threshold because OCR output is *noisy*: two reads of the same page
disagree on characters, so identity can only be approximated, and every constant
had to be measured over ~1.85M labelled pairs to find where approximation stops
being safe.

A PDF or a Markdown file hands us the text directly and deterministically. The
same bytes always extract the same characters. So identity here is EXACT — a
sha256 over the whitespace-normalised text — and the gate is string equality.
Two different documents cannot collide, so there is no false-merge rate, no
recall-vs-merge curve, nothing to sweep, and no eval harness. That is the entire
design, and it is why this module is short.

Whitespace is normalised (not stripped of content, not case-folded) so that the
same document re-saved by a different producer — which commonly reflows line
breaks and spacing while preserving the words — still hashes the same. Case is
left alone: the same file always extracts the same case, so folding it would buy
nothing and could only merge two documents that genuinely differ.

A file we cannot read — a scanned PDF with no text layer, an encrypted PDF, a
corrupt upload — returns ok=False and is then neither served nor stored, mirroring
the image gate's `ambiguous` class. Answering it still works; it just never
becomes a cache entry. Nothing here raises into a request.
"""
from __future__ import annotations

import hashlib
import io
import logging
import re
from dataclasses import dataclass

from app.config import CACHE_FILE_MIN_CHARS

logger = logging.getLogger("dejaq.services.file_text")

PDF_MIME = "application/pdf"
# Markdown arrives with an unreliable MIME — browsers commonly send text/plain or
# an empty string for a .md file — so the extension is the more trustworthy signal
# and either one is accepted.
_MARKDOWN_MIMES = frozenset({"text/markdown", "text/x-markdown", "text/plain", ""})
_MARKDOWN_SUFFIXES = (".md", ".markdown", ".mdown", ".mkd", ".txt")

_WHITESPACE_RE = re.compile(r"\s+")

_pypdf_missing_warned = False


@dataclass(frozen=True)
class FileText:
    """The result of reading an uploaded file.

    `text` is the extracted content as-is (what gets sent to the model for
    Markdown); `sha` is the identity used by the gate. They are deliberately
    different: the model wants readable text, the gate wants a stable key.
    """

    kind: str          # "pdf" | "markdown" | "" when the type is not supported
    text: str          # extracted content, un-normalised
    sha: str           # sha256 of the normalised text; "" when not identifiable
    char_count: int    # length of the normalised text
    ok: bool           # False -> never served, never stored
    reason: str        # why not ok, for the logs; "" when ok

    @property
    def cacheable(self) -> bool:
        return self.ok and bool(self.sha)


def kind_for(mime: str | None, filename: str | None) -> str:
    """Which extractor handles this upload, or "" if we do not support it."""
    mime = (mime or "").split(";", 1)[0].strip().lower()
    name = (filename or "").strip().lower()
    if mime == PDF_MIME or name.endswith(".pdf"):
        return "pdf"
    if name.endswith(_MARKDOWN_SUFFIXES) or mime in _MARKDOWN_MIMES:
        return "markdown"
    return ""


def _normalize(text: str) -> str:
    """Collapse every whitespace run to one space and trim.

    This is the only transformation between the extracted text and the hash, so
    it defines what "the same document" means. Keep it boring: anything cleverer
    here (stripping punctuation, folding case, dropping headers) would start
    merging documents that are not the same.
    """
    return _WHITESPACE_RE.sub(" ", text).strip()


def _finalize(kind: str, text: str) -> FileText:
    normalized = _normalize(text)
    if len(normalized) < CACHE_FILE_MIN_CHARS:
        return FileText(
            kind=kind,
            text=text,
            sha="",
            char_count=len(normalized),
            ok=False,
            reason=f"{len(normalized)} chars extracted (need >= {CACHE_FILE_MIN_CHARS})",
        )
    return FileText(
        kind=kind,
        text=text,
        sha=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        char_count=len(normalized),
        ok=True,
        reason="",
    )


def _extract_pdf(data: bytes) -> str:
    """Every page's text, concatenated. Raises only what extract() catches."""
    from pypdf import PdfReader  # imported lazily so the import cost is paid once, on use

    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        # An empty-password decrypt covers the common "protected but not really"
        # case; anything else falls through to a short read and is refused.
        try:
            reader.decrypt("")
        except Exception:
            return ""
    # ponytail: reads every page. Bounded in practice by MAX_ATTACHMENT_BYTES,
    # and it runs on a threadpool. If very large PDFs ever become common, cap the
    # page count and hash a page-count-tagged prefix — do NOT hash a bare prefix,
    # or two documents sharing an opening chapter would merge.
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def extract(data: bytes, mime: str | None = None, filename: str | None = None) -> FileText:
    """Read an uploaded file. Never raises — a failure yields ok=False."""
    global _pypdf_missing_warned

    kind = kind_for(mime, filename)
    if not kind:
        return FileText("", "", "", 0, ok=False, reason=f"unsupported type {mime!r}")

    if kind == "markdown":
        return _finalize(kind, data.decode("utf-8", errors="replace"))

    try:
        return _finalize(kind, _extract_pdf(data))
    except ModuleNotFoundError:
        if not _pypdf_missing_warned:
            logger.warning(
                "pypdf is not installed — PDF uploads cannot be cached. "
                "Install it (uv sync) to enable PDF caching."
            )
            _pypdf_missing_warned = True
        return FileText(kind, "", "", 0, ok=False, reason="pypdf not installed")
    except Exception as exc:
        # Corrupt, encrypted, or otherwise unreadable. A miss, never a raise.
        logger.info("PDF could not be read (%s); it will not be cached", type(exc).__name__)
        return FileText(kind, "", "", 0, ok=False, reason=f"unreadable ({type(exc).__name__})")


def matches(new: FileText, stored_sha: str | None, stored_kind: str | None) -> bool:
    """Same file, exactly. No threshold, and there is not supposed to be one."""
    return bool(
        new.cacheable
        and stored_sha
        and new.sha == stored_sha
        and new.kind == (stored_kind or "")
    )


def _self_test() -> None:
    long_text = " ".join(f"word{i}" for i in range(200))
    assert len(_normalize(long_text)) >= CACHE_FILE_MIN_CHARS

    # Type routing: MIME or extension, either alone is enough.
    assert kind_for("application/pdf", None) == "pdf"
    assert kind_for(None, "contract.PDF") == "pdf"
    assert kind_for("text/markdown", None) == "markdown"
    assert kind_for("text/plain", "notes.md") == "markdown"
    assert kind_for("", "notes.md") == "markdown", "browsers often send no MIME for .md"
    assert kind_for("image/png", "photo.png") == "", "images are not files here"

    a = extract(long_text.encode("utf-8"), "text/markdown", "a.md")
    assert a.ok and a.kind == "markdown"

    # The whole point: same content -> same key, whatever the producer did to the
    # whitespace. Different content -> different key.
    reflowed = extract(long_text.replace(" ", "\n  ").encode(), "text/markdown", "b.md")
    assert reflowed.sha == a.sha, "re-flowed whitespace must not change identity"
    other = extract((long_text + " extra").encode(), "text/markdown", "c.md")
    assert other.sha != a.sha, "different content must not collide"

    # Too little text to identify -> refused, with a reason worth logging.
    tiny = extract(b"hi", "text/markdown", "t.md")
    assert not tiny.ok and not tiny.cacheable and "need >=" in tiny.reason

    # Unreadable PDF bytes are a miss, not an exception.
    broken = extract(b"%PDF-1.4 not really a pdf", "application/pdf", "x.pdf")
    assert not broken.ok and broken.kind == "pdf"

    # Unsupported types never reach a gate.
    assert not extract(b"\x89PNG", "image/png", "p.png").ok

    # The gate itself.
    assert matches(a, a.sha, "markdown")
    assert not matches(a, other.sha, "markdown"), "different files must not match"
    assert not matches(a, a.sha, "pdf"), "kinds must not mix"
    assert not matches(a, None, None), "an entry with no file is not a match"
    assert not matches(tiny, tiny.sha, "markdown"), "an unidentifiable file never matches"
    print("self-test passed")


if __name__ == "__main__":
    _self_test()
