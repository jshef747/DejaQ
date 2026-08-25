"""Serving alternative drafts through the real pipeline.

The trigger arithmetic lives in test_draft_selector.py. What can only be tested
here is everything the ROUTER decides: which candidates are eligible at all,
that the served answer and the response body stay exactly what they were when
no tie fires, and that the drafts ride the wire where a client can find them.

Distances sit inside CACHE_DRAFTS_MAX_DISTANCE, which is capped at
CACHE_TRUST_DISTANCE (0.15). Both drafts are validated - the served answer like
any other hit, the alternate by its own call on the tie path - which is what
lets the window reach the trusted ceiling rather than stopping at
VALIDATOR_SKIP_DISTANCE. Every request here is single-turn, because drafts never
fire on a follow-up turn.
"""
import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import openai_compat
from app.services.memory_chromaDB import CacheLookupResult
from tests.test_openai_compat_smoke import (
    _AUTH,
    MarkerAdjuster,
    StubEnricher,
    StubNormalizer,
)

pytestmark = pytest.mark.no_model

ANSWER_A = "The refund window is 30 days from delivery."
ANSWER_B = "You have a month after the parcel arrives to ask for your money back."


@pytest.fixture(autouse=True)
def _stub_api_key(monkeypatch):
    """Autouse fixtures don't cross modules - redeclare it here."""
    from app.middleware.api_key import _KEY_CACHE

    monkeypatch.setattr(
        _KEY_CACHE, "resolve", lambda token: ("demo", 1) if token == "test-key" else None
    )


def _candidate(entry_id, distance, answer, **kwargs):
    return CacheLookupResult(
        hit=True,
        generalized_answer=answer,
        entry_id=entry_id,
        distance=distance,
        matched_query="query for " + entry_id,
        **kwargs,
    )


class _PoolMemory:
    """A memory whose lookup returns whichever candidates the test supplies."""

    def __init__(self, *candidates):
        self._candidates = list(candidates)

    def lookup_cache_pool(self, clean_query: str):
        return self._candidates, 0.10, "nearest prompt"

    def lookup_cache(self, clean_query: str):
        return self._candidates[0] if self._candidates else CacheLookupResult(hit=False)

    def increment_hit_count(self, doc_id: str):
        return None


class _AcceptingValidator:
    async def validate(self, new_query, cached_query, cached_answer, **kwargs):
        return True, "VALID"


def _patch_pipeline(monkeypatch, memory, drafts_enabled=True, validator=None):
    async def _noop_log(*a, **k):
        return None

    validator = validator or _AcceptingValidator()
    monkeypatch.setattr(
        openai_compat,
        "_services_for_model_profile",
        lambda profile, llm_config=None: openai_compat.ModelServices(
            normalizer=StubNormalizer(),
            llm_router=None,
            adjuster=MarkerAdjuster(),
            enricher=StubEnricher(),
            validator=validator,
        ),
    )
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: memory)
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)
    monkeypatch.setattr(openai_compat, "USE_CELERY", False)
    monkeypatch.setattr(
        openai_compat,
        "_read_effective_llm_config",
        lambda slug, wid: openai_compat.EffectiveLlmConfig(
            external_model="gemini-2.5-flash",
            routing_threshold=0.3,
            drafts_enabled=drafts_enabled,
        ),
    )


def _ask(stream=False, query="how long is the refund window?"):
    return TestClient(app, headers=_AUTH).post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": query}], "stream": stream},
    )


def _tied_pool(**alternate_kwargs):
    return _PoolMemory(
        _candidate("doc-a", 0.0200, ANSWER_A),
        _candidate("doc-b", 0.0231, ANSWER_B, **alternate_kwargs),
    )


# --- the feature working ----------------------------------------------------

def test_a_tie_returns_both_drafts(monkeypatch):
    _patch_pipeline(monkeypatch, _tied_pool())

    response = _ask()

    assert response.status_code == 200
    body = response.json()
    drafts = body["dejaq_drafts"]
    assert [d["label"] for d in drafts] == ["A", "B"]
    assert drafts[0]["content"] == ANSWER_A
    assert drafts[1]["content"] == ANSWER_B
    assert response.headers["x-dejaq-drafts"] == "2"


def test_draft_a_is_the_answer_that_was_actually_served(monkeypatch):
    """A client that ignores the drafts entirely must still read draft A."""
    _patch_pipeline(monkeypatch, _tied_pool())

    body = _ask().json()

    assert body["choices"][0]["message"]["content"] == body["dejaq_drafts"][0]["content"]


def test_the_response_id_names_the_served_draft(monkeypatch):
    _patch_pipeline(monkeypatch, _tied_pool())

    response = _ask()

    served = response.headers["x-dejaq-response-id"]
    assert response.json()["dejaq_drafts"][0]["response_id"] == served
    assert response.json()["dejaq_drafts"][1]["response_id"] != served


def test_both_drafts_are_served_verbatim(monkeypatch):
    """The adjuster would paraphrase the served answer to match the asker's
    tone, so the text a user picks would not be the text that gets the point."""
    _patch_pipeline(monkeypatch, _tied_pool())

    drafts = _ask().json()["dejaq_drafts"]

    assert drafts[0]["content"] == ANSWER_A
    assert "ADJUSTED" not in drafts[0]["content"]


def test_the_drafts_ride_the_terminal_streaming_chunk(monkeypatch):
    _patch_pipeline(monkeypatch, _tied_pool())

    response = _ask(stream=True)

    chunks = [
        json.loads(line[len("data: "):])
        for line in response.text.splitlines()
        if line.startswith("data: ") and line != "data: [DONE]"
    ]
    with_drafts = [c for c in chunks if "dejaq_drafts" in c]
    assert len(with_drafts) == 1, "drafts must appear exactly once, on the last chunk"
    assert with_drafts[0] is chunks[-1]
    # Still a legal chunk, so an SDK that ignores the extra key is unaffected.
    assert with_drafts[0]["object"] == "chat.completion.chunk"
    assert with_drafts[0]["choices"][0]["finish_reason"] == "stop"


# --- the feature correctly staying out of the way ---------------------------

def test_no_tie_leaves_the_body_exactly_as_it_was(monkeypatch):
    """The regression that matters most: an ordinary hit must not grow a key."""
    _patch_pipeline(
        monkeypatch,
        _PoolMemory(
            _candidate("doc-a", 0.0200, ANSWER_A),
            _candidate("doc-b", 0.0480, ANSWER_B),  # too far apart to be a tie
        ),
    )

    response = _ask()

    assert "dejaq_drafts" not in response.json()
    assert "x-dejaq-drafts" not in response.headers


def test_no_tie_leaves_the_streaming_chunks_exactly_as_they_were(monkeypatch):
    _patch_pipeline(monkeypatch, _PoolMemory(_candidate("doc-a", 0.0200, ANSWER_A)))

    response = _ask(stream=True)

    assert "dejaq_drafts" not in response.text


def test_drafts_are_off_unless_the_workspace_enables_them(monkeypatch):
    _patch_pipeline(monkeypatch, _tied_pool(), drafts_enabled=False)

    response = _ask()

    assert "dejaq_drafts" not in response.json()
    assert "x-dejaq-drafts" not in response.headers
    assert response.json()["choices"][0]["message"]["content"] == ANSWER_A


def test_drafts_never_fire_on_a_follow_up_turn(monkeypatch):
    """A multi-turn request is a conversation, and serving drafts means serving
    the stored answers verbatim - which would silently discard the context
    adjuster on exactly the turns that exist to change how an answer reads.

    The ADJUSTED marker is the proof: the adjuster still runs here, and would
    not if the tie-breaker had taken over the answer.
    """
    _patch_pipeline(monkeypatch, _tied_pool())

    response = TestClient(app, headers=_AUTH).post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o",
            "messages": [
                {"role": "user", "content": "how long is the refund window?"},
                {"role": "assistant", "content": ANSWER_A},
                {"role": "user", "content": "can you put that in bullet points?"},
            ],
            "stream": False,
        },
    )

    assert "dejaq_drafts" not in response.json()
    assert response.json()["choices"][0]["message"]["content"].startswith("ADJUSTED: ")


def test_a_human_authored_alternate_is_never_put_to_a_vote(monkeypatch):
    """A person vouched for that text through Edit & Save. Asking the next user
    to weigh it against a model's answer is what that feature exists to stop."""
    _patch_pipeline(monkeypatch, _tied_pool(authored="human"))

    assert "dejaq_drafts" not in _ask().json()


def test_a_human_authored_primary_is_never_put_to_a_vote(monkeypatch):
    _patch_pipeline(
        monkeypatch,
        _PoolMemory(
            _candidate("doc-a", 0.0200, ANSWER_A, authored="human"),
            _candidate("doc-b", 0.0231, ANSWER_B),
        ),
    )

    assert "dejaq_drafts" not in _ask().json()


def test_a_band_tier_alternate_is_never_offered(monkeypatch):
    """A band candidate is only servable once the validator accepts it, and
    drafts are validator-free - so it must not be offered as one."""
    _patch_pipeline(monkeypatch, _tied_pool(requires_validation=True))

    assert "dejaq_drafts" not in _ask().json()


def test_a_band_tier_primary_is_never_offered(monkeypatch):
    _patch_pipeline(
        monkeypatch,
        _PoolMemory(
            _candidate("doc-a", 0.1800, ANSWER_A, requires_validation=True),
            _candidate("doc-b", 0.1831, ANSWER_B, requires_validation=True),
        ),
    )

    assert "dejaq_drafts" not in _ask().json()


def test_a_settled_tie_is_not_offered_again(monkeypatch):
    """One pick puts the winner +1.0 ahead, which ends the tie for everyone."""
    _patch_pipeline(
        monkeypatch,
        _PoolMemory(
            _candidate("doc-a", 0.0200, ANSWER_A, score=1.0),
            _candidate("doc-b", 0.0231, ANSWER_B, score=0.0),
        ),
    )

    assert "dejaq_drafts" not in _ask().json()


# --- The alternate is validated on its own merit ----------------------------
#
# The served answer has always been validated - either by the validator or by
# sitting inside VALIDATOR_SKIP_DISTANCE, where the embedding is the guarantee.
# Until this ran, the alternate's only qualification was sitting near the
# primary, and that gap is why the configured window used to stop at
# VALIDATOR_SKIP_DISTANCE instead of the trusted ceiling.

class _RejectingValidator:
    """Accepts the served answer, refuses the alternate.

    Keyed on the answer text, because both calls arrive on the same turn and
    the point is that they are judged separately.
    """

    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    async def validate(self, new_query, cached_query, cached_answer, **kwargs):
        self.calls.append((cached_query, cached_answer))
        return (cached_answer != ANSWER_B), "VALID" if cached_answer != ANSWER_B else "INVALID"


class _ExplodingValidator:
    """Accepts the served answer, then throws on the alternate."""

    async def validate(self, new_query, cached_query, cached_answer, **kwargs):
        if cached_answer == ANSWER_B:
            raise RuntimeError("validator backend fell over")
        return True, "VALID"


def test_a_rejected_alternate_degrades_to_the_ordinary_single_answer(monkeypatch):
    """Not an error and not a miss.

    The primary is still a validated hit, so the turn must look exactly like a
    turn where no tie fired: the served answer, no drafts array, no header. A
    client has nothing new to handle.
    """
    validator = _RejectingValidator()
    _patch_pipeline(monkeypatch, _tied_pool(), validator=validator)

    response = _ask()
    body = response.json()

    assert response.status_code == 200
    assert "dejaq_drafts" not in body
    assert "x-dejaq-drafts" not in response.headers
    # Still a cache hit, still the served answer - just alone.
    assert response.headers["x-dejaq-tier"] == "cache"
    assert ANSWER_A in body["choices"][0]["message"]["content"]


def test_the_alternate_is_judged_on_its_own_question_and_answer(monkeypatch):
    """Not the primary's. Sitting near the primary is not a qualification -
    the alternate is a different entry matched by a different stored query."""
    validator = _RejectingValidator()
    _patch_pipeline(monkeypatch, _tied_pool(), validator=validator)

    _ask()

    assert ("query for doc-b", ANSWER_B) in validator.calls


def test_a_validator_that_throws_on_the_alternate_still_serves_the_answer(monkeypatch):
    """Fail-safe here means 'no second opinion', not 'no answer'."""
    _patch_pipeline(monkeypatch, _tied_pool(), validator=_ExplodingValidator())

    response = _ask()
    body = response.json()

    assert response.status_code == 200
    assert "dejaq_drafts" not in body
    assert response.headers["x-dejaq-tier"] == "cache"
    assert ANSWER_A in body["choices"][0]["message"]["content"]


def test_an_accepted_alternate_is_still_offered(monkeypatch):
    """The control: the same pool, with a validator that accepts both."""
    _patch_pipeline(monkeypatch, _tied_pool())

    response = _ask()

    assert response.headers["x-dejaq-drafts"] == "2"
    assert len(response.json()["dejaq_drafts"]) == 2


def test_a_rejected_alternate_leaves_the_stream_exactly_as_a_normal_hit(monkeypatch):
    _patch_pipeline(monkeypatch, _tied_pool(), validator=_RejectingValidator())

    response = _ask(stream=True)

    assert "dejaq_drafts" not in response.text
