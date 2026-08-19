"""A human-written cache answer must not be quietly replaced or aged out.

Edit & Save writes `authored="human"` onto the entry. Three separate mechanisms
would otherwise put the model's text back or drop the entry entirely, and each
one is guarded independently — this file covers all three plus the request-shape
rules that get an edit to them in the first place.
"""

import pytest
from pydantic import ValidationError

pytestmark = pytest.mark.no_model


# ── The background store must not overwrite an edit ───────────────────────────


class _FakeMemory:
    def __init__(self, existing: dict | None = None):
        self.existing = existing
        self.stored: list[tuple] = []

    def get_entry_metadata(self, doc_id):
        return self.existing

    def store_interaction(self, *args, **kwargs):
        self.stored.append((args, kwargs))
        return "doc1"


def test_celery_store_skips_a_human_authored_entry(monkeypatch):
    """The race is real: a miss advertises its response_id BEFORE generation, so
    an edit can land while this task is still queued behind a generalize()."""
    from app.tasks import cache_tasks

    memory = _FakeMemory({"authored": "human", "generalized_answer": "the human answer"})
    monkeypatch.setattr(cache_tasks, "get_memory_service", lambda ns: memory)
    monkeypatch.setattr(cache_tasks, "_is_suppressed", lambda q: False)

    def _boom(*a, **k):
        raise AssertionError("generalize() must not run for a human-authored entry")

    monkeypatch.setattr(cache_tasks, "get_context_adjuster_service", _boom)

    result = cache_tasks.generalize_and_store_task.run(
        "what is the refund window",
        "the model answer",
        "What is the refund window?",
        "acme",
        "acme__eng",
    )

    assert result["status"] == "human_authored"
    assert memory.stored == []


def test_celery_store_proceeds_for_an_ordinary_entry(monkeypatch):
    """The guard must be narrow: an entry with no provenance is still stored,
    and so is one a model wrote."""
    from app.tasks import cache_tasks

    memory = _FakeMemory({"generalized_answer": "an older model answer"})
    monkeypatch.setattr(cache_tasks, "get_memory_service", lambda ns: memory)
    monkeypatch.setattr(cache_tasks, "_is_suppressed", lambda q: False)

    class _Adjuster:
        async def generalize(self, answer):
            return f"generalized:{answer}"

    monkeypatch.setattr(cache_tasks, "get_context_adjuster_service", lambda **kw: _Adjuster())

    result = cache_tasks.generalize_and_store_task.run(
        "what is the refund window",
        "the model answer",
        "What is the refund window?",
        "acme",
        "acme__eng",
    )

    assert result["status"] == "stored"
    assert memory.stored[0][0][1] == "generalized:the model answer"


def test_in_process_fallback_store_skips_a_human_authored_entry(monkeypatch):
    """The DEJAQ_USE_CELERY=false / Celery-outage path carries the same guard —
    the race does not disappear when the queue does."""
    from app.routers import openai_compat

    memory = _FakeMemory({"authored": "human"})
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda ns: memory)

    def _boom(*a, **k):
        raise AssertionError("must not build services for a human-authored entry")

    monkeypatch.setattr(openai_compat, "_llm_config_for_workspace_slug", _boom)

    openai_compat._bg_generalize_and_store(
        "what is the refund window",
        "the model answer",
        "What is the refund window?",
        "acme",
        "acme__eng",
    )

    assert memory.stored == []


# ── Score eviction must not age out a human answer ────────────────────────────


class _FakeCollection:
    def __init__(self, rows):
        self.rows = rows
        self.deleted: list[str] = []

    def get(self, ids=None, where=None, include=None, limit=None, offset=None):
        if ids is not None:
            found = [i for i in ids if i in self.rows]
            return {"ids": found, "metadatas": [self.rows[i] for i in found]}
        # delete_entry cascades with where={"alias_of": id}. Honouring it is not
        # optional in a stub: a `get` that ignores the filter returns the whole
        # collection and the cascade deletes everything.
        if where and "alias_of" in where:
            found = [i for i, m in self.rows.items() if m.get("alias_of") == where["alias_of"]]
            return {"ids": found, "metadatas": [self.rows[i] for i in found]}
        return {"ids": list(self.rows), "metadatas": list(self.rows.values())}

    def delete(self, ids):
        for i in ids:
            self.deleted.append(i)
            self.rows.pop(i, None)

    def count(self):
        return len(self.rows)


def _memory_with(rows):
    from app.services.memory_chromaDB import MemoryService

    service = MemoryService.__new__(MemoryService)
    service._collection = _FakeCollection(rows)
    return service


def test_eviction_spares_a_human_authored_entry():
    """Nothing regenerates a human answer if it goes — the same argument that
    keeps the curated RAG collection out of this sweep. A thumbs-down still
    deletes it, so a bad edit stays undoable."""
    memory = _memory_with(
        {
            "human": {"score": -9.0, "authored": "human"},
            "model": {"score": -9.0},
        }
    )

    deleted = memory.evict_below_floor(-5.0)

    assert deleted == 1
    assert memory._collection.deleted == ["model"]


def test_eviction_returns_zero_when_only_human_entries_are_below_the_floor():
    memory = _memory_with({"human": {"score": -9.0, "authored": "human"}})

    assert memory.evict_below_floor(-5.0) == 0
    assert memory._collection.deleted == []


# ── overwrite_answer replaces the answer everywhere it is copied ──────────────


class _UpdatingCollection(_FakeCollection):
    def update(self, ids, metadatas):
        for entry_id, meta in zip(ids, metadatas):
            self.rows[entry_id] = meta


def _memory_with_updates(rows):
    from app.services.memory_chromaDB import MemoryService

    service = MemoryService.__new__(MemoryService)
    service._collection = _UpdatingCollection(rows)
    return service


def test_overwrite_answer_cascades_to_aliases():
    """An alias keeps a byte-copy of the parent's answer, so editing the root
    without rewriting them leaves every learned typo still serving the old text.
    delete_entry cascades for this reason; so must this."""
    memory = _memory_with_updates(
        {
            "root": {"generalized_answer": "wrong", "score": 3.0},
            "typo1": {"generalized_answer": "wrong", "alias_of": "root"},
            "typo2": {"generalized_answer": "wrong", "alias_of": "root"},
            "unrelated": {"generalized_answer": "something else"},
        }
    )

    written = memory.overwrite_answer("root", "right")

    assert written == "root"
    assert memory._collection.rows["typo1"]["generalized_answer"] == "right"
    assert memory._collection.rows["typo2"]["generalized_answer"] == "right"
    assert memory._collection.rows["typo1"]["authored"] == "human"
    assert memory._collection.rows["unrelated"]["generalized_answer"] == "something else"


def test_overwrite_answer_preserves_counters_and_attachment_gates():
    """Not store_interaction: an upsert would reset the counters to 0 and drop
    any image_*/file_* keys not re-supplied, un-gating the entry."""
    memory = _memory_with_updates(
        {
            "doc": {
                "generalized_answer": "wrong",
                "original_query": "the question",
                "score": 4.0,
                "hit_count": 11,
                "negative_count": 1,
                "file_sha": "abc123",
                "file_kind": "pdf",
            }
        }
    )

    memory.overwrite_answer("doc", "right")

    row = memory._collection.rows["doc"]
    assert row["generalized_answer"] == "right"
    assert row["score"] == 4.0
    assert row["hit_count"] == 11
    assert row["negative_count"] == 1
    assert row["file_sha"] == "abc123"
    assert row["file_kind"] == "pdf"
    assert row["original_query"] == "the question"


def test_overwrite_answer_redirects_an_alias_to_its_root():
    memory = _memory_with_updates(
        {
            "root": {"generalized_answer": "wrong", "score": 2.0},
            "typo": {"generalized_answer": "wrong", "alias_of": "root"},
        }
    )

    written = memory.overwrite_answer("typo", "right")

    assert written == "root"
    assert memory._collection.rows["root"]["generalized_answer"] == "right"
    assert memory._collection.rows["root"]["score"] == 2.0
    assert memory._collection.rows["typo"]["generalized_answer"] == "right"


def test_overwrite_answer_raises_for_a_missing_entry():
    memory = _memory_with_updates({})

    with pytest.raises(KeyError):
        memory.overwrite_answer("nope", "right")


# ── Request shape: a save is a like, and needs an interaction ─────────────────


def test_edited_answer_requires_a_positive_rating():
    from app.schemas.feedback import FeedbackRequest

    with pytest.raises(ValidationError):
        FeedbackRequest(interaction_id="int_1", rating="negative", edited_answer="text")


def test_edited_answer_requires_an_interaction_id():
    """The interaction record carries the namespace and the message hash the
    create-when-absent path verifies against; a bare response_id cannot."""
    from app.schemas.feedback import FeedbackRequest

    with pytest.raises(ValidationError):
        FeedbackRequest(response_id="acme__eng:doc1", rating="positive", edited_answer="text")


def test_edited_answer_accepted_with_a_positive_interaction_payload():
    from app.schemas.feedback import FeedbackRequest

    body = FeedbackRequest(
        interaction_id="int_1",
        rating="positive",
        edited_answer="the corrected answer",
        messages=[{"role": "user", "content": "Hello"}],
    )

    assert body.edited_answer == "the corrected answer"


def test_an_ordinary_thumbs_up_is_unchanged():
    """Every existing client sends no edited_answer at all; that must stay a
    valid, unremarkable request."""
    from app.schemas.feedback import FeedbackRequest

    body = FeedbackRequest(response_id="acme--default:doc1", rating="positive")

    assert body.edited_answer is None


class _RacingMemory:
    """The entry is ordinary when the task starts and human-authored by the time
    generalize() returns — the exact interleaving the guard's comment claims to
    handle, and the one a single up-front read cannot see."""

    def __init__(self):
        self.reads = 0
        self.stored: list[tuple] = []

    def get_entry_metadata(self, doc_id):
        self.reads += 1
        return {} if self.reads == 1 else {"authored": "human"}

    def store_interaction(self, *args, **kwargs):
        self.stored.append((args, kwargs))
        return "doc1"


def test_celery_store_loses_the_race_gracefully(monkeypatch):
    from app.tasks import cache_tasks

    memory = _RacingMemory()
    monkeypatch.setattr(cache_tasks, "get_memory_service", lambda ns: memory)
    monkeypatch.setattr(cache_tasks, "_is_suppressed", lambda q: False)

    class _Adjuster:
        async def generalize(self, answer):
            return "generalized"

    monkeypatch.setattr(cache_tasks, "get_context_adjuster_service", lambda **kw: _Adjuster())

    result = cache_tasks.generalize_and_store_task.run(
        "what is the refund window", "the model answer", "q", "acme", "acme__eng"
    )

    assert result["status"] == "human_authored"
    assert memory.stored == [], "an edit that landed during generalize() was overwritten"


def test_in_process_store_loses_the_race_gracefully(monkeypatch):
    from app.routers import openai_compat

    memory = _RacingMemory()
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda ns: memory)
    monkeypatch.setattr(
        openai_compat, "_llm_config_for_workspace_slug", lambda slug: None
    )

    class _Adjuster:
        async def generalize(self, answer):
            return "generalized"

    monkeypatch.setattr(
        openai_compat,
        "_services_for_model_profile",
        lambda profile, llm_config=None: openai_compat.ModelServices(
            normalizer=None, llm_router=None, adjuster=_Adjuster(), enricher=None, validator=None
        ),
    )

    openai_compat._bg_generalize_and_store(
        "what is the refund window", "the model answer", "q", "acme", "acme__eng"
    )

    assert memory.stored == []


def test_provenance_read_failure_does_not_stall_the_cache(monkeypatch):
    """The guard fails OPEN: a Chroma blip must not turn every background store
    into a silent no-op, which would stop the cache filling entirely."""
    from app.tasks import cache_tasks

    class _Broken:
        def get_entry_metadata(self, doc_id):
            raise RuntimeError("chroma down")

        def store_interaction(self, *args, **kwargs):
            return "doc1"

    assert cache_tasks._is_human_authored(_Broken(), "doc1") is False
