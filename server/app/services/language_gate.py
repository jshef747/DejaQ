"""Cheap, deterministic script-based language gate for cache hits.

This is a Unicode SCRIPT classifier, not a language detector. It exists to
catch one specific failure: a cache hit whose STORED ANSWER is written in a
different script than the QUESTION, e.g. a Hebrew question served a
previously-cached English answer verbatim.

Why a script check and not a model call: the normalizer, generalizer, and
validator already share one Ollama model tag, and the background
generalize() call it fires on every cache miss competes with a live
validate()/adjust() call for that same model - a third model call
(a language-ID prompt) on the hit path would only make that worse. A
per-character Unicode range count costs microseconds and has no model
dependency, so it can run on every hit unconditionally - including the
trusted-tier hits that skip the validator entirely
(distance <= VALIDATOR_SKIP_DISTANCE) and the near-identical hits that skip
the adjuster (distance <= ADJUSTER_SKIP_DISTANCE), neither of which a
validator-prompt-only or adjuster-only check would reach.

Script, not language: French and Spanish both count as LATIN, so this gate
never fires on a French/Spanish pair - every observed cross-lingual leak
(Hebrew<->English, French->Hebrew, Japanese->English, Chinese->English) was
also cross-script.
"""

from __future__ import annotations

import re

_HEBREW = re.compile(r"[֐-׿]")
_ARABIC = re.compile(r"[؀-ۿݐ-ݿ]")
_CJK = re.compile(r"[぀-ヿ一-鿿가-힣]")
_CYRILLIC = re.compile(r"[Ѐ-ӿ]")
_LATIN = re.compile(r"[A-Za-zÀ-ɏ]")

_SCRIPTS: tuple[tuple[str, re.Pattern], ...] = (
    ("hebrew", _HEBREW),
    ("arabic", _ARABIC),
    ("cjk", _CJK),
    ("cyrillic", _CYRILLIC),
    ("latin", _LATIN),
)

# Below this many script-bearing characters, the sample is too short to
# classify with any confidence (a one-word numeric answer, a stray emoji) -
# treated as unknown rather than guessed at, so it never blocks a hit.
_MIN_CHARS = 2

# A script must hold this share of all script-bearing characters to count as
# "dominant" - a mixed-script string (an English sentence quoting one
# Hebrew word) should not confidently claim either script.
_MIN_MAJORITY = 0.6


def dominant_script(text: str) -> str | None:
    """Return the script with the most letters in `text`, or None if too short/ambiguous to call."""
    if not text:
        return None
    counts = {name: len(pattern.findall(text)) for name, pattern in _SCRIPTS}
    total = sum(counts.values())
    if total < _MIN_CHARS:
        return None
    best_script, best_count = max(counts.items(), key=lambda kv: kv[1])
    if best_count / total < _MIN_MAJORITY:
        return None
    return best_script


def scripts_conflict(query: str, answer: str) -> bool:
    """True only when both sides classify confidently AND disagree.

    Either side returning None (too short, mixed, no letters at all - a
    pure-numeric or pure-code answer) means "not enough signal", which
    passes the gate rather than blocking it - the gate's job is to catch a
    known wrong-script serve, not to second-guess every short answer.
    """
    q_script = dominant_script(query)
    a_script = dominant_script(answer)
    if q_script is None or a_script is None:
        return False
    return q_script != a_script
