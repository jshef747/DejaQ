"""Explicit `@`-reference cache hits end-to-end through /v1/responses.

Mirrors test_file_hit_pipeline.py's shape exactly, because the reference gate
IS the file gate's shape: exact-id equality, running whenever either side
carries a reference, gating on an id in the entry's metadata rather than
concatenating it into the embedded text.

The addendum's requirement under test: a referenced document's answer must be
reusable across a PARAPHRASE (not just an exact repeat) — same document +
semantically similar question = hit; a different document, or no document at
all, must never be served that answer.
"""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import openai_compat, openai_responses
from app.services.memory_chromaDB import CacheLookupResult, derive_doc_id
from tests.test_openai_compat_smoke import _AUTH, StubAdjuster, StubEnricher, StubNormalizer

CACHED_ANSWER = "Building 7's badge code rotates every 90 days."
ORIGINAL_QUESTION = "how often does the building 7 badge code rotate?"
PARAPHRASE_QUESTION = "how frequently does the badge code for building 7 change?"
DOC_A_ID = 7
DOC_B_ID = 8


@pytest.fixture(autouse=True)
def _stub_api_key(monkeypatch):
    from app.middleware.api_key import _KEY_CACHE

    monkeypatch.setattr(
        _KEY_CACHE, "resolve", lambda token: ("demo", 1) if token == "test-key" else None
    )


class ReferenceHitMemory:
    """One entry anchored to DOC_A_ID, sitting in the validator-guarded band —
    a paraphrase, not an exact repeat, is the whole point of the addendum."""

    def __init__(self, rag_document_id: int = DOC_A_ID):
        self.rag_document_id = rag_document_id

    def lookup_cache(self, clean_query: str):
        return CacheLookupResult(
            hit=True,
            generalized_answer=CACHED_ANSWER,
            entry_id="doc-rag",
            distance=0.18,  # inside the band (0.15-0.20), so the validator runs
            matched_query=ORIGINAL_QUESTION,
            rag_document_id=self.rag_document_id,
            requires_validation=True,
        )

    def increment_hit_count(self, doc_id: str):
        return None


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
    # openai_responses.py validates rag_document_id against the real catalog
    # before the pipeline ever runs — stub that existence check rather than
    # seeding a real DB row; these tests are about the CACHE gate, not ingestion.
    monkeypatch.setattr(
        openai_responses.rag_document_repo, "get",
        lambda session, workspace_id, doc_id: SimpleNamespace(title="Building 7 Access Procedures"),
    )


def _post(query: str, *, rag_document_id: int | None = None):
    body = {"model": "gpt-4o", "input": query, "stream": False}
    if rag_document_id is not None:
        body["rag_document_id"] = rag_document_id
    return TestClient(app, headers=_AUTH).post("/v1/responses", json=body)


def test_same_document_paraphrase_is_served_from_cache(monkeypatch):
    """Scenario 1 from the addendum: reference A, ask a paraphrase — must hit."""
    validator = RecordingValidator(accept=True)
    adjuster = TrackingAdjuster()
    _patch_pipeline(monkeypatch, validator=validator, adjuster=adjuster, memory=ReferenceHitMemory())

    resp = _post(PARAPHRASE_QUESTION, rag_document_id=DOC_A_ID)

    assert resp.status_code == 200
    assert resp.json()["output_text"] == CACHED_ANSWER
    assert resp.headers["x-dejaq-tier"] == "cache"
    assert resp.headers["x-dejaq-cache-distance"] == "0.1800"
    # Served under the attachment/reference rules: question-vs-question mode,
    # no blind rewrite of an answer the adjuster cannot ground-check.
    assert validator.kwargs.get("attachment_anchored") is True
    assert adjuster.adjust_calls == []
    assert resp.headers["x-dejaq-rag-document-id"] == str(DOC_A_ID)


def test_a_different_referenced_document_is_not_served_the_cached_answer(monkeypatch):
    """Scenario 2 from the addendum: reference B, ask the same paraphrase —
    must NOT be served A's answer."""
    validator = RecordingValidator(accept=True)
    _patch_pipeline(
        monkeypatch, validator=validator, adjuster=TrackingAdjuster(), memory=ReferenceHitMemory()
    )

    resp = _post(PARAPHRASE_QUESTION, rag_document_id=DOC_B_ID)

    assert resp.headers.get("x-dejaq-tier") != "cache"
    assert CACHED_ANSWER not in resp.text


def test_an_unreferenced_request_is_not_served_the_cached_answer(monkeypatch):
    """Scenario 3 from the addendum: no reference at all — must NOT be served
    A's answer, however close the paraphrase is."""
    validator = RecordingValidator(accept=True)
    _patch_pipeline(
        monkeypatch, validator=validator, adjuster=TrackingAdjuster(), memory=ReferenceHitMemory()
    )

    resp = _post(PARAPHRASE_QUESTION)

    assert resp.headers.get("x-dejaq-tier") != "cache"
    assert CACHED_ANSWER not in resp.text


def test_validator_rejection_is_not_served(monkeypatch):
    """The id proves the DOCUMENT matches; it says nothing about whether the
    two questions want the same thing, so the validator stays load-bearing."""
    _patch_pipeline(
        monkeypatch, validator=RecordingValidator(accept=False),
        adjuster=TrackingAdjuster(), memory=ReferenceHitMemory(),
    )

    resp = _post("who installed the badge readers?", rag_document_id=DOC_A_ID)

    assert resp.headers.get("x-dejaq-tier") != "cache"
    assert CACHED_ANSWER not in resp.text


class RecordingStoreMemory:
    """Derives entry ids the same way the real MemoryService does, so a
    mismatch between the id handed to the client and the id of the row on
    disk (or a missing rag_document_id argument) shows up as one."""

    def __init__(self):
        self.stored: list[dict] = []

    def lookup_cache(self, clean_query: str):
        return CacheLookupResult(hit=False)

    def get_entry_metadata(self, entry_id: str):
        # Nothing stored yet on a fresh stub, so never human-authored — lets
        # is_human_authored's real code path run instead of failing open on
        # a missing method.
        return None

    def store_interaction(
        self, normalized_query, generalized_answer, original_query, user_id,
        image_dhash=None, image_clip=None, image_kind=None, image_text=None,
        file_sha=None, file_kind=None, rag_document_id=None,
        authored=None, rag_document_ids=None,
    ) -> str:
        doc_id = derive_doc_id(
            normalized_query, file_sha, image_text=image_text, image_dhash=image_dhash,
            rag_document_id=rag_document_id,
        )
        self.stored.append({
            "doc_id": doc_id,
            "normalized_query": normalized_query,
            "generalized_answer": generalized_answer,
            "rag_document_id": rag_document_id,
            "rag_document_ids": rag_document_ids,
        })
        return doc_id


class BlindGeneralizer(TrackingAdjuster):
    def __init__(self):
        super().__init__()
        self.generalize_calls: list[str] = []

    async def generalize(self, answer: str) -> str:
        self.generalize_calls.append(answer)
        return "a rewritten, generalized answer"


class StubLocalRouter:
    """Answers every request locally with a fixed string — stands in for the
    real Ollama-backed router so a genuine cache MISS can complete."""

    async def generate_local_response(self, query, **kwargs):
        return "Building 7's badge code rotates every 90 days.", None, "stop"


def test_referenced_miss_stores_the_answer_verbatim_with_the_document_id(monkeypatch):
    """Serving rule 7: stored verbatim (no generalize() call, which cannot see
    the referenced document), tagged with the document id that gates it."""
    memory = RecordingStoreMemory()
    adjuster = BlindGeneralizer()
    _patch_pipeline(monkeypatch, validator=RecordingValidator(True), adjuster=adjuster, memory=memory)
    monkeypatch.setattr(
        openai_compat, "_services_for_model_profile",
        lambda profile, llm_config=None: openai_compat.ModelServices(
            normalizer=StubNormalizer(), llm_router=StubLocalRouter(),
            adjuster=adjuster, enricher=StubEnricher(), validator=RecordingValidator(True),
        ),
    )
    monkeypatch.setattr(openai_compat.rag_service, "retrieve_by_document", lambda *a, **k: [])

    resp = _post("some fresh question nobody asked yet", rag_document_id=DOC_A_ID)

    assert resp.status_code == 200
    assert adjuster.generalize_calls == []
    assert len(memory.stored) == 1
    assert memory.stored[0]["rag_document_id"] == DOC_A_ID


def test_two_documents_asked_the_same_question_get_two_entries():
    """The cache-key half of item 6: `derive_doc_id` must not let two different
    referenced documents asked the same question collide into one entry."""
    q = "summarise this document"
    id_a = derive_doc_id(q, rag_document_id=DOC_A_ID)
    id_b = derive_doc_id(q, rag_document_id=DOC_B_ID)
    id_none = derive_doc_id(q)
    assert len({id_a, id_b, id_none}) == 3


class ReferencePoolMemory(ReferenceHitMemory):
    """A pool whose FIRST passer is the anchored entry and whose second is an
    ordinary text entry - the shape the candidate-gate loop scans when the
    alternative-drafts tie-breaker is on."""

    def lookup_cache_pool(self, clean_query: str):
        return (
            [
                self.lookup_cache(clean_query),
                CacheLookupResult(
                    hit=True,
                    generalized_answer="An unrelated cached answer.",
                    entry_id="doc-plain",
                    distance=0.185,
                    matched_query="something else entirely",
                    requires_validation=True,
                ),
            ],
            0.18,
            ORIGINAL_QUESTION,
        )


def test_the_reported_anchoring_is_the_served_entrys_own(monkeypatch):
    """A referenced request reports its OWN document, and is never offered a
    second answer - with the alternative-drafts tie-breaker switched on.

    Merging staging's reference anchoring into this branch's restructured
    candidate loop (which collects several passers instead of breaking on the
    first) puts `_rag_anchored` inside the `if not _gate_passed:` guard, exactly
    like _image_anchored/_file_anchored, so it always describes the SERVED
    entry. Note what the loop makes of that: when the request carries a
    reference, a candidate either matches its document id (and is anchored) or
    is rejected by the gate, so a non-anchored second passer cannot exist and
    the mis-fold is unreachable rather than merely unlikely. The assignment
    stays inside the guard because that is the rule the other two follow and it
    must survive a future change to the gate - not because this test could tell
    the two apart.

    What this DOES pin is the pair of outcomes: the header names DOC_A even
    with a second pool candidate present, and `not _request_has_rag_ref` in
    `_want_drafts` keeps a chooser off a request whose correctness rests on the
    reference it carried.
    """
    validator = RecordingValidator(accept=True)
    _patch_pipeline(
        monkeypatch,
        validator=validator,
        adjuster=TrackingAdjuster(),
        memory=ReferencePoolMemory(),
    )
    # Drafts ON, which is what makes the loop scan past the first passer at
    # all - with the feature off the whole hazard is unreachable and the test
    # would be vacuous.
    monkeypatch.setattr(
        openai_compat,
        "_read_effective_llm_config",
        lambda slug, wid: openai_compat.EffectiveLlmConfig(
            external_model="gemini-2.5-flash",
            routing_threshold=0.3,
            drafts_enabled=True,
        ),
    )

    resp = _post(PARAPHRASE_QUESTION, rag_document_id=DOC_A_ID)

    assert resp.status_code == 200
    assert resp.json()["output_text"] == CACHED_ANSWER
    # The served entry is the anchored one, and the header names ITS document.
    assert resp.headers["x-dejaq-rag-document-id"] == str(DOC_A_ID)
    # And no second answer was offered for a request whose correctness rests on
    # the reference it carried.
    assert "x-dejaq-drafts" not in resp.headers
    assert "dejaq_drafts" not in resp.json()
