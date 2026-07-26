"""Structured-field extraction for the image-cache document-matching problem.

Hypothesis: documents are identified by a handful of structured fields (dates,
times, ID/course numbers, sitting/version markers, money amounts, emails,
URLs) rather than by raw vocabulary overlap. Extract those fields explicitly;
require them to agree (with OCR-noise-tolerant fuzzy matching); use
disagreement as a hard veto; use token-Jaccard as a base/gate signal.

Scored with the shared protocol (protocol.py), unchanged.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
import time
from dataclasses import dataclass, field

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from protocol import load, evaluate, report, token_jaccard, BASELINE_ZERO_MERGE_RECALL

# ---------------------------------------------------------------------------
# Digit OCR confusion classes. Tesseract's most common digit misreads.
# Symmetric pairs: a single substitution within one of these pairs, at one
# digit position, is treated as "could be OCR noise, not a real difference".
# ---------------------------------------------------------------------------
CONFUSABLE_DIGITS = {
    frozenset(p) for p in [
        (0, 6), (0, 8), (0, 9),
        (1, 7), (1, 4),
        (2, 7),
        (3, 8), (3, 9),
        (5, 6), (5, 8),
        (6, 8), (6, 9),
        (8, 9),
    ]
}


def digits_confusable(d1: str, d2: str) -> bool:
    """Same length, and every differing position is a known OCR confusion pair,
    with at most 1 total substitution allowed."""
    if len(d1) != len(d2):
        return False
    diffs = 0
    for c1, c2 in zip(d1, d2):
        if c1 == c2:
            continue
        if c1.isdigit() and c2.isdigit() and frozenset((int(c1), int(c2))) in CONFUSABLE_DIGITS:
            diffs += 1
            if diffs > 1:
                return False
        else:
            return False
    return True


# ---------------------------------------------------------------------------
# Field extraction
# ---------------------------------------------------------------------------

# Dates: dd.mm.yy(yy), dd/mm/yyyy, dd-mm-yyyy, yyyy-mm-dd, dd.mm (no year)
DATE_RE = re.compile(
    r"""(?<!\d)
    (?:
        (?P<d1>\d{1,2})[./\-](?P<m1>\d{1,2})[./\-](?P<y1>\d{2,4})   # dd.mm.yy(yy)
        |
        (?P<y2>\d{4})[./\-](?P<m2>\d{1,2})[./\-](?P<d2>\d{1,2})     # yyyy-mm-dd
    )
    (?!\d)""",
    re.VERBOSE,
)

# Times: H:MM or HH:MM, optionally with seconds
TIME_RE = re.compile(r"(?<!\d)(\d{1,2}):(\d{2})(?::\d{2})?(?!\d)")

# Long digit runs: 4+ consecutive digits (course/invoice/id numbers), captured
# separately from date/time matches (those are stripped first).
DIGIT_RUN_RE = re.compile(r"(?<!\d)\d{4,}(?!\d)")

# Money amounts: currency symbol + digits, or digits + currency word
MONEY_RE = re.compile(r"(?:[$\u20ac\u20aa\u00a3]\s?\d[\d,]*(?:\.\d+)?)|(?:\d[\d,]*(?:\.\d+)?\s?(?:USD|ILS|EUR|GBP|\u05e9\"\u05d7|\u05e9\u05d7))")

EMAIL_RE = re.compile(r"[A-Za-z0-9_.+-]+@[A-Za-z0-9-]+\.[A-Za-z0-9.-]+")
URL_RE = re.compile(r"https?://[^\s]+|www\.[^\s]+")

# Hebrew exam "sitting" marker: \u05de\u05d5\u05e2\u05d3 \u05d0' / \u05de\u05d5\u05e2\u05d3 \u05d1' (moed A / moed B), plus
# generic English "Version A/B", "Exam A/B", "Sitting 1/2" style markers.
SITTING_RE = re.compile(r"\u05de\u05d5\u05e2\u05d3\s*([\u05d0\u05d1])")
# Marker word is case-insensitive, but the captured sitting/version token must
# be an uppercase letter or digit (e.g. "Version A", "Exam 2") -- otherwise
# ordinary lowercase prose ("as part of", "in the form of") false-fires on
# common two-letter words like "of", "so", "is".
VERSION_RE = re.compile(r"\b(?:(?i:version|ver\.?|exam|sitting|part|form))\s*[:\-]?\s*([A-Z0-9]{1,2})\b(?![a-z])")


def _norm_year(y: str) -> int:
    yi = int(y)
    if yi < 100:
        return 2000 + yi if yi < 70 else 1900 + yi
    return yi


def extract_dates(text: str) -> list[tuple[int, int, int]]:
    out = []
    for m in DATE_RE.finditer(text):
        try:
            if m.group("d1"):
                d, mo, y = int(m.group("d1")), int(m.group("m1")), _norm_year(m.group("y1"))
            else:
                d, mo, y = int(m.group("d2")), int(m.group("m2")), _norm_year(m.group("y2"))
            if 1 <= d <= 31 and 1 <= mo <= 12:
                out.append((d, mo, y))
        except (ValueError, TypeError):
            continue
    return out


def extract_times(text: str) -> list[tuple[int, int]]:
    out = []
    for m in TIME_RE.finditer(text):
        h, mi = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and 0 <= mi <= 59:
            out.append((h, mi))
    return out


def extract_digit_runs(text: str) -> list[str]:
    # Remove date/time-shaped substrings first so long digit runs are truly
    # separate identifiers, not fragments of dates already captured.
    stripped = DATE_RE.sub(" ", text)
    stripped = TIME_RE.sub(" ", stripped)
    return DIGIT_RUN_RE.findall(stripped)


def extract_money(text: str) -> list[str]:
    return [re.sub(r"\s", "", m) for m in MONEY_RE.findall(text)]


def extract_sitting(text: str) -> list[str]:
    out = [f"moed_{m.group(1)}" for m in SITTING_RE.finditer(text)]
    out += [f"ver_{m.group(1).lower()}" for m in VERSION_RE.finditer(text)]
    return out


@dataclass
class Fields:
    dates: list = field(default_factory=list)
    times: list = field(default_factory=list)
    digit_runs: list = field(default_factory=list)
    money: list = field(default_factory=list)
    emails: list = field(default_factory=list)
    urls: list = field(default_factory=list)
    sitting: list = field(default_factory=list)


_CACHE: dict[str, Fields] = {}


def get_fields(rec: dict) -> Fields:
    key = rec["path"]
    f = _CACHE.get(key)
    if f is not None:
        return f
    text = rec["text"]
    f = Fields(
        dates=extract_dates(text),
        times=extract_times(text),
        digit_runs=extract_digit_runs(text),
        money=extract_money(text),
        emails=[e.lower() for e in EMAIL_RE.findall(text)],
        urls=[u.lower() for u in URL_RE.findall(text)],
        sitting=extract_sitting(text),
    )
    _CACHE[key] = f
    return f


def date_str(d: tuple[int, int, int]) -> str:
    return f"{d[0]:02d}{d[1]:02d}{d[2]:04d}"


def time_str(t: tuple[int, int]) -> str:
    return f"{t[0]:02d}{t[1]:02d}"


def any_fuzzy_match(list_a, list_b, keyfn) -> bool:
    for a in list_a:
        ka = keyfn(a)
        for b in list_b:
            if digits_confusable(ka, keyfn(b)):
                return True
    return False


def any_exact_match(list_a, list_b) -> bool:
    sa, sb = set(list_a), set(list_b)
    return bool(sa & sb)


def money_key(m: str) -> str:
    """Strip currency symbols/words, keep the digit string for fuzzy compare."""
    return re.sub(r"[^\d]", "", m)


def _edit_distance_at_most_1(a: str, b: str) -> bool:
    """True if a and b differ by at most one single-character edit
    (substitution, insertion, or deletion). O(len) check, no DP needed since
    the budget is 1."""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la == lb:
        # at most one substitution
        diffs = sum(1 for x, y in zip(a, b) if x != y)
        return diffs <= 1
    # one is one character longer: check single insertion/deletion
    shorter, longer = (a, b) if la < lb else (b, a)
    i = j = 0
    skipped = False
    while i < len(shorter) and j < len(longer):
        if shorter[i] == longer[j]:
            i += 1
            j += 1
        else:
            if skipped:
                return False
            skipped = True
            j += 1
    return True


def any_truncation_or_exact_match(list_a, list_b, min_len: int = 8) -> bool:
    """OCR noise on long identifying strings (emails, URLs) takes two common
    shapes: truncation (a character misread as whitespace/garbage cuts the
    tail) or a single character substitution/insertion/deletion elsewhere in
    the string. Treat either as a match; both require the string to be
    reasonably long first, so short generic tokens can't spuriously match."""
    for a in list_a:
        for b in list_b:
            if a == b:
                return True
            shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
            if len(shorter) < min_len:
                continue
            if longer.startswith(shorter):
                return True
            if _edit_distance_at_most_1(a, b):
                return True
    return False


def field_verdicts(fa: Fields, fb: Fields, fuzzy_ids: bool = True,
                    digit_run_min_len: int = 5) -> dict[str, str | None]:
    """For each field type return 'agree' / 'disagree' / None (can't compare,
    at least one side missing the field)."""
    verdicts = {}

    def verdict_fuzzy(la, lb, keyfn):
        if not la or not lb:
            return None
        return "agree" if any_fuzzy_match(la, lb, keyfn) else "disagree"

    def verdict_exact(la, lb):
        if not la or not lb:
            return None
        return "agree" if any_exact_match(la, lb) else "disagree"

    def verdict_truncation(la, lb, min_len):
        if not la or not lb:
            return None
        return "agree" if any_truncation_or_exact_match(la, lb, min_len) else "disagree"

    verdicts["date"] = verdict_fuzzy(fa.dates, fb.dates, date_str)
    verdicts["time"] = verdict_fuzzy(fa.times, fb.times, time_str)

    # Short digit runs (page numbers, footers, single-digit page counts) are
    # noisy and not reliably identifying; only treat runs at/above
    # digit_run_min_len as veto-worthy identifiers (course/invoice/ID numbers).
    long_a = [d for d in fa.digit_runs if len(d) >= digit_run_min_len]
    long_b = [d for d in fb.digit_runs if len(d) >= digit_run_min_len]
    if fuzzy_ids:
        verdicts["digit_run"] = verdict_fuzzy(long_a, long_b, lambda x: x)
    else:
        verdicts["digit_run"] = verdict_exact(long_a, long_b)

    if fuzzy_ids:
        verdicts["money"] = verdict_fuzzy(fa.money, fb.money, money_key)
    else:
        verdicts["money"] = verdict_exact(fa.money, fb.money)
    verdicts["email"] = verdict_truncation(fa.emails, fb.emails, min_len=8)
    verdicts["url"] = verdict_truncation(fa.urls, fb.urls, min_len=8)
    verdicts["sitting"] = verdict_exact(fa.sitting, fb.sitting)
    return verdicts


# ---------------------------------------------------------------------------
# Candidate scoring functions
# ---------------------------------------------------------------------------

ALL_FIELD_TYPES = ("date", "time", "digit_run", "money", "email", "url", "sitting")


def make_scorer(*, missing_penalty: float = 0.0, agree_bonus: float = 0.05,
                 disagree_veto: float = -10.0, fuzzy_ids: bool = True,
                 digit_run_min_len: int = 5, base: str = "jaccard",
                 veto_fields: tuple = ALL_FIELD_TYPES):
    """Factory: token-Jaccard (or flat base) gated/boosted by field verdicts.

    missing_penalty: score subtracted per field type where one side has the
        field and the other doesn't (tests the "asymmetric" question).
    agree_bonus: score added per field type where both sides have the field
        and it fuzzy/exact-matches.
    disagree_veto: if ANY field type disagrees, return this (very low; should
        dominate a sort so it lands below all true negatives too).
    """

    def score(a: dict, b: dict) -> float:
        fa, fb = get_fields(a), get_fields(b)
        verdicts = field_verdicts(fa, fb, fuzzy_ids=fuzzy_ids, digit_run_min_len=digit_run_min_len)

        if any(v == "disagree" and ftype in veto_fields for ftype, v in verdicts.items()):
            return disagree_veto

        base_score = token_jaccard(a, b) if base == "jaccard" else 0.0
        for ftype, v in verdicts.items():
            if v == "agree":
                base_score += agree_bonus
            elif v is None:
                # one or both sides missing this field type -> no evidence
                base_score -= missing_penalty
        return base_score

    return score


def fields_only_score(a: dict, b: dict) -> float:
    """Pure field-agreement score, ignoring token Jaccard entirely, to isolate
    how much signal structured fields alone carry."""
    fa, fb = get_fields(a), get_fields(b)
    verdicts = field_verdicts(fa, fb, fuzzy_ids=True)
    if any(v == "disagree" for v in verdicts.values()):
        return -10.0
    return sum(1 for v in verdicts.values() if v == "agree")


def which_fields_fire(recs, verdicts_dump=False):
    """Diagnostic: for every pair, which field types ever produce a verdict at
    all (agree or disagree), split by same-group vs different-group."""
    from itertools import combinations
    counts = {"same": {}, "diff": {}}
    for a, b in combinations(recs, 2):
        same = a["group"] == b["group"]
        bucket = counts["same"] if same else counts["diff"]
        fa, fb = get_fields(a), get_fields(b)
        verdicts = field_verdicts(fa, fb, fuzzy_ids=True)
        for ftype, v in verdicts.items():
            if v is None:
                continue
            key = (ftype, v)
            bucket[key] = bucket.get(key, 0) + 1
    return counts


if __name__ == "__main__":
    recs = load()
    print(f"{len(recs)} document images, {len({r['group'] for r in recs})} groups")
    print(f"sources: {sorted(set(r['source'] for r in recs))}")

    report(evaluate(recs, token_jaccard, "BASELINE token-set Jaccard"))

    variants = {
        "fields: veto-only, jaccard base (bonus=0)": make_scorer(agree_bonus=0.0, missing_penalty=0.0),
        "fields: veto + agree-bonus 0.05": make_scorer(agree_bonus=0.05, missing_penalty=0.0),
        "fields: veto + agree-bonus 0.15": make_scorer(agree_bonus=0.15, missing_penalty=0.0),
        "fields: veto + missing-penalty 0.05": make_scorer(agree_bonus=0.05, missing_penalty=0.05),
        "fields: veto + missing-penalty 0.15": make_scorer(agree_bonus=0.05, missing_penalty=0.15),
        "fields: exact digit-run match (no fuzzy)": make_scorer(agree_bonus=0.05, missing_penalty=0.0, fuzzy_ids=False),
        "fields: no-money-veto (money=bonus only)": make_scorer(
            agree_bonus=0.05, missing_penalty=0.0,
            veto_fields=("date", "time", "digit_run", "email", "url", "sitting"),
        ),
        "fields: digit_run_min_len=6": make_scorer(agree_bonus=0.05, missing_penalty=0.0, digit_run_min_len=6),
        "fields: digit_run_min_len=4": make_scorer(agree_bonus=0.05, missing_penalty=0.0, digit_run_min_len=4),
        "fields: strong veto set only (date+time+sitting)": make_scorer(
            agree_bonus=0.05, missing_penalty=0.0,
            veto_fields=("date", "time", "sitting"),
        ),
        "fields: SAFE veto set (date+time+sitting+email+url, money/digit_run=bonus-only)": make_scorer(
            agree_bonus=0.05, missing_penalty=0.0,
            veto_fields=("date", "time", "sitting", "email", "url"),
        ),
        "fields: pure field-agreement (no jaccard base)": fields_only_score,
    }

    for name, fn in variants.items():
        t0 = time.time()
        result = evaluate(recs, fn, name)
        n_pairs = result["n_same"] + result["n_diff"]
        elapsed = time.time() - t0
        report(result)
        print(f"    runtime: {1000 * elapsed / n_pairs:.4f} ms/pair (extraction cached per-image)")

    print("\n=== Field firing diagnostic (which field types produce any verdict) ===")
    counts = which_fields_fire(recs)
    print("same-group verdicts:", counts["same"])
    print("diff-group verdicts:", counts["diff"])

    print("\n=== Subset split: coursework vs docunet ===")
    subset_variants = [
        "fields: veto + agree-bonus 0.05",
        "fields: no-money-veto (money=bonus only)",
        "fields: strong veto set only (date+time+sitting)",
        "fields: SAFE veto set (date+time+sitting+email+url, money/digit_run=bonus-only)",
    ]
    for src in sorted(set(r["source"] for r in recs)):
        sub = [r for r in recs if r["source"] == src]
        groups = len({r["group"] for r in sub})
        print(f"\n--- subset={src}  n={len(sub)}  groups={groups} ---")
        if groups < 2:
            print("    (fewer than 2 groups; skipping pair eval)")
            continue
        report(evaluate(sub, token_jaccard, f"[{src}] baseline jaccard"))
        for name in subset_variants:
            report(evaluate(sub, variants[name], f"[{src}] {name}"))
