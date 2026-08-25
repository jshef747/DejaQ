"""Trigger math for the semantic tie-breaker (services/draft_selector.py).

The selector is pure, so every condition is exercised here without a running
stack. The eligibility rules that depend on the REQUEST rather than on the pair
(attachments, human-authored entries, the tier a candidate came from) are
enforced at the call site and covered by test_drafts_hit_pipeline.py.
"""

import pytest

from app.services.draft_selector import answers_diverge, select_draft_pair
from app.services.memory_chromaDB import CacheLookupResult

MAX_DISTANCE = 0.05
MAX_DELTA = 0.02
MAX_SCORE_GAP = 1.0


def candidate(
    entry_id: str,
    distance: float,
    answer: str,
    *,
    score: float = 0.0,
    alias_of: str | None = None,
    requires_validation: bool = False,
    authored: str | None = None,
) -> CacheLookupResult:
    return CacheLookupResult(
        hit=True,
        generalized_answer=answer,
        entry_id=entry_id,
        distance=distance,
        matched_query=f"query for {entry_id}",
        score=score,
        alias_of=alias_of,
        requires_validation=requires_validation,
        authored=authored,
    )


def select(pool):
    return select_draft_pair(
        pool,
        max_distance=MAX_DISTANCE,
        max_delta=MAX_DELTA,
        max_score_gap=MAX_SCORE_GAP,
    )


ANSWER_A = "The nearest station is Kings Cross, about a nine minute walk north."
ANSWER_B = "Kings Cross is closest - roughly ten minutes on foot, heading north."


def test_fires_when_two_candidates_are_indistinguishable():
    pair = select([
        candidate("a", 0.0200, ANSWER_A),
        candidate("b", 0.0231, ANSWER_B),
    ])
    assert pair is not None
    assert pair.primary.entry_id == "a"
    assert pair.alternate.entry_id == "b"
    assert pair.distance_delta == pytest.approx(0.0031)


def test_refuses_a_single_candidate():
    assert select([candidate("a", 0.02, ANSWER_A)]) is None


def test_refuses_an_empty_pool():
    assert select([]) is None


def test_refuses_when_the_distances_are_not_close_enough():
    # 0.04 apart against a 0.02 tolerance: the embedding CAN separate these,
    # so there is nothing to break a tie over.
    assert select([
        candidate("a", 0.0200, ANSWER_A),
        candidate("b", 0.0600, ANSWER_B),
    ]) is None


def test_refuses_when_the_runner_up_is_outside_the_quality_window():
    # Tied with each other, but both only just - the second sits past the
    # window, and a tie between two poor matches is still two poor matches.
    assert select([
        candidate("a", 0.0450, ANSWER_A),
        candidate("b", 0.0600, ANSWER_B),
    ]) is None


def test_refuses_when_the_primary_is_outside_the_quality_window():
    assert select([
        candidate("a", 0.0550, ANSWER_A),
        candidate("b", 0.0600, ANSWER_B),
    ]) is None


def test_a_distance_exactly_on_the_window_is_still_offered():
    pair = select([
        candidate("a", MAX_DISTANCE, ANSWER_A),
        candidate("b", MAX_DISTANCE, ANSWER_B),
    ])
    assert pair is not None


def test_a_delta_exactly_on_the_tolerance_is_still_offered():
    pair = select([
        candidate("a", 0.0100, ANSWER_A),
        candidate("b", 0.0300, ANSWER_B),
    ])
    assert pair is not None
    assert pair.distance_delta == pytest.approx(MAX_DELTA)


def test_a_settled_tie_is_never_offered_again():
    """The convergence rule, and the single most important case here.

    One pick applies the ordinary +1.0, which puts the winner exactly
    MAX_SCORE_GAP ahead. From then on the pair is settled and the chooser must
    never reappear - otherwise a distance-based trigger asks every user the
    same already-answered question forever.
    """
    assert select([
        candidate("a", 0.0200, ANSWER_A, score=1.0),
        candidate("b", 0.0231, ANSWER_B, score=0.0),
    ]) is None


def test_a_tie_is_still_offered_while_the_gap_is_under_the_threshold():
    pair = select([
        candidate("a", 0.0200, ANSWER_A, score=0.5),
        candidate("b", 0.0231, ANSWER_B, score=0.0),
    ])
    assert pair is not None


def test_the_score_gap_is_absolute_not_signed():
    # The runner-up on distance may well be AHEAD on score; that is still a
    # settled pair, not an open one.
    assert select([
        candidate("a", 0.0200, ANSWER_A, score=0.0),
        candidate("b", 0.0231, ANSWER_B, score=2.0),
    ]) is None


def test_refuses_an_alias_and_its_root():
    """An alias holds a byte-copy of its root's answer (store_alias), so this
    pair is the likeliest distance tie in any corpus and would render the same
    text twice."""
    assert select([
        candidate("root", 0.0200, ANSWER_A),
        candidate("alias", 0.0205, ANSWER_A, alias_of="root"),
    ]) is None


def test_refuses_two_aliases_of_one_root():
    assert select([
        candidate("alias-1", 0.0200, ANSWER_A, alias_of="root"),
        candidate("alias-2", 0.0205, ANSWER_A, alias_of="root"),
    ]) is None


def test_refuses_two_entries_holding_identical_text():
    assert select([
        candidate("a", 0.0200, ANSWER_A),
        candidate("b", 0.0205, ANSWER_A),
    ]) is None


def test_refuses_text_differing_only_in_whitespace():
    assert select([
        candidate("a", 0.0200, ANSWER_A),
        candidate("b", 0.0205, "  ".join(ANSWER_A.split()) + "\n"),
    ]) is None


def test_a_one_word_factual_difference_is_offered():
    """Deliberately NOT refused, and this is the most valuable case of all.

    Two cached answers to one question that disagree on a single fact ("nine"
    vs "ten minutes") are exactly what a person should be asked to arbitrate -
    the divergence guard exists to catch two copies of the SAME answer, not to
    suppress a real disagreement because it is narrow. Measured overlap for
    this pair is 0.846, comfortably under the ceiling.
    """
    pair = select([
        candidate("a", 0.0200, ANSWER_A),
        candidate("b", 0.0205, ANSWER_A.replace("nine", "ten")),
    ])
    assert pair is not None


def test_refuses_a_reformatted_copy_of_one_answer():
    # Same words, different wrapping and punctuation: nothing to choose between.
    assert select([
        candidate("a", 0.0200, ANSWER_A),
        candidate("b", 0.0205, ANSWER_A.replace(", ", " -- ").replace(".", " !")),
    ]) is None


def test_refuses_when_an_answer_is_empty():
    assert select([
        candidate("a", 0.0200, ""),
        candidate("b", 0.0205, ANSWER_B),
    ]) is None


def test_refuses_when_a_distance_is_missing():
    missing = CacheLookupResult(hit=True, generalized_answer=ANSWER_B, entry_id="b", distance=None)
    assert select([candidate("a", 0.02, ANSWER_A), missing]) is None


def test_the_alternate_is_the_closest_candidate_not_the_next_listed():
    """List order is by feedback SCORE within a tier, not by distance (see
    MemoryService._lookup_candidates), so the next element is merely the next
    most popular entry. Reading the alternate off the order would miss this
    genuine tie entirely.
    """
    pair = select([
        candidate("a", 0.0200, ANSWER_A, score=0.4),
        candidate("popular-but-far", 0.0480, ANSWER_B, score=0.3),
        candidate("c", 0.0205, "A third, quite different answer about the walk.", score=0.0),
    ])

    assert pair is not None
    assert pair.primary.entry_id == "a"
    assert pair.alternate.entry_id == "c"
    assert pair.distance_delta == pytest.approx(0.0005)


def test_the_primary_is_always_the_candidate_the_caller_served():
    """Even when a later candidate is closer. The router has already keyed the
    whole response off passed[0]; re-ranking here would serve one answer and
    label a different one as draft A."""
    pair = select([
        candidate("served", 0.0210, ANSWER_A),
        candidate("closer", 0.0205, ANSWER_B),
    ])

    assert pair is not None
    assert pair.primary.entry_id == "served"
    assert pair.alternate.entry_id == "closer"


def test_a_runner_up_outside_the_window_is_skipped_not_fatal():
    """One candidate being too far must not hide a closer one behind it."""
    pair = select([
        candidate("a", 0.0200, ANSWER_A),
        candidate("far", 0.5000, "An answer about something else entirely."),
        candidate("c", 0.0205, ANSWER_B),
    ])

    assert pair is not None
    assert pair.alternate.entry_id == "c"


class TestAnswersDiverge:
    def test_identical_text_is_not_a_choice(self):
        assert answers_diverge(ANSWER_A, ANSWER_A) is None

    def test_genuinely_different_text_returns_its_overlap(self):
        ratio = answers_diverge(ANSWER_A, ANSWER_B)
        assert ratio is not None
        assert 0.0 <= ratio < 0.9

    def test_empty_text_is_not_a_choice(self):
        assert answers_diverge("", ANSWER_A) is None
        assert answers_diverge(ANSWER_A, "   ") is None

    def test_punctuation_only_difference_is_not_a_choice(self):
        assert answers_diverge("Yes, absolutely.", "Yes - absolutely!") is None

    def test_the_same_temperature_written_two_ways_is_not_a_choice(self):
        """The tungsten pair from the PR 70 review, and the ONLY natural tie it
        could produce.

        The trigger population comes from concurrent misses of one question, so
        the two entries are two phrasings of one answer far more often than a
        real disagreement. Untokenised this pair scored 0.70 - under the 0.9
        ceiling - and the user was asked to choose between the same fact
        written twice.
        """
        assert answers_diverge(
            "The melting point of tungsten is 3422°C.",
            "The melting point of tungsten is 3422 degrees Celsius.",
        ) is None

    def test_percent_and_currency_spellings_are_not_a_choice(self):
        assert answers_diverge("Interest is 5%.", "Interest is 5 percent.") is None
        assert answers_diverge("It costs $100.", "It costs 100 dollars.") is None

    def test_normalising_units_does_not_swallow_a_real_disagreement(self):
        """The pair the 0.9 ceiling exists to protect, re-asserted against the
        normalisation: "nine" vs "ten" is a difference in what the answer SAYS,
        not in how a unit is spelled, so it must still be offered - at the same
        0.846 the ceiling was set against.
        """
        ratio = answers_diverge(ANSWER_A, ANSWER_A.replace("nine", "ten"))
        assert ratio is not None
        assert round(ratio, 3) == 0.846

    def test_a_real_temperature_disagreement_is_still_a_choice(self):
        """Normalising the UNIT must not normalise away the VALUE."""
        assert answers_diverge(
            "The melting point of tungsten is 3422°C.",
            "The melting point of tungsten is 3400 degrees Celsius.",
        ) is not None
