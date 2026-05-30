"""Cheap heuristic prefilter: decides VALID, INVALID, or AMBIGUOUS without an LLM.

Rules (applied in order, first match wins):
  1. wh-word mismatch — if the interrogative word changes in a way that implies a
     different fact type (e.g. 'what' → 'how many'), vote INVALID.
  2. entity diff — if a capitalized proper noun or number in new_query is absent
     from both cached_query and cached_answer, vote INVALID.
  3. conjunction expansion — if new_query contains a conjunction joining two noun
     phrases that aren't both in cached_query, vote INVALID.
  4. no verdict → AMBIGUOUS (hand off to LLM).
"""

from __future__ import annotations

import re


_WH_WHAT = {"what", "which", "who", "whose", "whom"}
_WH_QUANTITY = {"how many", "how much", "how long", "how far", "how tall", "how deep", "how wide", "how heavy", "how old", "how often"}
_WH_WHEN = {"when"}
_WH_WHERE = {"where"}
_WH_WHY = {"why"}
_WH_HOW = {"how"}

_CONJUNCTION_PATTERNS = re.compile(
    r"\b(and|plus|as well as|along with|together with|in addition to)\b",
    re.IGNORECASE,
)

_QUANTITY_PATTERNS = re.compile(
    r"\b\d[\d,\.]*\b|"
    r"\b(million|billion|trillion|thousand|hundred|percent|%|km|kg|mph|m/s|celsius|fahrenheit|degrees?)\b",
    re.IGNORECASE,
)


def _extract_wh_class(text: str) -> str | None:
    lower = text.lower().strip()
    for wh in _WH_QUANTITY:
        if wh in lower:
            return "quantity"
    # "what year / what time / what date" are temporal → "when" class
    if re.search(r"\bwhat (year|time|date|century|decade|era)\b", lower):
        return "when"
    for wh in _WH_WHEN:
        if wh in lower:
            return "when"
    for wh in _WH_WHERE:
        if wh in lower:
            return "where"
    for wh in _WH_WHY:
        if wh in lower:
            return "why"
    for wh in _WH_WHAT:
        if lower.startswith(wh) or f" {wh} " in lower:
            return "what"
    if lower.startswith("how") or " how " in lower:
        return "how"
    return None


def _extract_proper_nouns(text: str) -> set[str]:
    words = text.split()
    result: set[str] = set()
    for w in words:
        # Strip possessives before cleaning
        w = re.sub(r"'s\b", "", w, flags=re.IGNORECASE)
        clean = re.sub(r"[^a-zA-Z0-9]", "", w)
        if len(clean) >= 2 and clean[0].isupper() and not clean.isupper():
            result.add(clean.lower())
    return result


def _extract_numbers(text: str) -> set[str]:
    return set(re.findall(r"\b\d[\d,\.]*\b", text))


def apply(
    cached_query: str,
    cached_answer: str,
    new_query: str,
) -> tuple[str, str]:
    """Return (verdict, reason) where verdict is VALID, INVALID, or AMBIGUOUS."""

    # Rule 1: wh-word class mismatch
    old_wh = _extract_wh_class(cached_query)
    new_wh = _extract_wh_class(new_query)
    if old_wh and new_wh and old_wh != new_wh:
        # 'what' → 'how many' is a clear fact-type change
        if "quantity" in (new_wh,) and old_wh in ("what", "who", "where", "why"):
            return ("INVALID", f"wh-mismatch: {old_wh!r}→{new_wh!r}")
        if new_wh == "when" and old_wh in ("what", "who", "where"):
            return ("INVALID", f"wh-mismatch: {old_wh!r}→{new_wh!r}")
        if new_wh == "where" and old_wh in ("what", "who", "when"):
            return ("INVALID", f"wh-mismatch: {old_wh!r}→{new_wh!r}")
        if new_wh == "who" and old_wh in ("what", "when", "where"):
            return ("INVALID", f"wh-mismatch: {old_wh!r}→{new_wh!r}")

    # Rule 2: entity diff — new query contains a proper noun absent from both cached
    new_entities = _extract_proper_nouns(new_query)
    cached_entities = _extract_proper_nouns(cached_query) | _extract_proper_nouns(cached_answer)
    novel_entities = new_entities - cached_entities
    # Ignore common English words that are capitalized (e.g. first word of sentence)
    stopwords = {"what", "who", "where", "when", "how", "is", "are", "was", "were", "the", "a", "an", "in", "of", "and", "or", "for", "to", "do", "does", "did", "can", "could", "would", "should", "its"}
    novel_entities = {e for e in novel_entities if e not in stopwords and len(e) >= 3}
    if novel_entities:
        return ("INVALID", f"new entity not in cache: {sorted(novel_entities)[:3]}")

    # Rule 3: conjunction expansion
    if _CONJUNCTION_PATTERNS.search(new_query) and not _CONJUNCTION_PATTERNS.search(cached_query):
        return ("INVALID", "conjunction expansion: new query asks for multiple facts")

    return ("AMBIGUOUS", "no heuristic fired")


if __name__ == "__main__":
    cases = [
        # (cached_query, cached_answer, new_query, expected)
        ("What is the capital of New Zealand?",
         "Wellington is the capital city of New Zealand.",
         "How many people live in the capital of New Zealand?",
         "INVALID"),
        ("What is the capital of France?",
         "The capital of France is Paris.",
         "What is France's capital city?",
         "AMBIGUOUS"),
        ("What is the capital of New Zealand?",
         "Wellington is the capital of New Zealand.",
         "What is the capital of Australia?",
         "INVALID"),
        ("Who invented the telephone?",
         "Alexander Graham Bell invented the telephone.",
         "In what year was the telephone invented?",
         "INVALID"),
        ("Who wrote Hamlet?",
         "Hamlet was written by William Shakespeare.",
         "Who wrote Hamlet and when was it written?",
         "INVALID"),
        ("What is photosynthesis?",
         "Photosynthesis is how plants convert sunlight into glucose.",
         "yo eli5 photosynthesis",
         "AMBIGUOUS"),
    ]
    ok = True
    for cq, ca, nq, expected in cases:
        verdict, reason = apply(cq, ca, nq)
        status = "OK" if verdict == expected else "FAIL"
        if status == "FAIL":
            ok = False
        print(f"  {status}  {verdict!r} ({reason})  expected {expected!r}")
        print(f"       new_query: {nq!r}")
    print("All OK" if ok else "FAILURES above")
