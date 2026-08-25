"""The semantic tie-breaker: when two cache entries are indistinguishable, offer both.

`MemoryService._lookup_candidates` ranks every candidate and the router serves the
first one that clears the attachment gates. That is the right default, but it hides
a real state: two entries at near-identical cosine distance mean the embedding
*cannot separate them*, and picking the one that happened to be closer by a few
thousandths is a coin flip nobody is told about.

This module decides whether a pair is that case. It is pure - no I/O, no model
calls, no Chroma round-trip - so the whole trigger can be exercised in unit tests
without a running stack. Eligibility rules that depend on the REQUEST rather than
on the pair (attachments, human-authored entries, the tier a candidate came from)
live at the call site in routers/openai_compat.py, not here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.memory_chromaDB import CacheLookupResult

# Two answers whose word sets overlap this much are the SAME answer wearing
# different punctuation or wrapping, and presenting them as a choice is a bogus
# question - the user would be picking between two copies.
#
# Set high on purpose. This guard exists to catch duplicates, NOT to suppress a
# narrow disagreement: two cached answers that differ by one fact ("a nine
# minute walk" vs "a ten minute walk", measured 0.846) are the single most
# valuable thing this feature can surface, and a tighter ceiling would throw
# exactly those away. The exact-match and alias checks above catch the common
# duplicate cases; this only catches the ragged ones they miss.
_MAX_ANSWER_JACCARD = 0.9

_WORD_RE = re.compile(r"[a-z0-9]+")

# Unit and currency SPELLINGS, folded to one form before the overlap is
# measured. The comparison is a word-overlap ratio, so "3422°C" and "3422
# degrees Celsius" tokenise to different word sets and score 0.70 - two
# writings of one fact, offered to the user as a real choice.
#
# That is not an edge case here, it is the common one. The trigger population
# is created by CONCURRENT misses (a sequential near-variant hits the entry
# that already exists and is never stored), so the two entries in a natural
# tie are two answers to the SAME question - which means two phrasings of one
# answer far more often than a real disagreement.
#
# Normalising rather than lowering _MAX_ANSWER_JACCARD is deliberate: the
# ceiling stays at 0.9 so a narrow factual disagreement ("a nine minute walk"
# vs "a ten minute walk", measured 0.846) is still offered, which is the case
# this feature exists for. Only the spelling of a unit is cancelled, never a
# difference in what the answer says.
#
# Substituted into the lowercased text before tokenising, longest key first so
# "°c" is consumed before the bare "°". Each replacement is padded with spaces
# because a symbol sits flush against its number ("3422°c", "50%", "$100").
_SYMBOL_SPELLINGS = {
    "℃": " degrees celsius ",
    "℉": " degrees fahrenheit ",
    "°c": " degrees celsius ",
    "°f": " degrees fahrenheit ",
    "°": " degrees ",
    "%": " percent ",
    "$": " dollars ",
    "€": " euros ",
    "£": " pounds ",
    "¥": " yen ",
    "₪": " shekels ",
}

# Written-out spellings of the same units, folded onto one token each. Covers
# the singular/plural pair and the usual abbreviations; anything not listed is
# left alone, which is the safe direction (an unfolded token can only make two
# answers look MORE different, never less).
_TOKEN_ALIASES = {
    "degree": "degrees",
    "deg": "degrees",
    "degs": "degrees",
    "centigrade": "celsius",
    "percentage": "percent",
    "percents": "percent",
    "pct": "percent",
    "dollar": "dollars",
    "usd": "dollars",
    "euro": "euros",
    "eur": "euros",
    "pound": "pounds",
    "gbp": "pounds",
    "jpy": "yen",
    "shekel": "shekels",
    "ils": "shekels",
    "nis": "shekels",
}


@dataclass(frozen=True)
class DraftPair:
    """Two candidates the embedding could not tell apart.

    `primary` is what gets served and streamed exactly as a single hit would be,
    and it is fixed by the caller - it is whichever candidate the attachment
    gates accepted first, and the whole pipeline downstream has already keyed
    off it. `alternate` is the closest OTHER candidate, chosen here.
    """

    primary: CacheLookupResult
    alternate: CacheLookupResult
    distance_delta: float


def _tokens(text: str) -> set[str]:
    lowered = text.lower()
    for symbol, spelling in _SYMBOL_SPELLINGS.items():
        if symbol in lowered:
            lowered = lowered.replace(symbol, spelling)
    return {_TOKEN_ALIASES.get(word, word) for word in _WORD_RE.findall(lowered)}


def _normalized(text: str) -> str:
    return " ".join(text.split())


def _root_id(candidate: CacheLookupResult) -> str:
    """The entry a candidate's ANSWER actually lives on.

    An alias entry holds a byte-copy of its root's answer (see
    MemoryService.store_alias), so an alias and its root are the single most
    likely distance tie in any corpus - and offering them as two drafts would
    render the identical text twice.
    """
    return candidate.alias_of or candidate.entry_id or ""


def answers_diverge(first: str, second: str) -> float | None:
    """Word-overlap ratio of two answers, or None when they are the same answer.

    None means "do not offer these as a choice". A ratio is returned for a pair
    that differs enough to be worth a question, so the caller can log it.
    """
    left, right = _normalized(first), _normalized(second)
    if not left or not right or left == right:
        return None
    left_tokens, right_tokens = _tokens(left), _tokens(right)
    if not left_tokens or not right_tokens:
        return None
    union = left_tokens | right_tokens
    jaccard = len(left_tokens & right_tokens) / len(union)
    return None if jaccard >= _MAX_ANSWER_JACCARD else jaccard


def select_draft_pair(
    passed: list[CacheLookupResult],
    *,
    max_distance: float,
    max_delta: float,
    max_score_gap: float,
) -> DraftPair | None:
    """The top two gate-passing candidates, when they are genuinely tied.

    All four conditions must hold:

    1. Baseline quality - BOTH distances at or below `max_distance`. A tie
       between two mediocre matches is still two mediocre matches.
    2. Semantic proximity - the distances differ by no more than `max_delta`.
       This is the tie itself.
    3. Nobody has won yet - the entries' feedback scores differ by less than
       `max_score_gap`. This is what makes the feature converge: one pick
       applies +1.0, the gap reaches exactly max_score_gap (1.0 as shipped),
       and the pair stops being offered. Without it a distance-based trigger
       asks every user the same settled question forever.
    4. Genuinely different answers - not an alias of the same root, not the
       same text, and not a near-duplicate (see `answers_diverge`).

    Returns None when any condition fails, which is the overwhelmingly common
    case and must leave the caller on its existing single-hit path untouched.

    `passed[0]` is the served answer and is taken as given. The alternate is the
    CLOSEST of the rest, picked here rather than read off the list order,
    because the lookup ranks each tier by feedback SCORE, not by distance (see
    MemoryService._lookup_candidates) - so the next element is merely the next
    most popular entry, which may be nowhere near the query. Trusting the order
    would silently miss real ties.
    """
    if len(passed) < 2:
        return None

    primary = passed[0]
    primary_distance = primary.distance
    if primary_distance is None or primary_distance > max_distance:
        return None

    eligible = [
        candidate for candidate in passed[1:]
        if candidate.distance is not None and candidate.distance <= max_distance
    ]
    if not eligible:
        return None
    alternate = min(eligible, key=lambda candidate: candidate.distance)

    delta = abs(alternate.distance - primary_distance)
    if delta > max_delta:
        return None

    if abs(primary.score - alternate.score) >= max_score_gap:
        return None

    if _root_id(primary) == _root_id(alternate):
        return None

    if answers_diverge(
        primary.generalized_answer or "", alternate.generalized_answer or ""
    ) is None:
        return None

    return DraftPair(primary=primary, alternate=alternate, distance_delta=delta)
