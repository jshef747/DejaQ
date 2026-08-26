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
REPO_A = "github:acme/widgets"
REPO_B = "github:acme/gadgets"
REPO_A_DOC_IDS = [11, 12, 13]


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
    # Same for a GROUP reference: the repo's member ids are resolved from the
    # catalog before the pipeline runs. REPO_A is populated, everything else is
    # an unknown group.
    monkeypatch.setattr(
        openai_responses.rag_document_repo, "list_for_group",
        lambda session, workspace_id, group_key: (
            [SimpleNamespace(id=i) for i in REPO_A_DOC_IDS] if group_key == REPO_A else []
        ),
    )


def _post(query: str, *, rag_document_id: int | None = None, rag_group_key: str | None = None):
    body = {"model": "gpt-4o", "input": query, "stream": False}
    if rag_document_id is not None:
        body["rag_document_id"] = rag_document_id
    if rag_group_key is not None:
        body["rag_group_key"] = rag_group_key
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
        file_sha=None, file_kind=None, rag_document_id=None, rag_group_key=None,
        authored=None, rag_document_ids=None,
    ) -> str:
        doc_id = derive_doc_id(
            normalized_query, file_sha, image_text=image_text, image_dhash=image_dhash,
            rag_document_id=rag_document_id, rag_group_key=rag_group_key,
        )
        self.stored.append({
            "doc_id": doc_id,
            "normalized_query": normalized_query,
            "generalized_answer": generalized_answer,
            "rag_document_id": rag_document_id,
            "rag_group_key": rag_group_key,
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
    monkeypatch.setattr(openai_compat.rag_service, "retrieve_by_documents", lambda *a, **k: [])

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


# --- Whole-repository references -------------------------------------------
#
# Same gate, one level up: a reference can pin ONE document (rag_document_id)
# or a whole imported repository (rag_group_key, "github:{owner}/{repo}", one
# catalog row per file). The exact-equality rule is unchanged - it just runs on
# the group key as well, so a repo-scoped answer and a single-file answer into
# that same repo never reach each other.


class GroupHitMemory:
    """One entry anchored to REPO_A, in the validator-guarded band."""

    def __init__(self, rag_group_key: str = REPO_A):
        self.rag_group_key = rag_group_key

    def lookup_cache(self, clean_query: str):
        return CacheLookupResult(
            hit=True,
            generalized_answer=CACHED_ANSWER,
            entry_id="doc-rag-group",
            distance=0.18,
            matched_query=ORIGINAL_QUESTION,
            rag_group_key=self.rag_group_key,
            requires_validation=True,
        )

    def increment_hit_count(self, doc_id: str):
        return None


def test_same_repository_paraphrase_is_served_from_cache(monkeypatch):
    validator = RecordingValidator(accept=True)
    adjuster = TrackingAdjuster()
    _patch_pipeline(monkeypatch, validator=validator, adjuster=adjuster, memory=GroupHitMemory())

    resp = _post(PARAPHRASE_QUESTION, rag_group_key=REPO_A)

    assert resp.status_code == 200
    assert resp.json()["output_text"] == CACHED_ANSWER
    assert resp.headers["x-dejaq-tier"] == "cache"
    # Served under the same attachment/reference rules as a single document.
    assert validator.kwargs.get("attachment_anchored") is True
    assert adjuster.adjust_calls == []
    assert resp.headers["x-dejaq-rag-group-key"] == REPO_A
    assert "x-dejaq-rag-document-id" not in resp.headers
    assert resp.headers["x-dejaq-rag-document-title"] == "acme/widgets"


def test_a_different_repository_is_not_served_the_cached_answer(monkeypatch):
    _patch_pipeline(
        monkeypatch, validator=RecordingValidator(True),
        adjuster=TrackingAdjuster(), memory=GroupHitMemory(),
    )
    monkeypatch.setattr(
        openai_responses.rag_document_repo, "list_for_group",
        lambda session, workspace_id, group_key: [SimpleNamespace(id=99)],
    )

    resp = _post(PARAPHRASE_QUESTION, rag_group_key=REPO_B)

    assert resp.headers.get("x-dejaq-tier") != "cache"
    assert CACHED_ANSWER not in resp.text


def test_a_single_file_reference_is_not_served_the_repository_answer(monkeypatch):
    """A repo-scoped answer read every file; a file-scoped question asked about
    one. Same repository, different question - not interchangeable."""
    _patch_pipeline(
        monkeypatch, validator=RecordingValidator(True),
        adjuster=TrackingAdjuster(), memory=GroupHitMemory(),
    )

    resp = _post(PARAPHRASE_QUESTION, rag_document_id=REPO_A_DOC_IDS[0])

    assert resp.headers.get("x-dejaq-tier") != "cache"
    assert CACHED_ANSWER not in resp.text


def test_a_repository_reference_is_not_served_a_single_file_answer(monkeypatch):
    """The mirror of the test above - the entry is pinned to one file."""
    _patch_pipeline(
        monkeypatch, validator=RecordingValidator(True),
        adjuster=TrackingAdjuster(), memory=ReferenceHitMemory(),
    )

    resp = _post(PARAPHRASE_QUESTION, rag_group_key=REPO_A)

    assert resp.headers.get("x-dejaq-tier") != "cache"
    assert CACHED_ANSWER not in resp.text


def test_repository_miss_retrieves_across_every_file_and_stores_verbatim(monkeypatch):
    """Retrieval is scoped to the whole group (not one file, not the whole
    workspace), and the answer is stored verbatim under the group key."""
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
    scopes: list = []

    def _capture(namespace, ids, query, top_k):
        scopes.append(list(ids))
        return []

    monkeypatch.setattr(openai_compat.rag_service, "retrieve_by_documents", _capture)

    resp = _post("some fresh question nobody asked yet", rag_group_key=REPO_A)

    assert resp.status_code == 200
    assert scopes == [REPO_A_DOC_IDS]
    assert adjuster.generalize_calls == []
    assert len(memory.stored) == 1
    assert memory.stored[0]["rag_group_key"] == REPO_A
    assert memory.stored[0]["rag_document_id"] is None


def test_an_unknown_group_key_is_rejected(monkeypatch):
    _patch_pipeline(
        monkeypatch, validator=RecordingValidator(True),
        adjuster=TrackingAdjuster(), memory=GroupHitMemory(),
    )

    resp = _post(PARAPHRASE_QUESTION, rag_group_key="github:nobody/nothing")

    assert resp.status_code == 400
    assert "not found" in resp.json()["detail"]


def test_both_reference_kinds_at_once_is_rejected(monkeypatch):
    _patch_pipeline(
        monkeypatch, validator=RecordingValidator(True),
        adjuster=TrackingAdjuster(), memory=GroupHitMemory(),
    )

    resp = _post(PARAPHRASE_QUESTION, rag_document_id=DOC_A_ID, rag_group_key=REPO_A)

    assert resp.status_code == 400
    assert "not both" in resp.json()["detail"]


def test_repository_and_file_references_get_different_entries():
    """The cache-key half: the same question against a repo, against one of its
    files, and with no reference at all must be three different entries."""
    q = "what does this code do"
    ids = {
        derive_doc_id(q, rag_group_key=REPO_A),
        derive_doc_id(q, rag_group_key=REPO_B),
        derive_doc_id(q, rag_document_id=DOC_A_ID),
        derive_doc_id(q),
    }
    assert len(ids) == 4
