"""Routing + matching rules for the two-path image gate (no OCR binary needed)."""
import pytest

from app.routers.openai_compat import (
    _doc_id,
    _entry_image_kind,
    _evaluate_image_gate,
    _image_kind,
)
from app.services.image_fingerprint import ImageFingerprint
from app.services.image_text import OcrResult, matches, tokens_from_string
from app.services.memory_chromaDB import CacheLookupResult


def doc_ocr(tokens: set[str]) -> OcrResult:
    return OcrResult(frozenset(tokens), word_count=200, mean_confidence=90.0, ok=True)


def photo_ocr() -> OcrResult:
    return OcrResult(frozenset(), word_count=0, mean_confidence=0.0, ok=True)


FP = ImageFingerprint(dhash_hex="0f0f0f0f0f0f0f0f", clip_b64="")


def entry(**kw) -> CacheLookupResult:
    return CacheLookupResult(hit=True, entry_id="e", distance=0.01, matched_query="q", **kw)


def test_kind_from_ocr():
    assert _image_kind(doc_ocr({"alpha", "beta"})) == "document"
    assert _image_kind(photo_ocr()) == "photo"
    assert _image_kind(None) == "photo"


def test_entry_kind_infers_from_stored_fingerprints():
    """Entries written before image_kind existed must still classify correctly."""
    assert _entry_image_kind(entry()) == "text"
    assert _entry_image_kind(entry(image_text="alpha beta")) == "document"
    assert _entry_image_kind(entry(image_dhash="ff", image_clip="x")) == "photo"
    assert _entry_image_kind(entry(image_kind="photo")) == "photo"


@pytest.mark.parametrize(
    "request_kind,entry_kw",
    [
        ("photo", {"image_text": "alpha beta"}),      # photo must not match a document
        ("document", {"image_dhash": "ff", "image_clip": "x"}),  # and vice-versa
        ("photo", {}),                                 # nor a text-only entry
        ("document", {}),
    ],
)
def test_kinds_never_mix(request_kind, entry_kw):
    ok, reason, _ = _evaluate_image_gate(
        request_kind=request_kind,
        entry_kind=_entry_image_kind(entry(**entry_kw)),
        fingerprint=FP,
        ocr=doc_ocr({"a", "b"}),
        lookup=entry(**entry_kw),
    )
    assert not ok
    assert reason.startswith("kind_mismatch")


def test_document_served_when_words_agree():
    """Ten shared tokens and one extra scores 0.909 — clear of the 0.85 bar."""
    tokens = {"complex", "analysis", "course", "142180", "syllabus",
              "semester", "lecture", "credits", "faculty", "hours"}
    e = entry(image_kind="document", image_text=" ".join(sorted(tokens)))
    ok, reason, detail = _evaluate_image_gate(
        request_kind="document", entry_kind="document",
        fingerprint=None, ocr=doc_ocr(tokens | {"extra"}), lookup=e,
    )
    assert ok and reason == "text_pass"
    assert detail["token_jaccard"] > 0.85


def test_shared_template_different_identifiers_rejected():
    """The real false-merge case: same university template, different course.

    Measured at 0.578 token overlap live. It used to be rejected by a digit-token
    rule; that rule is gone (it admitted merges in every swept configuration and
    fired on OCR junk), so the single threshold now rejects it directly.
    """
    template = {"school", "computer", "science", "credits", "semester", "syllabus", "faculty"}
    stored = template | {"142180", "complex"}
    incoming = template | {"142241", "cloud"}
    e = entry(image_kind="document", image_text=" ".join(sorted(stored)))
    ok, reason, detail = _evaluate_image_gate(
        request_kind="document", entry_kind="document",
        fingerprint=None, ocr=doc_ocr(incoming), lookup=e,
    )
    assert not ok, "different courses on one template must not be served"
    assert reason == "text_mismatch"
    assert detail["token_jaccard"] < 0.85, "must fall below the measured safe threshold"


def test_document_without_ocr_is_not_served():
    e = entry(image_kind="document", image_text="alpha beta gamma")
    ok, reason, _ = _evaluate_image_gate(
        request_kind="document", entry_kind="document",
        fingerprint=None, ocr=None, lookup=e,
    )
    assert not ok and reason == "ocr_unavailable"


def test_photo_without_fingerprint_is_not_served():
    e = entry(image_kind="photo", image_dhash="ff", image_clip="x")
    ok, reason, _ = _evaluate_image_gate(
        request_kind="photo", entry_kind="photo",
        fingerprint=None, ocr=photo_ocr(), lookup=e,
    )
    assert not ok and reason == "fingerprint_failed"


def test_one_threshold_decides_regardless_of_digits():
    """Digits are no longer special: only word overlap decides."""
    a = frozenset({"alpha", "beta", "gamma", "delta", "epsilon"})
    near = frozenset({"alpha", "beta", "gamma", "delta", "zeta"})
    assert matches(a, a).matched
    assert not matches(a, near).matched, "0.67 overlap must fail the threshold"

    # Identical word overlap, one pair with digits and one without, must agree.
    with_digits = frozenset({"142180", "beta", "gamma", "delta", "epsilon"})
    assert matches(a, near).matched == matches(with_digits, near).matched


def test_ambiguous_images_are_never_served():
    """Real text, below the document bar: the pixel path used to take these."""
    # Text is present (tokens found) but read badly — the confidence is what
    # disqualifies it, not the amount of text.
    ambiguous = OcrResult(frozenset({"some", "words", "here", "more"}), word_count=8,
                          mean_confidence=55.0, ok=True)
    assert ambiguous.is_ambiguous and not ambiguous.is_document
    assert _image_kind(ambiguous) == "ambiguous"

    # It can never match a stored entry of any kind.
    for kw in ({"image_kind": "photo", "image_dhash": "ff", "image_clip": "x"},
               {"image_kind": "document", "image_text": "some words"}):
        ok, reason, _ = _evaluate_image_gate(
            request_kind="ambiguous", entry_kind=_entry_image_kind(entry(**kw)),
            fingerprint=FP, ocr=ambiguous, lookup=entry(**kw),
        )
        assert not ok and reason.startswith("kind_mismatch")


def test_a_blank_image_has_no_pixel_fingerprint():
    """A near-uniform page merged with every other blank page on CLIP+dHash."""
    from PIL import Image

    from app.services.image_fingerprint import tile_variety

    assert tile_variety(Image.new("RGB", (64, 64), (255, 255, 255))) < 10


def test_cropped_snippet_is_a_document():
    """A two-line crop of an exercise: 34 words at 84.8 confidence, measured live.

    The floor was 45, so this fell to the photo path and missed at hamming 36
    even though its token overlap with a re-crop was 0.833.
    """
    snippet = OcrResult(frozenset({"dtime", "הוכיחו"}), word_count=34, mean_confidence=84.8, ok=True)
    assert snippet.is_document

    # The confidence floor still rejects an unreadable photo of a screen.
    assert not OcrResult(frozenset(), word_count=60, mean_confidence=35.0, ok=True).is_document


def test_token_string_round_trip():
    tokens = frozenset({"alpha", "142180", "beta"})
    assert tokens_from_string(OcrResult(tokens, 5, 90.0, True).token_string()) == tokens


# --- entry identity -----------------------------------------------------------

def test_two_images_asked_the_same_question_get_separate_entries():
    """Without the image component in the id, the second upload would overwrite
    the first — and "what is in this image?" / "solve it" are the questions people
    actually ask, which the cache filter deliberately lets through despite being
    too short. Mirrors the file-side test in test_file_gate.py.
    """
    q = "what is in this image"

    # Documents are keyed by their OCR tokens.
    a = doc_ocr({"integral", "substitution"}).token_string()
    b = doc_ocr({"risotto", "parmesan"}).token_string()
    assert _doc_id(q, image_text=a) != _doc_id(q, image_text=b)

    # Photos have no readable text, so they are keyed by their dhash.
    assert _doc_id(q, image_dhash="0f0f0f0f0f0f0f0f") != _doc_id(q, image_dhash="f0f0f0f0f0f0f0f0")

    # A document and a photo never collide either.
    assert _doc_id(q, image_text=a) != _doc_id(q, image_dhash="0f0f0f0f0f0f0f0f")

    # Text entries keep their existing ids, so nothing already cached moves.
    assert _doc_id(q) == _doc_id(q, image_text=None, image_dhash=None)


def test_every_id_derivation_site_agrees():
    """The router, the Celery task and the store all write the same entry id.
    Three hand-rolled copies drifting apart is exactly how the overwrite bug
    reached production, so they share one function.
    """
    from app.services.memory_chromaDB import derive_doc_id
    from app.tasks.cache_tasks import _doc_id as task_doc_id

    assert _doc_id is derive_doc_id
    assert task_doc_id is derive_doc_id
