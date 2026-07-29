"""File-anchored cache hits end-to-end through /v1/responses.

Exercises the real pipeline (router → gate → validator → serve) with a stubbed
memory and validator, the same harness shape as test_image_hit_validation.py.
What these check that test_file_gate.py cannot: that the gate is actually wired
into the request path, that a file entry is unreachable without its file, and
that a file hit is served under the attachment rules (question-vs-question
validation, no context adjuster).
"""
import base64

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import openai_compat
from app.services import file_text
from app.services.memory_chromaDB import CacheLookupResult
from tests.test_file_gate import make_pdf
from tests.test_openai_compat_smoke import (
    _AUTH,
    StubAdjuster,
    StubEnricher,
    StubNormalizer,
)

CACHED_ANSWER = "The termination clause allows either party to exit with 30 days' notice."
DOC_TEXT = " ".join(f"clause{i}" for i in range(45))
OTHER_TEXT = DOC_TEXT + " and one additional paragraph entirely"

PDF_A = make_pdf(DOC_TEXT)
PDF_B = make_pdf(OTHER_TEXT)
SHA_A = file_text.extract(PDF_A, "application/pdf", "a.pdf").sha


@pytest.fixture(autouse=True)
def _stub_api_key(monkeypatch):
    from app.middleware.api_key import _KEY_CACHE

    monkeypatch.setattr(
        _KEY_CACHE, "resolve", lambda token: ("demo", 1) if token == "test-key" else None
    )


class FileHitMemory:
    """One entry anchored to PDF_A, close enough on text to need validation."""

    def __init__(self, file_sha: str = SHA_A, file_kind: str = "pdf"):
        self.file_sha = file_sha
        self.file_kind = file_kind

    def lookup_cache(self, clean_query: str):
        return CacheLookupResult(
            hit=True,
            generalized_answer=CACHED_ANSWER,
            entry_id="doc-file",
            distance=0.0753,  # above VALIDATOR_SKIP_DISTANCE, so the validator runs
            matched_query="what does the termination clause say?",
            file_sha=self.file_sha,
            file_kind=self.file_kind,
        )

    def increment_hit_count(self, doc_id: str):
        return None

    def count_file_entries(self, file_sha: str) -> int:
        return 1 if file_sha == self.file_sha else 0


class RecordingValidator:
    def __init__(self, accept: bool = True):
        self.accept = accept
        self.kwargs: dict = {}

    async def validate(self, new_query, cached_query, cached_answer, **kwargs):
        self.kwargs = kwargs
        return self.accept, "VALID" if self.accept else "INVALID"


class TrackingAdjuster(StubAdjuster):
    def __init__(self):
        self.adjust_calls: list[str] = []

    async def adjust(self, original_query: str, general_answer: str) -> str:
        self.adjust_calls.append(general_answer)
        return "ADJUSTED — blind rewrite"


def _patch_pipeline(monkeypatch, *, validator, adjuster, memory):
    async def _noop_log(*a, **k):
        return None

    monkeypatch.setattr(
        openai_compat, "_services_for_model_profile",
        lambda profile: openai_compat.ModelServices(
            normalizer=StubNormalizer(), llm_router=None,
            adjuster=adjuster, enricher=StubEnricher(), validator=validator,
        ),
    )
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: memory)
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)
    monkeypatch.setattr(openai_compat, "USE_CELERY", False)


def _post(
    query: str,
    *,
    pdf: bytes | None = None,
    markdown: bytes | None = None,
    sticky: bool = False,
):
    content: list[dict] = [{"type": "input_text", "text": query}]
    if pdf is not None:
        content.append({
            "type": "input_file", "filename": "contract.pdf",
            "file_data": "data:application/pdf;base64," + base64.b64encode(pdf).decode(),
        })
    if markdown is not None:
        content.append({
            "type": "input_file", "filename": "notes.md",
            "file_data": "data:text/markdown;base64," + base64.b64encode(markdown).decode(),
        })
    headers = dict(_AUTH)
    if sticky:
        headers["X-DejaQ-Attachment-Sticky"] = "true"
    return TestClient(app, headers=headers).post(
        "/v1/responses",
        json={"model": "gpt-4o", "input": [{"role": "user", "content": content}], "stream": False},
    )


def test_same_pdf_is_served_from_cache(monkeypatch):
    validator = RecordingValidator(accept=True)
    adjuster = TrackingAdjuster()
    _patch_pipeline(monkeypatch, validator=validator, adjuster=adjuster, memory=FileHitMemory())

    resp = _post("what are the termination terms?", pdf=PDF_A)

    assert resp.status_code == 200
    assert resp.json()["output_text"] == CACHED_ANSWER
    assert resp.headers["x-dejaq-tier"] == "cache"
    # Served under the attachment rules: question-vs-question mode requested
    # (ValidatorService is what drops the answer in that mode — asserted against
    # the real service in test_image_hit_validation.py)...
    assert validator.kwargs.get("attachment_anchored") is True
    # ...and no blind rewrite of an answer about content the adjuster cannot read.
    assert adjuster.adjust_calls == []


def test_a_different_pdf_is_not_served_the_cached_answer(monkeypatch):
    """The false-merge check. It replaces the threshold sweep the image gate
    needs: with exact hashing, one differing document is enough to prove it."""
    validator = RecordingValidator(accept=True)
    _patch_pipeline(
        monkeypatch, validator=validator, adjuster=TrackingAdjuster(), memory=FileHitMemory()
    )

    resp = _post("what are the termination terms?", pdf=PDF_B)

    assert resp.headers.get("x-dejaq-tier") != "cache"
    assert CACHED_ANSWER not in resp.text


def test_a_file_entry_is_unreachable_without_the_file(monkeypatch):
    """A text-only ask must never be served an answer about a document the
    asker did not attach, however close the questions are."""
    _patch_pipeline(
        monkeypatch, validator=RecordingValidator(True),
        adjuster=TrackingAdjuster(), memory=FileHitMemory(),
    )

    resp = _post("what are the termination terms?")

    assert resp.headers.get("x-dejaq-tier") != "cache"
    assert CACHED_ANSWER not in resp.text


def test_kinds_never_mix(monkeypatch):
    """A markdown file must not match a pdf entry, even at the same hash."""
    md = DOC_TEXT.encode()
    md_sha = file_text.extract(md, "text/markdown", "notes.md").sha
    _patch_pipeline(
        monkeypatch, validator=RecordingValidator(True), adjuster=TrackingAdjuster(),
        memory=FileHitMemory(file_sha=md_sha, file_kind="pdf"),
    )

    resp = _post("what are the termination terms?", markdown=md)

    assert resp.headers.get("x-dejaq-tier") != "cache"


def test_validator_rejection_is_not_served(monkeypatch):
    """The hash proves the FILE matches; it says nothing about whether the two
    questions want the same thing, so the validator stays load-bearing."""
    _patch_pipeline(
        monkeypatch, validator=RecordingValidator(accept=False),
        adjuster=TrackingAdjuster(), memory=FileHitMemory(),
    )

    resp = _post("who signed it?", pdf=PDF_A)

    assert resp.headers.get("x-dejaq-tier") != "cache"
    assert CACHED_ANSWER not in resp.text


def test_log_says_when_we_hold_the_file_but_the_question_missed(monkeypatch, caplog):
    """The diagnostic that makes these logs worth reading.

    Re-uploading a known document with an unrelated question produces no cache
    candidate, so the file is never compared. Without this note that logs
    identically to uploading a document nobody has ever sent — two different
    problems with two different fixes.
    """
    class KnownFileNoTextMatch(FileHitMemory):
        def lookup_cache(self, clean_query: str):
            return CacheLookupResult(hit=False, nearest_distance=0.31,
                                     nearest_prompt="what does the termination clause say?")

        def store_interaction(self, *args, **kwargs):
            return "id"

    _patch_pipeline(
        monkeypatch, validator=RecordingValidator(True),
        adjuster=TrackingAdjuster(), memory=KnownFileNoTextMatch(),
    )

    with caplog.at_level("INFO", logger="dejaq.router.openai_compat"):
        _post("who is the CEO of the counterparty?", pdf=PDF_A)

    line = next(m for m in caplog.messages if "file_gate NOT REACHED" in m)
    assert "this exact file IS cached" in line
    assert "the question was what missed, not the file" in line


def test_log_says_whether_the_file_was_carried_from_an_earlier_turn(monkeypatch, caplog):
    """The chat app pins an attachment so follow-ups re-send it. A REJECT on a
    carried turn means the SAME bytes hashed differently — a transport or
    extraction bug — while a REJECT on a fresh turn just means two documents
    differ. The lines are otherwise identical, so the marker is the only way to
    tell those apart in a log."""
    _patch_pipeline(
        monkeypatch, validator=RecordingValidator(True),
        adjuster=TrackingAdjuster(), memory=FileHitMemory(),
    )

    with caplog.at_level("INFO", logger="dejaq.router.openai_compat"):
        _post("what are the termination terms?", pdf=PDF_A)
    assert "freshly-attached" in next(m for m in caplog.messages if m.startswith("file kind="))

    caplog.clear()
    with caplog.at_level("INFO", logger="dejaq.router.openai_compat"):
        _post("who signed it?", pdf=PDF_A, sticky=True)
    assert "carried-over" in next(m for m in caplog.messages if m.startswith("file kind="))


def test_scanned_pdf_answers_but_is_never_stored(monkeypatch):
    """No text layer means no identity: answered normally, never cached."""
    stored: list[tuple] = []

    class NoHitMemory(FileHitMemory):
        def lookup_cache(self, clean_query: str):
            return CacheLookupResult(hit=False)

        def store_interaction(self, *args, **kwargs):
            stored.append((args, kwargs))
            return "id"

    _patch_pipeline(
        monkeypatch, validator=RecordingValidator(True),
        adjuster=TrackingAdjuster(), memory=NoHitMemory(),
    )

    resp = _post("what does this say?", pdf=make_pdf(""))

    # 402 (no provider credential in tests) still proves the routing decision;
    # what matters here is that nothing was written to the cache.
    assert resp.status_code in (200, 402, 422)
    assert stored == []
