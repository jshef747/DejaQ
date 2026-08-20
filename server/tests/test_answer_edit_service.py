"""Edit & Save — a human-written answer replaces the model's, everywhere.

The feature's whole promise is that the edited text is the ONLY answer the
question can return afterwards, so most of what is worth testing here is not
"did the write happen" but "did the old answer survive somewhere it shouldn't".
"""

import asyncio
from dataclasses import dataclass

import pytest

pytestmark = pytest.mark.no_model


@dataclass
class FakeInteraction:
    interaction_id: str = "int_abc"
    workspace_id: int | None = 1
    workspace_slug: str = "acme"
    department: str = "eng"
    cache_namespace: str = "acme__eng"
    served_tier: str = "cache"
    response_id: str | None = "acme__eng:doc1"
    message_hash: str = ""


class FakeMemory:
    """Stands in for MemoryService, modelling the two things that matter here:
    an entry can be absent, and overwrite_answer redirects an alias to its root.
    """

    def __init__(self, entries: dict | None = None):
        self.entries = entries if entries is not None else {}
        self.stored: list[tuple] = []

    def overwrite_answer(self, entry_id: str, answer: str, *, authored: str = "human") -> str:
        meta = self.entries.get(entry_id)
        if meta is None:
            raise KeyError(entry_id)
        root_id = meta.get("alias_of") or entry_id
        target = self.entries.get(root_id, meta)
        target["generalized_answer"] = answer
        target["authored"] = authored
        return root_id

    def store_interaction(self, clean_query, answer, original_query, user_id, **kwargs):
        self.stored.append((clean_query, answer, original_query, user_id, kwargs))
        self.entries["new_doc"] = {"generalized_answer": answer, "authored": kwargs.get("authored")}
        return "new_doc"


def _run(coro):
    return asyncio.run(coro)


# ── The primary path: overwrite what is already there ─────────────────────────


def test_overwrites_an_existing_entry_in_place(monkeypatch):
    from app.services import answer_edit

    memory = FakeMemory({"doc1": {"generalized_answer": "wrong", "score": 4.0}})
    monkeypatch.setattr(answer_edit, "get_memory_service", lambda ns: memory)

    outcome = _run(
        answer_edit.apply_edited_answer(
            interaction=FakeInteraction(),
            response_id="acme__eng:doc1",
            edited_answer="right",
            messages=None,
        )
    )

    assert outcome.edit_status == "saved"
    assert outcome.response_id == "acme__eng:doc1"
    assert memory.entries["doc1"]["generalized_answer"] == "right"
    assert memory.entries["doc1"]["authored"] == "human"
    # No re-derivation: the id the client held already addresses the entry, so
    # nothing was created alongside it.
    assert memory.stored == []


def test_editing_through_an_alias_returns_the_root_id(monkeypatch):
    """An alias is a pointer for lookup but keeps its own copy of the answer.
    The write must land on the root, and the caller must be told which id that
    is, or the +1.0 and any later feedback address the wrong document."""
    from app.services import answer_edit

    memory = FakeMemory(
        {
            "root1": {"generalized_answer": "wrong"},
            "alias1": {"generalized_answer": "wrong", "alias_of": "root1"},
        }
    )
    monkeypatch.setattr(answer_edit, "get_memory_service", lambda ns: memory)

    outcome = _run(
        answer_edit.apply_edited_answer(
            interaction=FakeInteraction(),
            response_id="acme__eng:alias1",
            edited_answer="right",
            messages=None,
        )
    )

    assert outcome.edit_status == "saved"
    assert outcome.response_id == "acme__eng:root1"
    assert memory.entries["root1"]["generalized_answer"] == "right"


# ── The fallback: create the entry the pipeline never wrote ───────────────────


def test_creates_an_entry_when_none_exists(monkeypatch):
    from app.services import answer_edit, response_registry

    memory = FakeMemory({})  # nothing stored yet
    monkeypatch.setattr(answer_edit, "get_memory_service", lambda ns: memory)

    class _Svc:
        async def enrich(self, query, history):
            return query

        async def normalize(self, text):
            return text.lower()

    monkeypatch.setattr(answer_edit, "get_context_enricher_service", lambda **kw: _Svc())
    monkeypatch.setattr(answer_edit, "get_normalizer_service", lambda **kw: _Svc())

    messages = [{"role": "user", "content": "What Is The Refund Window"}]
    interaction = FakeInteraction(
        response_id=None,
        message_hash=response_registry.compute_messages_hash(messages),
    )

    outcome = _run(
        answer_edit.apply_edited_answer(
            interaction=interaction,
            response_id=None,
            edited_answer="30 days.",
            messages=messages,
        )
    )

    assert outcome.edit_status == "created"
    assert outcome.response_id == "acme__eng:new_doc"
    clean_query, answer, original_query, user_id, kwargs = memory.stored[0]
    assert clean_query == "what is the refund window"
    # Stored verbatim: no generalizer runs over a human answer.
    assert answer == "30 days."
    assert original_query == "What Is The Refund Window"
    assert kwargs["authored"] == "human"


def test_create_path_ignores_the_cache_filter(monkeypatch):
    """A two-word query is below cache_filter's minimum, but a person vouching
    for the answer outranks the heuristic — that is the one rule Edit & Save is
    allowed to override."""
    from app.services import answer_edit, response_registry

    memory = FakeMemory({})
    monkeypatch.setattr(answer_edit, "get_memory_service", lambda ns: memory)

    class _Svc:
        async def enrich(self, query, history):
            return query

        async def normalize(self, text):
            return text

    monkeypatch.setattr(answer_edit, "get_context_enricher_service", lambda **kw: _Svc())
    monkeypatch.setattr(answer_edit, "get_normalizer_service", lambda **kw: _Svc())

    messages = [{"role": "user", "content": "refund window"}]
    interaction = FakeInteraction(
        response_id=None, message_hash=response_registry.compute_messages_hash(messages)
    )

    outcome = _run(
        answer_edit.apply_edited_answer(
            interaction=interaction,
            response_id=None,
            edited_answer="30 days.",
            messages=messages,
        )
    )

    assert outcome.edit_status == "created"
    assert len(memory.stored) == 1


# ── The refusals ──────────────────────────────────────────────────────────────


def test_absent_entry_without_a_replay_is_not_cached(monkeypatch):
    """The attachment case. The client withholds `messages` for a turn that
    carried an image or a file, because the replay is blind to the bytes.
    Creating an entry from it would produce an ungated text entry holding an
    answer about a document nobody attached."""
    from app.services import answer_edit

    memory = FakeMemory({})
    monkeypatch.setattr(answer_edit, "get_memory_service", lambda ns: memory)

    outcome = _run(
        answer_edit.apply_edited_answer(
            interaction=FakeInteraction(),
            response_id="acme__eng:doc1",
            edited_answer="right",
            messages=None,
        )
    )

    assert outcome.edit_status == "not_cached"
    assert outcome.response_id is None
    assert memory.stored == []


def test_a_mismatched_replay_writes_nothing(monkeypatch):
    from app.services import answer_edit

    memory = FakeMemory({})
    monkeypatch.setattr(answer_edit, "get_memory_service", lambda ns: memory)

    outcome = _run(
        answer_edit.apply_edited_answer(
            interaction=FakeInteraction(response_id=None, message_hash="not-the-right-hash"),
            response_id=None,
            edited_answer="right",
            messages=[{"role": "user", "content": "hello"}],
        )
    )

    assert outcome.edit_status == "message_mismatch"
    assert memory.stored == []


@pytest.mark.parametrize("bad", ["", "   \n "])
def test_an_empty_answer_is_rejected(bad):
    from app.services import answer_edit

    with pytest.raises(ValueError):
        _run(
            answer_edit.apply_edited_answer(
                interaction=FakeInteraction(),
                response_id="acme__eng:doc1",
                edited_answer=bad,
                messages=None,
            )
        )


def test_an_oversized_answer_is_rejected():
    from app.services import answer_edit

    with pytest.raises(ValueError):
        answer_edit.validate_edited_answer("x" * (answer_edit.MAX_EDITED_ANSWER_BYTES + 1))


# ── The Like half: an edit scores the entry it wrote ──────────────────────────


def test_submit_feedback_scores_the_entry_the_edit_landed_on(monkeypatch):
    """The +1.0 must apply to the human text, and to the id the edit actually
    wrote — not the alias id the client happened to be holding."""
    from app.services import answer_edit, feedback_service

    scored: list[tuple[str, float]] = []

    class _Mem:
        def update_score(self, doc_id, delta):
            scored.append((doc_id, delta))
            return 1.0

    async def _fake_edit(**kwargs):
        return answer_edit.EditOutcome(edit_status="saved", response_id="acme__eng:root1")

    async def _log(*args, **kwargs):
        return None

    async def _validate_owner(*args, **kwargs):
        return FakeInteraction()

    monkeypatch.setattr(feedback_service, "apply_edited_answer", _fake_edit)
    monkeypatch.setattr(feedback_service, "get_memory_service", lambda ns: _Mem())
    monkeypatch.setattr(feedback_service.request_logger, "log_feedback", _log)
    monkeypatch.setattr(feedback_service.response_registry, "validate_owner", _validate_owner)

    result = _run(
        feedback_service.submit_feedback(
            response_id="acme__eng:alias1",
            interaction_id="int_abc",
            edited_answer="right",
            rating="positive",
            comment=None,
            workspace="acme",
            workspace_id=1,
            department="eng",
            validate_namespace=True,
            cache_namespace="acme__eng",
        )
    )

    assert result.edit_status == "saved"
    assert result.response_id == "acme__eng:root1"
    assert result.new_score == 1.0
    assert scored == [("root1", 1.0)]


def test_an_unlanded_edit_does_not_score_a_nonexistent_entry(monkeypatch):
    """"not_cached" leaves the response_id naming an entry that does not exist.
    Scoring it would 404 the whole request over a like the user did express."""
    from app.services import answer_edit, feedback_service

    class _Mem:
        def update_score(self, doc_id, delta):
            raise AssertionError("must not score an entry that was never written")

    async def _fake_edit(**kwargs):
        return answer_edit.EditOutcome(edit_status="not_cached")

    async def _log(*args, **kwargs):
        return None

    async def _validate_owner(*args, **kwargs):
        return FakeInteraction()

    monkeypatch.setattr(feedback_service, "apply_edited_answer", _fake_edit)
    monkeypatch.setattr(feedback_service, "get_memory_service", lambda ns: _Mem())
    monkeypatch.setattr(feedback_service.request_logger, "log_feedback", _log)
    monkeypatch.setattr(feedback_service.response_registry, "validate_owner", _validate_owner)

    result = _run(
        feedback_service.submit_feedback(
            response_id="acme__eng:doc1",
            interaction_id="int_abc",
            edited_answer="right",
            rating="positive",
            comment=None,
            workspace="acme",
            workspace_id=1,
            department="eng",
            validate_namespace=True,
            cache_namespace="acme__eng",
        )
    )

    assert result.status == "ok"
    assert result.edit_status == "not_cached"
    assert result.new_score is None


def test_the_feedback_log_records_that_it_was_an_edit(monkeypatch):
    from app.services import answer_edit, feedback_service

    logged: list[dict] = []

    class _Mem:
        def update_score(self, doc_id, delta):
            return 1.0

    async def _fake_edit(**kwargs):
        return answer_edit.EditOutcome(edit_status="saved", response_id="acme__eng:doc1")

    async def _log(*args, **kwargs):
        logged.append(kwargs)

    async def _validate_owner(*args, **kwargs):
        return FakeInteraction()

    monkeypatch.setattr(feedback_service, "apply_edited_answer", _fake_edit)
    monkeypatch.setattr(feedback_service, "get_memory_service", lambda ns: _Mem())
    monkeypatch.setattr(feedback_service.request_logger, "log_feedback", _log)
    monkeypatch.setattr(feedback_service.response_registry, "validate_owner", _validate_owner)

    _run(
        feedback_service.submit_feedback(
            response_id="acme__eng:doc1",
            interaction_id="int_abc",
            edited_answer="right",
            rating="positive",
            comment=None,
            workspace="acme",
            workspace_id=1,
            department="eng",
            validate_namespace=True,
            cache_namespace="acme__eng",
        )
    )

    assert logged[0]["edited"] is True


def test_service_rejects_an_edit_without_a_resolved_interaction(monkeypatch):
    """The admin surface reaches submit_feedback with its own schema, which has
    no edited_answer rules — so the service re-checks rather than trusting the
    data-plane validator to have run."""
    from app.services import feedback_service

    async def _log(*args, **kwargs):
        return None

    monkeypatch.setattr(feedback_service.request_logger, "log_feedback", _log)

    with pytest.raises(ValueError):
        _run(
            feedback_service.submit_feedback(
                response_id="acme__eng:doc1",
                edited_answer="right",
                rating="positive",
                comment=None,
                workspace="acme",
                department="eng",
                validate_namespace=True,
            )
        )


def test_an_edit_cannot_write_into_another_workspaces_namespace(monkeypatch):
    """A caller holding workspace A's key must not be able to overwrite
    workspace B's cache by naming B's response_id alongside their own valid
    interaction_id. The namespace has to be checked BEFORE the write, not by
    _apply_cache_feedback afterwards - by then the answer is already replaced.
    """
    from app.services import feedback_service

    written: list[str] = []

    class _Mem:
        def __init__(self, namespace):
            self.namespace = namespace

        def overwrite_answer(self, doc_id, answer, *, authored="human"):
            written.append(f"{self.namespace}:{doc_id}")
            return doc_id

        def update_score(self, doc_id, delta):
            return 1.0

    async def _log(*args, **kwargs):
        return None

    async def _validate_owner(*args, **kwargs):
        return FakeInteraction()

    monkeypatch.setattr(feedback_service, "get_memory_service", _Mem)
    monkeypatch.setattr("app.services.answer_edit.get_memory_service", _Mem)
    monkeypatch.setattr(feedback_service.request_logger, "log_feedback", _log)
    monkeypatch.setattr(feedback_service.response_registry, "validate_owner", _validate_owner)

    with pytest.raises(feedback_service.FeedbackNamespaceMismatch):
        _run(
            feedback_service.submit_feedback(
                response_id="victim__default:abc123",
                interaction_id="int_abc",
                edited_answer="poisoned",
                rating="positive",
                comment=None,
                workspace="acme",
                workspace_id=1,
                department="eng",
                validate_namespace=True,
                cache_namespace="acme__eng",
            )
        )

    assert written == [], f"wrote into a foreign namespace before validating: {written}"
