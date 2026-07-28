"""Sequence / word-order family of candidates for the image-cache document
matching problem.

Hypothesis under test: plain token-SET Jaccard throws away word order. Two
different exam papers share nearly all boilerplate words but differ in the
phrases immediately around the date/session-letter; two re-captures of the
SAME page preserve word order even when individual words get OCR noise.
Sequence-aware signals (n-grams, LCS, longest common run) might separate these
better than a token set does.

All scoring goes through protocol.evaluate() unchanged, so the "recall @ 0
false merges" number is directly comparable to the 45.4% baseline and to
other agents' families.

Run:
    cd server
    uv run python ../evals/image_similarity/candidates/sequence_probe.py
"""
from __future__ import annotations

import bisect
import re
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path

SCRATCH = Path(__file__).parent
sys.path.insert(0, str(SCRATCH))
from protocol import BASELINE_ZERO_MERGE_RECALL, evaluate, load, report, token_jaccard  # noqa: E402

# Same token pattern the shipped gate uses (app/services/image_text.py::_TOKEN_RE),
# copied here (not imported) so this probe has no import-time dependency beyond
# protocol.py. Latin + digits + Hebrew block; length >= 3 filter matches the
# "tokens" field so word-order signals are apples-to-apples with the baseline.
_TOKEN_RE = re.compile(r"[a-z0-9@._\u0590-\u05ff]+")


def prepare(recs: list[dict]) -> None:
    """Attach an ORDERED token sequence (not deduped, not sorted) and a
    normalised char string to every record, in place. Also precompute the
    n-gram sets ONCE per document (not per pair) -- rebuilding a document's
    char-4gram set on every one of its ~250 pairwise comparisons is pure
    waste; computing it once and reusing is a >10x speedup for the n-gram
    family and costs nothing in accuracy."""
    for r in recs:
        toks = [t for t in _TOKEN_RE.findall(r["text"].lower()) if len(t) >= 3]
        r["seq"] = tuple(toks)
        r["ctext"] = " ".join(toks)
        r["bigrams"] = word_ngrams(r["seq"], 2)
        r["trigrams"] = word_ngrams(r["seq"], 3)
        r["char3"] = char_ngrams(r["ctext"], 3)
        r["char4"] = char_ngrams(r["ctext"], 4)
        r["char5"] = char_ngrams(r["ctext"], 5)


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------

def word_ngrams(seq: tuple[str, ...], n: int) -> frozenset[tuple[str, ...]]:
    if len(seq) < n:
        return frozenset()
    return frozenset(seq[i:i + n] for i in range(len(seq) - n + 1))


def char_ngrams(s: str, n: int) -> frozenset[str]:
    if len(s) < n:
        return frozenset()
    return frozenset(s[i:i + n] for i in range(len(s) - n + 1))


def jaccard(a: frozenset, b: frozenset) -> float:
    u = a | b
    return len(a & b) / len(u) if u else 0.0


def lcs_length(a: tuple[str, ...], b: tuple[str, ...]) -> int:
    """Exact longest common SUBSEQUENCE length via the classic reduction to
    Longest Increasing Subsequence (patience sorting): for each element of a
    in order, list the positions where it occurs in b, in DECREASING order;
    concatenate all these lists; the LIS length of the result equals LCS(a, b).
    O((n + r) log n) where r = number of matching (a[i], b[j]) pairs -- much
    faster than the O(n*m) DP table when the shared vocabulary is moderate,
    which it is here (a few hundred distinct tokens per exam page)."""
    pos: dict[str, list[int]] = {}
    for j, tok in enumerate(b):
        pos.setdefault(tok, []).append(j)
    for lst in pos.values():
        lst.reverse()  # decreasing order, so LIS length == LCS length
    seq: list[int] = []
    seq_extend = seq.extend
    for tok in a:
        lst = pos.get(tok)
        if lst:
            seq_extend(lst)
    tails: list[int] = []
    for x in seq:
        idx = bisect.bisect_left(tails, x)
        if idx == len(tails):
            tails.append(x)
        else:
            tails[idx] = x
    return len(tails)


def longest_common_run(a: tuple[str, ...], b: tuple[str, ...]) -> int:
    """Exact longest common CONTIGUOUS run of words, via difflib's
    find_longest_match (stdlib, indexes b once then walks a -- effectively
    O(n + m) for non-degenerate text, exact, well tested)."""
    if not a or not b:
        return 0
    m = SequenceMatcher(None, a, b, autojunk=False)
    match = m.find_longest_match(0, len(a), 0, len(b))
    return match.size


# ---------------------------------------------------------------------------
# Candidate score functions
# ---------------------------------------------------------------------------

def make_word_ngram(n: int):
    key = {2: "bigrams", 3: "trigrams"}[n]

    def score(a: dict, b: dict) -> float:
        return jaccard(a[key], b[key])
    score.__name__ = f"word_{n}gram_jaccard"
    return score


def make_char_ngram(n: int):
    key = f"char{n}"

    def score(a: dict, b: dict) -> float:
        return jaccard(a[key], b[key])
    score.__name__ = f"char_{n}gram_jaccard"
    return score


def lcs_norm_min(a: dict, b: dict) -> float:
    denom = min(len(a["seq"]), len(b["seq"]))
    if denom == 0:
        return 0.0
    return lcs_length(a["seq"], b["seq"]) / denom


def lcs_norm_mean(a: dict, b: dict) -> float:
    denom = (len(a["seq"]) + len(b["seq"])) / 2.0
    if denom == 0:
        return 0.0
    return lcs_length(a["seq"], b["seq"]) / denom


def run_norm_min(a: dict, b: dict) -> float:
    denom = min(len(a["seq"]), len(b["seq"]))
    if denom == 0:
        return 0.0
    return longest_common_run(a["seq"], b["seq"]) / denom


def run_norm_mean(a: dict, b: dict) -> float:
    denom = (len(a["seq"]) + len(b["seq"])) / 2.0
    if denom == 0:
        return 0.0
    return longest_common_run(a["seq"], b["seq"]) / denom


_bigram = make_word_ngram(2)
_trigram = make_word_ngram(3)
_char4 = make_char_ngram(4)


def combo_uni_bi(a: dict, b: dict) -> float:
    return 0.5 * token_jaccard(a, b) + 0.5 * _bigram(a, b)


def combo_uni_bi_tri(a: dict, b: dict) -> float:
    return (token_jaccard(a, b) + _bigram(a, b) + _trigram(a, b)) / 3.0


def combo_uni_char4(a: dict, b: dict) -> float:
    return 0.5 * token_jaccard(a, b) + 0.5 * _char4(a, b)


def combo_uni_bi_lcs(a: dict, b: dict) -> float:
    return 0.34 * token_jaccard(a, b) + 0.33 * _bigram(a, b) + 0.33 * lcs_norm_min(a, b)


def combo_uni_run(a: dict, b: dict) -> float:
    return 0.5 * token_jaccard(a, b) + 0.5 * run_norm_min(a, b)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def timed_evaluate(recs: list[dict], score, name: str, sample_pairs: int = 4000) -> dict:
    """Run the mandatory protocol.evaluate(), plus an independent wall-clock
    timing of the score function alone (protocol.evaluate() does its own
    pair enumeration; we time a fresh sample so the number reflects pure
    per-pair cost, not list-building overhead)."""
    from itertools import combinations, islice

    pair_iter = islice(combinations(recs, 2), sample_pairs)
    sample = list(pair_iter)
    t0 = time.perf_counter()
    for a, b in sample:
        score(a, b)
    t1 = time.perf_counter()
    per_pair_us = (t1 - t0) / len(sample) * 1e6 if sample else float("nan")

    result = evaluate(recs, score, name)
    result["per_pair_us"] = per_pair_us
    return result


def hardest_negative_pair(recs: list[dict], score) -> dict:
    """Find the different-group pair with the highest score -- the exact
    false-merge-causing near-miss, with enough detail to report it."""
    from itertools import combinations

    worst = None
    worst_s = float("-inf")
    for a, b in combinations(recs, 2):
        if a["group"] == b["group"]:
            continue
        s = score(a, b)
        if s > worst_s:
            worst_s = s
            worst = (a, b)
    a, b = worst
    return {
        "score": worst_s,
        "path_a": a["path"], "group_a": a["group"],
        "path_b": b["path"], "group_b": b["group"],
        "token_jaccard": token_jaccard(a, b),
    }


def main() -> None:
    print("Loading document records...")
    recs = load()
    print(f"{len(recs)} document images, {len({r['group'] for r in recs})} groups")
    prepare(recs)

    approaches = [
        ("word_bigram_jaccard", make_word_ngram(2)),
        ("word_trigram_jaccard", make_word_ngram(3)),
        ("char_3gram_jaccard", make_char_ngram(3)),
        ("char_4gram_jaccard", make_char_ngram(4)),
        ("char_5gram_jaccard", make_char_ngram(5)),
        ("lcs_norm_min", lcs_norm_min),
        ("lcs_norm_mean", lcs_norm_mean),
        ("longest_run_norm_min", run_norm_min),
        ("longest_run_norm_mean", run_norm_mean),
        ("combo_unigram+bigram", combo_uni_bi),
        ("combo_uni+bi+tri", combo_uni_bi_tri),
        ("combo_unigram+char4gram", combo_uni_char4),
        ("combo_uni+bi+lcs", combo_uni_bi_lcs),
        ("combo_unigram+run", combo_uni_run),
    ]

    all_results = []
    for name, fn in approaches:
        t0 = time.perf_counter()
        res = timed_evaluate(recs, fn, name)
        wall = time.perf_counter() - t0
        res["wall_s"] = wall
        all_results.append(res)
        report(res)
        print(f"    per-pair: {res['per_pair_us']:.2f} us   full-eval wall: {wall:.1f}s")

    print("\n\n================ SUMMARY ================")
    print(f"BASELINE (token-set Jaccard) recall @ 0 merges: {100*BASELINE_ZERO_MERGE_RECALL:.1f}%")
    print(f"{'approach':<28}{'recall@0':>10}{'recall@5':>10}{'recall@25':>11}{'us/pair':>10}")
    for res in all_results:
        r0 = res["results"].get(0, {}).get("recall", 0.0)
        r5 = res["results"].get(5, {}).get("recall", 0.0)
        r25 = res["results"].get(25, {}).get("recall", 0.0)
        print(f"{res['name']:<28}{100*r0:>9.1f}%{100*r5:>9.1f}%{100*r25:>10.1f}%{res['per_pair_us']:>9.2f}u")

    best = max(all_results, key=lambda r: (r["results"].get(0, {}).get("recall", 0.0),
                                            r["results"].get(5, {}).get("recall", 0.0)))
    fn_by_name = {name: fn for name, fn in approaches}
    print(f"\nBest by recall@0: {best['name']}")
    hn = hardest_negative_pair(recs, fn_by_name[best["name"]])
    print(f"Hardest negative pair for {best['name']}:")
    print(f"    {hn['path_a']}  (group={hn['group_a']})")
    print(f"    {hn['path_b']}  (group={hn['group_b']})")
    print(f"    score={hn['score']:.4f}   token_jaccard={hn['token_jaccard']:.4f}")


if __name__ == "__main__":
    main()
