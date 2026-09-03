"""OCR fingerprint for text-bearing images (the document path of the image gate).

Why this exists: pixel similarity cannot judge documents. Two screenshots of the
SAME syllabus differ in every pixel (crop/zoom) while two DIFFERENT syllabi from
one university template are nearly pixel-identical — measured live, two different
courses scored CLIP 0.027 / dHash hamming 0, i.e. the pixel gate would have served
one course's answer for the other. The distinguishing information is the words.

So: images that yield confident text are compared by their text; everything else
keeps the CLIP+dHash gate in image_fingerprint.py.

Engine: the `tesseract` binary (cross-platform; Hebrew via the ~1MB heb
traineddata). It is invoked as a subprocess in TSV mode so per-word confidence is
available. Absent or failing tesseract degrades to the photo path — never raises
into a request.

All thresholds here were measured, see docs/image-gate.md.
"""
from __future__ import annotations

import csv
import io
import logging
import re
import subprocess
from dataclasses import dataclass

from app.config import (
    CACHE_IMAGE_AMBIGUOUS_MIN_WORDS,
    CACHE_IMAGE_OCR_MIN_CONFIDENCE,
    CACHE_IMAGE_OCR_MIN_WORDS,
    CACHE_IMAGE_TEXT_MIN_JACCARD,
    CACHE_IMAGE_TEXT_MIN_SHARED_TOKENS,
    OCR_TIMEOUT_SECONDS,
    TESSERACT_BIN,
    TESSERACT_LANGS,
)

logger = logging.getLogger("dejaq.services.image_text")

# Latin + digits + Hebrew block. Length >= 3 drops OCR noise ("a", "|", ".").
_TOKEN_RE = re.compile(r"[a-z0-9@._֐-׿]+")
# Per-word confidence at or above this counts as a "confident" word.
_WORD_CONFIDENCE_FLOOR = 60.0

_missing_binary_warned = False


@dataclass(frozen=True)
class OcrResult:
    tokens: frozenset[str]
    word_count: int          # words at or above _WORD_CONFIDENCE_FLOOR
    mean_confidence: float
    ok: bool                 # False when OCR could not run at all

    @property
    def is_document(self) -> bool:
        """Both criteria must hold, but confidence does the real separating.

        Measured: real documents scored mean confidence 83.3-92.2 with 54-373
        confident words. Unreadable photos-of-screens reached 60 confident words
        but only ~35 mean confidence, so the confidence floor rejects them. The
        word floor (CACHE_IMAGE_OCR_MIN_WORDS = 6) is deliberately low: a short
        crop read well - measured 9 words at 86.8 confidence - is a small
        document, not something to refuse. Amount of text is not the test; OCR
        quality is.
        """
        return (
            self.ok
            and self.mean_confidence >= CACHE_IMAGE_OCR_MIN_CONFIDENCE
            and self.word_count >= CACHE_IMAGE_OCR_MIN_WORDS
        )

    @property
    def is_ambiguous(self) -> bool:
        """Text is present but OCR cannot be trusted to have read it correctly.

        Neither served nor stored. Sending these to the pixel gate instead — what
        used to happen — was the largest single source of wrong answers: 1,712
        false merges on one measured corpus and 204 on another, because two
        different pages of text look near-identical to CLIP. It matters because
        only ~11% of real scanned business forms clear the confidence floor.

        The test is CONFIDENCE, not length. An earlier version keyed on "below the
        document bar", which made a short crop permanently un-cacheable even
        though OCR had read it perfectly (measured live: 9 words at 86.8
        confidence, refused on every request). A confident read of a little text
        is a small document; an unconfident read of a lot of text is garbage.

        Counts TOKENS rather than word_count, because word_count only includes
        words above the per-word confidence floor: a page where every word is read
        badly scores zero there and would slip through to the pixel gate — exactly
        the population that must not reach it.
        """
        return (
            self.ok
            and not self.is_document
            and len(self.tokens) >= CACHE_IMAGE_AMBIGUOUS_MIN_WORDS
            and self.mean_confidence < CACHE_IMAGE_OCR_MIN_CONFIDENCE
        )

    def token_string(self) -> str:
        """Stable scalar form for Chroma metadata (scalar-only)."""
        return " ".join(sorted(self.tokens))


def tokens_from_string(stored: str | None) -> frozenset[str]:
    return frozenset((stored or "").split())


# Rejected: a digit-token rule (require identifier overlap in a middle zone).
# It was built to separate documents sharing a template, and it failed three ways
# on measurement. (1) Swept jointly over 69,411 different-document pairs, EVERY
# configuration that kept it admitted false merges; the only zero-merge point was
# a single token threshold with the middle zone always rejecting. (2) It cost 10.7
# points of recall. (3) It fired on OCR junk — a mangled formula produced the
# "identifiers" 'קאס6ר' and '6087', which disagreed and vetoed a true match at
# 0.736 token overlap. An independent evaluation on real receipts reached the same
# conclusion: a document's numbers are a bag of many values and OCR reads a
# different subset each time. See docs/image-gate.md.


def extract(image_bytes: bytes) -> OcrResult:
    """Run OCR over the image. Never raises — a failure yields ok=False."""
    global _missing_binary_warned
    try:
        proc = subprocess.run(
            [TESSERACT_BIN, "stdin", "stdout", "-l", TESSERACT_LANGS, "--psm", "3", "tsv"],
            input=image_bytes,
            capture_output=True,
            timeout=OCR_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        if not _missing_binary_warned:
            logger.warning(
                "tesseract binary %r not found — image documents fall back to the "
                "pixel gate. Install it (brew install tesseract / apt install "
                "tesseract-ocr tesseract-ocr-heb) to enable document caching.",
                TESSERACT_BIN,
            )
            _missing_binary_warned = True
        return OcrResult(frozenset(), 0, 0.0, ok=False)
    except subprocess.TimeoutExpired:
        logger.warning("OCR timed out after %.1fs; treating image as a photo", OCR_TIMEOUT_SECONDS)
        return OcrResult(frozenset(), 0, 0.0, ok=False)
    except Exception:
        logger.exception("OCR failed; treating image as a photo")
        return OcrResult(frozenset(), 0, 0.0, ok=False)

    if proc.returncode != 0:
        logger.warning("tesseract exited %d; treating image as a photo", proc.returncode)
        return OcrResult(frozenset(), 0, 0.0, ok=False)

    return _parse_tsv(proc.stdout.decode("utf-8", errors="replace"))


def ocr_plaintext(image_bytes: bytes) -> str:
    """OCR an image to READABLE prose, preserving word order.

    Separate from `extract`: that function reads TSV to derive per-word confidence
    and a token BAG for the image gate, which throws word order away. The RAG
    knowledge layer ingests an image's text to ground an answer, so it wants the
    text as written. Reuses the same binary/languages/timeout config. Never raises
    — a failure (missing binary, timeout, bad exit) returns "".
    """
    global _missing_binary_warned
    try:
        proc = subprocess.run(
            [TESSERACT_BIN, "stdin", "stdout", "-l", TESSERACT_LANGS, "--psm", "3"],
            input=image_bytes,
            capture_output=True,
            timeout=OCR_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        if not _missing_binary_warned:
            logger.warning(
                "tesseract binary %r not found — image knowledge cannot be OCR'd.",
                TESSERACT_BIN,
            )
            _missing_binary_warned = True
        return ""
    except subprocess.TimeoutExpired:
        logger.warning("OCR timed out after %.1fs", OCR_TIMEOUT_SECONDS)
        return ""
    except Exception:
        logger.exception("OCR failed")
        return ""
    if proc.returncode != 0:
        logger.warning("tesseract exited %d", proc.returncode)
        return ""
    return proc.stdout.decode("utf-8", errors="replace").strip()


def _parse_tsv(tsv: str) -> OcrResult:
    """Pure/testable: TSV rows -> tokens + confidence stats."""
    confidences: list[float] = []
    text_parts: list[str] = []
    reader = csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE)
    for row in reader:
        word = (row.get("text") or "").strip()
        if not word:
            continue
        try:
            conf = float(row.get("conf", -1))
        except (TypeError, ValueError):
            continue
        if conf < 0:
            continue
        confidences.append(conf)
        text_parts.append(word)

    if not confidences:
        return OcrResult(frozenset(), 0, 0.0, ok=True)

    tokens = frozenset(t for t in _TOKEN_RE.findall(" ".join(text_parts).lower()) if len(t) >= 3)
    confident = sum(1 for c in confidences if c >= _WORD_CONFIDENCE_FLOOR)
    return OcrResult(
        tokens=tokens,
        word_count=confident,
        mean_confidence=sum(confidences) / len(confidences),
        ok=True,
    )


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


@dataclass(frozen=True)
class TextMatch:
    matched: bool
    token_jaccard: float


def matches(new: frozenset[str], stored: frozenset[str]) -> TextMatch:
    """Same document when the two OCR vocabularies overlap past one threshold.

    0.85 is the measured zero-false-merge point. It was 0.80, on the evidence
    that no two genuinely different documents exceeded 0.798 — two exam papers
    for one course differing only by a date, a time and one letter. That held
    only because the corpus contained no two receipts from one shop: measured on
    real scanned receipts, two from one restaurant with the same items and the
    same total, differing only in invoice number and date, reach 0.848.

    It is deliberately one number rather than a rule with zones. Four independent
    approaches (word order, page layout, structured fields, noise-robust text)
    were measured against this same data and none beat a plain threshold without
    admitting merges somewhere: the difference between two near-duplicate
    documents is a small localised edit, and no global similarity score isolates
    it. Recall is therefore low; a miss costs one API call, a merge serves
    someone else's document. See docs/image-gate.md.
    """
    tj = _jaccard(new, stored)
    enough = len(new & stored) >= CACHE_IMAGE_TEXT_MIN_SHARED_TOKENS
    return TextMatch(enough and tj >= CACHE_IMAGE_TEXT_MIN_JACCARD, tj)


def _self_test() -> None:
    def tsv(rows: list[tuple[str, float]]) -> str:
        head = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"
        body = "\n".join(f"5\t1\t1\t1\t1\t{i}\t0\t0\t1\t1\t{c}\t{w}" for i, (w, c) in enumerate(rows))
        return head + "\n" + body + "\n"

    # Confidence decides, not length.
    doc = _parse_tsv(tsv([(f"word{i}", 95.0) for i in range(60)]))
    assert doc.ok and doc.is_document, "confident wordy page must be a document"

    # The live regression: a short crop read perfectly is a small document, not
    # something to refuse. Measured at 9 words / 86.8 confidence.
    crop = _parse_tsv(tsv([(f"word{i}", 86.8) for i in range(9)]))
    assert crop.is_document, "a confident short crop must be cacheable"
    assert not crop.is_ambiguous

    garbage = _parse_tsv(tsv([(f"word{i}", 30.0) for i in range(200)]))
    assert not garbage.is_document, "low-confidence text is not a document (angled screen photo)"
    assert garbage.is_ambiguous, "unreliable OCR must be refused, not sent to the pixel gate"
    assert not doc.is_ambiguous, "a document is not ambiguous"

    assert _parse_tsv("").word_count == 0
    assert not _parse_tsv("").is_ambiguous, "no text at all is a photo, not ambiguous"
    # Rows tesseract emits with conf=-1 (layout rows) must not count.
    assert _parse_tsv(tsv([("ignored", -1.0)])).word_count == 0

    # A ratio over a couple of tokens is noise: never a match, however "identical".
    tiny = frozenset({"abc", "def"})
    assert not matches(tiny, tiny).matched, "two shared tokens is not evidence"

    # Same document matches; different documents do not. Ten shared tokens with
    # one extra on one side scores 0.909 — clear of the threshold rather than
    # balanced on it, so this fixture tests the rule and not the constant.
    a = frozenset({"complex", "analysis", "course", "142180", "boazc",
                   "semester", "lecture", "credits", "faculty", "syllabus"})
    a2 = a | {"extra"}
    assert matches(a, a2).matched, "same document with one extra token must match"

    # The measured false-merge case: shared template, different course. Rejected
    # on word overlap alone (0.578), with no identifier rule involved.
    tmpl = {"school", "computer", "science", "credits", "semester", "syllabus", "faculty", "hours"}
    t1 = frozenset(tmpl | {"142180", "complex"})
    t2 = frozenset(tmpl | {"142241", "cloud"})
    m = matches(t1, t2)
    assert not m.matched, f"different courses on one template must not match (tj={m.token_jaccard:.3f})"

    # Either side of the threshold. Two 100-token documents sharing S tokens
    # overlap S/(200-S), so 85 shared -> 0.739 (reject) and 95 -> 0.905 (accept).
    # The measured worst different-document pair — two receipts from one
    # restaurant differing by invoice number and date — sat at 0.848.
    shared = [f"s{i}" for i in range(95)]
    base = frozenset(shared + [f"a{i}" for i in range(5)])
    near_miss = frozenset(shared[:85] + [f"b{i}" for i in range(15)])
    near_hit = frozenset(shared + [f"c{i}" for i in range(5)])
    assert not matches(base, near_miss).matched, "0.74 overlap must not be served"
    assert matches(base, near_hit).matched, "0.90 overlap must be served"
    assert matches(base, base).matched, "identical documents must match"

    # Round-trip through the Chroma scalar form.
    assert tokens_from_string(OcrResult(a, 10, 90.0, True).token_string()) == a
    assert tokens_from_string(None) == frozenset()
    print("self-test passed")


if __name__ == "__main__":
    _self_test()
