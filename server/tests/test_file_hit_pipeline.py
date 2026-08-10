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
from app.services.memory_chromaDB import CacheLookupResult, derive_doc_id
from tests.test_file_gate import make_pdf
from tests.test_openai_compat_smoke import (
    _AUTH,
    StubAdjuster,
    StubEnricher,
    StubNormalizer,
)

CACHED_ANSWER = "The termination clause allows either party to exit with 30 days' notice."
ORIGINAL_QUESTION = "what are the termination terms of this contract?"
TYPO_QUESTION = "waht are teh terminaton trems of this contarct?"
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
        lambda profile, llm_config=None: openai_compat.ModelServices(
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


class AliasLearningMemory(FileHitMemory):
    """A file-anchored entry, plus whatever aliases the router asks us to store.

    `store_alias` mirrors the real MemoryService exactly: it copies the parent's
    ANSWER and nothing else — no `file_sha`, no `file_kind`. That is the whole
    bug. An alias of a file-anchored entry is an ordinary text entry holding an
    answer about a document, and the file gate can no longer see anything to
    gate on.

    The seeded entry sits in the validator-guarded band (`requires_validation`),
    which is the only tier alias learning fires on.
    """

    def __init__(self):
        super().__init__()
        self.aliases: dict[str, str] = {}

    def lookup_cache(self, clean_query: str):
        if clean_query in self.aliases:
            return CacheLookupResult(
                hit=True,
                generalized_answer=CACHED_ANSWER,
                entry_id=self.aliases[clean_query],
                distance=0.0,
                matched_query=clean_query,
                # No file_sha/file_kind — precisely what store_alias writes.
            )
        return CacheLookupResult(
            hit=True,
            generalized_answer=CACHED_ANSWER,
            entry_id="doc-file",
            distance=0.1802,  # inside the band, so the validator runs
            matched_query=ORIGINAL_QUESTION,
            file_sha=self.file_sha,
            file_kind=self.file_kind,
            requires_validation=True,
        )

    def store_alias(self, alias_query: str, source_entry_id: str) -> str:
        doc_id = f"alias-{len(self.aliases)}"
        self.aliases[alias_query] = doc_id
        return doc_id


class SynchronousAliasWriter:
    """Runs `_store_alias_bg`'s work inline so the assertions are deterministic.

    The router fires alias learning through `asyncio.create_task`; whether that
    task gets a slice before TestClient tears the loop down is a race. Replacing
    only the background wrapper keeps the decision under test — the branch at
    the alias-learning call site — and makes the write itself synchronous.
    """

    def __init__(self, memory):
        self.memory = memory
        self.calls: list[tuple[str, str, str]] = []

    def __call__(self, namespace: str, alias_query: str, source_entry_id: str):
        self.calls.append((namespace, alias_query, source_entry_id))
        self.memory.store_alias(alias_query, source_entry_id)

        async def _already_done():
            return None

        return _already_done()


def test_no_alias_is_learned_for_a_file_anchored_hit(monkeypatch):
    """Alias learning must not launder a file answer into an ungated text entry.

    `store_alias` copies the answer and drops `file_sha`/`file_kind`, so an alias
    of a file-anchored entry is reachable by question text alone. Learning one
    would hand the next asker an answer about a document they never attached.
    """
    memory = AliasLearningMemory()
    alias_writer = SynchronousAliasWriter(memory)
    _patch_pipeline(
        monkeypatch, validator=RecordingValidator(True),
        adjuster=TrackingAdjuster(), memory=memory,
    )
    monkeypatch.setattr(openai_compat, "_store_alias_bg", alias_writer)

    resp = _post(TYPO_QUESTION, pdf=PDF_A)

    # The hit itself is legitimate: same file, validator accepted.
    assert resp.headers["x-dejaq-tier"] == "cache"
    assert resp.json()["output_text"] == CACHED_ANSWER
    # ...but nothing about it may be remembered as a text entry.
    assert alias_writer.calls == []
    assert memory.aliases == {}


def test_the_typod_phrasing_is_not_reachable_without_the_file(monkeypatch):
    """The end-to-end leak, in the shipped default configuration.

    A1 seeds a file-anchored entry; A2 asks the same thing with a typo and the
    same PDF, which hits and (before the fix) taught an alias; A3 asks the typo'd
    question with NO FILE AT ALL and was served the contract's answer.
    """
    memory = AliasLearningMemory()
    alias_writer = SynchronousAliasWriter(memory)
    _patch_pipeline(
        monkeypatch, validator=RecordingValidator(True),
        adjuster=TrackingAdjuster(), memory=memory,
    )
    monkeypatch.setattr(openai_compat, "_store_alias_bg", alias_writer)

    # A2 — typo'd question, file attached: a real, correctly gated cache hit.
    assert _post(TYPO_QUESTION, pdf=PDF_A).headers["x-dejaq-tier"] == "cache"

    # A3 — same typo'd question, nothing attached.
    resp = _post(TYPO_QUESTION)

    assert resp.headers.get("x-dejaq-tier") != "cache"
    assert CACHED_ANSWER not in resp.text


def test_alias_learning_still_works_for_a_plain_text_hit(monkeypatch):
    """The fix is scoped to attachment-anchored hits; text hits keep learning."""

    class TextBandMemory(AliasLearningMemory):
        def lookup_cache(self, clean_query: str):
            return CacheLookupResult(
                hit=True,
                generalized_answer=CACHED_ANSWER,
                entry_id="doc-text",
                distance=0.1802,
                matched_query=ORIGINAL_QUESTION,
                requires_validation=True,
            )

    memory = TextBandMemory()
    alias_writer = SynchronousAliasWriter(memory)
    _patch_pipeline(
        monkeypatch, validator=RecordingValidator(True),
        adjuster=TrackingAdjuster(), memory=memory,
    )
    monkeypatch.setattr(openai_compat, "_store_alias_bg", alias_writer)

    resp = _post(TYPO_QUESTION)

    assert resp.headers["x-dejaq-tier"] == "cache"
    assert [c[1] for c in alias_writer.calls] == [TYPO_QUESTION.lower()]


class RecordingStoreMemory:
    """Records what the background store actually wrote, and derives entry ids
    the same way the real MemoryService does — so a mismatch between the id
    handed to the client and the id of the row on disk shows up as one."""

    def __init__(self):
        self.stored: list[dict] = []

    def lookup_cache(self, clean_query: str):
        return CacheLookupResult(hit=False)

    def count_file_entries(self, file_sha: str) -> int:
        return 0

    def store_interaction(
        self, normalized_query, generalized_answer, original_query, user_id,
        image_dhash=None, image_clip=None, image_kind=None, image_text=None,
        file_sha=None, file_kind=None,
    ) -> str:
        doc_id = derive_doc_id(
            normalized_query, file_sha, image_text=image_text, image_dhash=image_dhash
        )
        self.stored.append({
            "doc_id": doc_id,
            "normalized_query": normalized_query,
            "generalized_answer": generalized_answer,
            "file_sha": file_sha,
            "file_kind": file_kind,
        })
        return doc_id


class BlindGeneralizer(TrackingAdjuster):
    """Stands in for Phi-3.5 on an answer it cannot see the source of. The real
    thing invents specifics; this one just marks that it ran."""

    def __init__(self):
        super().__init__()
        self.generalize_calls: list[str] = []

    async def generalize(self, answer: str) -> str:
        self.generalize_calls.append(answer)
        return "an agreed-upon period of notice"


class BrokenCeleryTask:
    """Redis down: apply_async raises and the router degrades to in-process."""

    def apply_async(self, *args, **kwargs):
        raise ConnectionError("Error 61 connecting to localhost:6379. Connection refused.")


def _patch_external_provider(monkeypatch, answer: str):
    class StubExternal:
        async def generate_response(self, request, provider=None, api_key=None):
            from app.schemas.chat import ExternalLLMResponse

            return ExternalLLMResponse(
                text=answer, model_used=request.model,
                prompt_tokens=5, completion_tokens=6, latency_ms=10.0,
            )

    monkeypatch.setattr(openai_compat, "_external_llm", StubExternal())
    monkeypatch.setattr(
        openai_compat,
        "get_workspace_provider_key",
        lambda session, workspace_id, provider: "sk-test-live",
    )
    monkeypatch.setattr(
        openai_compat, "_read_effective_llm_config",
        lambda workspace_slug, workspace_id: openai_compat.EffectiveLlmConfig(
            external_model="gpt-4o-mini", routing_threshold=0.0,
        ),
    )


PROVIDER_ANSWER = "Either party may terminate this agreement with thirty days written notice."


def _post_pdf_miss_with_broken_celery(monkeypatch, memory, adjuster):
    _patch_pipeline(monkeypatch, validator=RecordingValidator(True), adjuster=adjuster, memory=memory)
    monkeypatch.setattr(openai_compat, "USE_CELERY", True)
    monkeypatch.setattr(openai_compat, "generalize_and_store_task", BrokenCeleryTask())
    _patch_external_provider(monkeypatch, PROVIDER_ANSWER)
    return _post(ORIGINAL_QUESTION, pdf=PDF_A)


def test_celery_fallback_stores_the_file_identity(monkeypatch):
    """A broker outage must not turn a document answer into an ungated text entry.

    The Celery-dispatch-failure fallback passed the image arguments but stopped
    short of `file_sha`/`file_kind`, so both defaulted to None and the entry was
    written with no file identity at all — after which the file gate has nothing
    to gate on and a later question with no attachment is served the document's
    answer.
    """
    memory = RecordingStoreMemory()
    resp = _post_pdf_miss_with_broken_celery(monkeypatch, memory, BlindGeneralizer())

    assert resp.status_code == 200
    assert len(memory.stored) == 1
    entry = memory.stored[0]
    assert entry["file_sha"] == SHA_A
    assert entry["file_kind"] == "pdf"


def test_celery_fallback_does_not_generalize_an_attachment_answer(monkeypatch):
    """`if image_kind or file_kind` is what keeps attachment answers verbatim.

    With the file arguments dropped that test was false, so the generalizer —
    which cannot see the PDF — rewrote a specific contractual term into a vague
    paraphrase before it was stored.
    """
    memory = RecordingStoreMemory()
    adjuster = BlindGeneralizer()
    _post_pdf_miss_with_broken_celery(monkeypatch, memory, adjuster)

    assert adjuster.generalize_calls == []
    assert memory.stored[0]["generalized_answer"] == PROVIDER_ANSWER


def test_celery_fallback_response_id_addresses_the_entry_written(monkeypatch):
    """The id handed to the client is what /v1/feedback resolves. It is derived
    WITH the file hash, so an entry stored WITHOUT one is unaddressable."""
    memory = RecordingStoreMemory()
    resp = _post_pdf_miss_with_broken_celery(monkeypatch, memory, BlindGeneralizer())

    returned = resp.headers["x-dejaq-response-id"]
    assert returned.rsplit(":", 1)[1] == memory.stored[0]["doc_id"]


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
