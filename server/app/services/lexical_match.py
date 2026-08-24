"""Word-level fuzzy alignment between a query and a cached candidate query.

Rationale: typos change *letters*, different questions change *words*.
BGE embeddings cannot separate a heavily typo'd query ("teh captial of rusia",
cosine 0.39 from its clean twin) from a sibling question ("capital of germany",
cosine 0.21) — both look "far". Per-word fuzzy alignment can: every word of a
typo'd query has a close letter-level twin on the other side, while a sibling
question always contains at least one word with no counterpart.

Used as a *gate*, never a rewrite: this module never modifies text, so it cannot
mangle jargon or poison cache keys the way a dictionary spell checker did.

Stdlib only (difflib, re).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher

# Cheap function words that never veto a match on their own. Only applied to
# short tokens (len <= 3) so a typo'd content word is never silently skipped.
_STOPWORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "of", "in", "on", "at",
    "to", "do", "i", "it", "my", "me", "you", "and", "or", "for", "with",
    "can", "be",
})

# Unicode \w (Python 3 str patterns default to Unicode matching) so any
# script's letters/digits survive tokenizing, not just ASCII - the old
# a-z0-9 class stripped Hebrew (and every other non-Latin script) entirely,
# so align() returned aligned=False for two byte-identical Hebrew strings.
# Apostrophe (') and Hebrew geresh (׳) are kept as WORD-INTERNAL
# characters, not stripped to a space: "ניז'ר" (Niger) used to split into
# "ניז" + "ר", so its one leftover word paired against Nigeria's leftover
# ("ניגריה") became TWO leftovers on the candidate side - which defeats the
# single-word-swap hint gate below (it only fires when both sides leave
# exactly one leftover), so the validator got no hint at all on a real
# different-country pair and false-accepted it (dejaq-200-test-fixes,
# defect #1). Same shape as English contractions ("what's" was splitting
# into "what" + "s").
_NON_ALNUM = re.compile(r"[^\w'׳ ]", re.UNICODE)

# Question words are semantically loaded despite being short: "why" vs "who"
# are 0.667 letter-similar but ask different things. A question word may only
# be satisfied by an exact copy or a non-question-word (its own typo, e.g.
# "hwo" -> "how") — never by a DIFFERENT question word.
_QUESTION_WORDS = frozenset({"who", "what", "when", "where", "why", "how", "which"})


@dataclass(frozen=True)
class AlignResult:
    """Outcome of aligning two queries word-by-word.

    aligned: True when every non-trivial token on BOTH sides fuzzy-matches a
        token on the other side (i.e. the two strings plausibly differ only by
        typos / trivial words).
    mismatches: the (word, closest_word_on_other_side) pairs that failed —
        empty when aligned. These identify the semantic difference (e.g.
        ("list", "string")) and can be fed to the cache validator as a hint.
    exact: True only when every token cancelled by an EXACT copy on the other
        side (no fuzzy matching was needed at all) - i.e. the two strings are
        the same words, modulo order/case/stopwords. False both when a real
        mismatch was found AND when the two sides only matched via fuzzy
        letter-similarity - a real distinction the entity-name case needs:
        "אוסטריה"/"אוסטרליה" (Austria/Australia) fuzzy-match at ratio 0.93
        (aligned=True) despite being two different countries, so `aligned`
        alone cannot tell "definitely a typo" from "close enough that it
        might not be". `exact` can: a caller deciding whether to trust a
        near-duplicate distance WITHOUT a validator call should require
        `exact`, not just `aligned`.
    """

    aligned: bool
    mismatches: tuple[tuple[str, str], ...] = ()
    exact: bool = True


def _tokens(text: str) -> list[str]:
    return _NON_ALNUM.sub(" ", text.lower()).split()


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _threshold(word: str) -> float:
    # Short words tolerate proportionally larger edits ("teh"/"the" = 0.667);
    # longer words must stay clearly recognizable.
    return 0.6 if len(word) <= 4 else 0.72


def _leftovers(src: list[str], dst: list[str]) -> list[str]:
    """Tokens of src not cancelled by an exact copy in dst (multiset diff).

    Exact-match cancellation prevents a leftover word from "stealing" a match
    that is already claimed: in "what is the best way ... and why?" the word
    "way" exists on both sides and must pair with itself, so the appended
    "why" cannot fuzzy-match it (0.667) and is correctly left unmatched.
    """
    remaining = Counter(dst)
    out: list[str] = []
    for word in src:
        if remaining.get(word, 0) > 0:
            remaining[word] -= 1
        else:
            out.append(word)
    return out


def _merged_blob_match(word: str, blob: str) -> bool:
    """True when the shorter string appears (nearly) contiguously inside the
    much longer one — the missing-space typo shape: "work" inside
    "digestionworrk". The 1.3x length guard keeps standalone sibling words
    (grass/grease, asyncio/multiprocessing) out: they are similar-length or
    share only scattered letters."""
    short, long_ = (word, blob) if len(word) <= len(blob) else (blob, word)
    if len(long_) < 1.3 * len(short) or len(short) < 3:
        return False
    match = SequenceMatcher(None, short, long_).find_longest_match(0, len(short), 0, len(long_))
    return match.size / len(short) >= 0.75


def _side_mismatches(src: list[str], dst: list[str]) -> list[tuple[str, str]]:
    """Mismatches among LEFTOVER tokens: each src leftover must fuzzy-match a
    dst leftover (its typo'd twin). No dst leftovers => nothing to pair with."""
    misses: list[tuple[str, str]] = []
    for word in src:
        if word in _STOPWORDS and len(word) <= 3:
            continue
        best_ratio = 0.0
        best_word = ""
        for cand in dst:
            r = _ratio(word, cand)
            # Tie-break toward the longer candidate: for a vetoed word the pair
            # is reported as a hint, and "list ~ string" beats "list ~ i".
            if r > best_ratio or (r == best_ratio and len(cand) > len(best_word)):
                best_ratio, best_word = r, cand
        if (
            word in _QUESTION_WORDS
            and best_word in _QUESTION_WORDS
            and best_word != word
        ):
            misses.append((word, best_word))
        elif best_ratio < _threshold(word):
            if any(_merged_blob_match(word, cand) for cand in dst):
                continue  # missing-space merge ("work" ~ "digestionworrk")
            misses.append((word, best_word))
    return misses


def align(query: str, candidate: str) -> AlignResult:
    """Align two queries word-by-word; symmetric (both directions must match).

    Identical words cancel exactly (multiset), then every leftover token on
    BOTH sides must fuzzy-match a leftover on the other side. Symmetry catches
    both a *changed* word (germany vs france) and an *extra* word carrying new
    meaning ("...and when?").
    """
    q_tokens = _tokens(query)
    c_tokens = _tokens(candidate)
    if not q_tokens or not c_tokens:
        return AlignResult(aligned=False, exact=False)

    q_left = _leftovers(q_tokens, c_tokens)
    c_left = _leftovers(c_tokens, q_tokens)
    if not q_left and not c_left:
        return AlignResult(aligned=True, exact=True)

    misses = _side_mismatches(q_left, c_left)
    # Reverse direction: candidate leftovers unmatched by query leftovers.
    # Skip pairs already recorded (same pair reads identically either way).
    seen = {frozenset(p) for p in misses}
    for pair in _side_mismatches(c_left, q_left):
        if frozenset(pair) not in seen:
            misses.append(pair)
            seen.add(frozenset(pair))

    # `mismatches` is a HINT fed to the cache validator ("the new question
    # differs at these words") - only trustworthy for the single-word-swap
    # trap this was built for (docstring's own example: "list" vs "string"),
    # where exactly one leftover word sits on each side. When phrasing
    # differs more broadly - a real paraphrase restructured into a different
    # sentence shape, not a word swap - EVERY leftover word gets forced onto
    # whatever's closest on the other side, however unrelated: measured live,
    # "how many continents are there" vs "what's the total number of
    # continents" produces mismatches=[('what','how'), ('s','there'),
    # ('total','how'), ('number','there'), ('how','of'), ('many','what')] -
    # nonsense pairings between function words, not a real semantic diff.
    # Fed to the validator as "these words differ, reply INVALID if that
    # changes the ask," this measurably flips a correct VALID into a false
    # INVALID (dejaq-acceptance-fixes report, defect #1's root cause) even
    # though the validator judges the same pair VALID with no hint at all.
    # `aligned` below is unaffected - it still reads the FULL `misses`, so
    # rescue-tier gating and sibling rejection (swept over ~1500 pairs) keep
    # exactly their existing behaviour; only the exposed HINT is narrowed.
    hint_mismatches = tuple(misses) if len(q_left) <= 1 and len(c_left) <= 1 else ()

    return AlignResult(aligned=not misses, mismatches=hint_mismatches, exact=False)
