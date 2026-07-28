"""Noise-robust text representation probe for the image-cache document-matching problem.

Tests whether representations that absorb OCR character noise (rather than
exact token-set overlap) widen the gap between SAME-content pairs and
DIFFERENT-document pairs, at the shared scoring protocol's headline metric:
recall at ZERO false merges.

Run:
    cd server
    uv run python /path/to/textnorm_probe.py
"""
from __future__ import annotations

import math
import sys
import time
import unicodedata
from collections import Counter
from itertools import combinations
from pathlib import Path

import numpy as np

SCRATCH = Path(__file__).parent
sys.path.insert(0, str(SCRATCH))
from protocol import load, evaluate, report, token_jaccard, BASELINE_ZERO_MERGE_RECALL  # noqa: E402

# --------------------------------------------------------------------------
# Hebrew / OCR-noise normalization
# --------------------------------------------------------------------------

# Final-form -> regular-form Hebrew letters.
_HEB_FINAL_MAP = str.maketrans({
    "\u05da": "\u05db",
    "\u05dd": "\u05de",
    "\u05df": "\u05e0",
    "\u05e3": "\u05e4",
    "\u05e5": "\u05e6",
})

# Visually-confusable characters collapsed to a canonical form.
# 0/O/o -> 0 ; 1/l/I/i -> 1 ; 6/\u05d1 -> kept separate (\u05d1 is a real Hebrew letter,
# collapsing it into "6" would destroy Hebrew text; instead we only fold the
# Latin lookalikes that OCR confuses with each other).
_CONFUSABLE_MAP = str.maketrans({
    "O": "0", "o": "0",
    "l": "1", "I": "1", "i": "1",
})

_RTL_MARKS = dict.fromkeys(map(ord, "\u200e\u200f\u202a\u202b\u202c\u202d\u202e"), None)


def strip_diacritics(s: str) -> str:
    """Remove combining marks (Hebrew niqqud, Latin accents)."""
    decomposed = unicodedata.normalize("NFKD", s)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def normalize_text(s: str) -> str:
    s = s.translate(_RTL_MARKS)
    s = strip_diacritics(s)
    s = s.translate(_HEB_FINAL_MAP)
    s = s.translate(_CONFUSABLE_MAP)
    s = s.lower()
    return s


def normalize_token(t: str) -> str:
    return normalize_text(t)


# --------------------------------------------------------------------------
# Character n-gram TF-IDF (df fitted on corpus vocabulary only, no labels)
# --------------------------------------------------------------------------

def char_ngrams(text: str, n: int) -> Counter:
    """Word-bounded character n-grams (char_wb style): pad each word with a
    boundary marker so n-grams don't bleed across word breaks, same idea as
    sklearn's analyzer='char_wb'."""
    grams = Counter()
    for word in text.split():
        padded = f" {word} "
        for i in range(len(padded) - n + 1):
            grams[padded[i:i + n]] += 1
    return grams


class CharNgramTfidf:
    """Corpus-fit (unlabeled) char n-gram TF-IDF cosine similarity.
    IDF is computed once over the corpus's own documents -- exactly what a
    live cache has available from its stored entries, no ground truth used."""

    def __init__(self, n: int, normalize_fn=normalize_text):
        self.n = n
        self.normalize_fn = normalize_fn
        self.df: Counter = Counter()
        self.n_docs = 0
        self.vecs: dict[str, dict[str, float]] = {}
        self.norms: dict[str, float] = {}

    def fit(self, recs: list[dict]) -> None:
        raw_counts = {}
        for r in recs:
            grams = char_ngrams(self.normalize_fn(r["text"]), self.n)
            raw_counts[r["path"]] = grams
            for g in grams:
                self.df[g] += 1
        self.n_docs = len(recs)
        idf = {g: math.log((1 + self.n_docs) / (1 + df)) + 1.0 for g, df in self.df.items()}
        for path, grams in raw_counts.items():
            total = sum(grams.values()) or 1
            vec = {g: (c / total) * idf[g] for g, c in grams.items()}
            self.vecs[path] = vec
            self.norms[path] = math.sqrt(sum(v * v for v in vec.values())) or 1.0

    def score(self, a: dict, b: dict) -> float:
        va, vb = self.vecs[a["path"]], self.vecs[b["path"]]
        if len(va) > len(vb):
            va, vb = vb, va
        dot = sum(v * vb.get(g, 0.0) for g, v in va.items())
        return dot / (self.norms[a["path"]] * self.norms[b["path"]])


# --------------------------------------------------------------------------
# Char-shingle Jaccard (the set-overlap thing MinHash approximates)
# --------------------------------------------------------------------------

class CharShingleJaccard:
    def __init__(self, n: int, normalize_fn=normalize_text):
        self.n = n
        self.normalize_fn = normalize_fn
        self.sets: dict[str, frozenset] = {}

    def fit(self, recs: list[dict]) -> None:
        for r in recs:
            self.sets[r["path"]] = frozenset(char_ngrams(self.normalize_fn(r["text"]), self.n))

    def score(self, a: dict, b: dict) -> float:
        x, y = self.sets[a["path"]], self.sets[b["path"]]
        u = x | y
        return len(x & y) / len(u) if u else 0.0


# --------------------------------------------------------------------------
# Normalized token Jaccard (Hebrew final forms / diacritics / confusables)
# --------------------------------------------------------------------------

class NormalizedTokenJaccard:
    def __init__(self):
        self.sets: dict[str, frozenset] = {}

    def fit(self, recs: list[dict]) -> None:
        for r in recs:
            self.sets[r["path"]] = frozenset(normalize_token(t) for t in r["tokens"])

    def score(self, a: dict, b: dict) -> float:
        x, y = self.sets[a["path"]], self.sets[b["path"]]
        u = x | y
        return len(x & y) / len(u) if u else 0.0


# --------------------------------------------------------------------------
# Confidence-weighted token overlap
# --------------------------------------------------------------------------

class ConfidenceWeightedJaccard:
    """Weighted Jaccard where each token's weight = max per-occurrence OCR
    confidence (0-100 -> 0-1) seen for that token in the document. Shared
    tokens contribute min(weight_a, weight_b) to intersection weight, ensures
    high-confidence tokens dominate the match while noisy low-confidence
    tokens barely register on either side."""

    def __init__(self, normalize_fn=normalize_token):
        self.normalize_fn = normalize_fn
        self.weights: dict[str, dict[str, float]] = {}

    def fit(self, recs: list[dict]) -> None:
        for r in recs:
            w: dict[str, float] = {}
            for word_entry in r["words"]:
                text, conf = word_entry[0], word_entry[1]
                tok = self.normalize_fn(text)
                if not tok:
                    continue
                c = max(0.0, min(100.0, conf)) / 100.0
                w[tok] = max(w.get(tok, 0.0), c)
            self.weights[r["path"]] = w

    def score(self, a: dict, b: dict) -> float:
        wa, wb = self.weights[a["path"]], self.weights[b["path"]]
        keys = set(wa) | set(wb)
        if not keys:
            return 0.0
        inter = sum(min(wa.get(k, 0.0), wb.get(k, 0.0)) for k in keys)
        union = sum(max(wa.get(k, 0.0), wb.get(k, 0.0)) for k in keys)
        return inter / union if union else 0.0


# --------------------------------------------------------------------------
# Fuzzy token overlap (bounded edit distance, greedy matching)
# --------------------------------------------------------------------------

def _edit_distance_leq(a: str, b: str, k: int) -> bool:
    """True if levenshtein(a, b) <= k. Cheap band check: length diff > k
    means no need for DP at all."""
    if abs(len(a) - len(b)) > k:
        return False
    if a == b:
        return True
    la, lb = len(a), len(b)
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        row_min = cur[0]
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            row_min = min(row_min, cur[j])
        if row_min > k:
            return False
        prev = cur
    return prev[lb] <= k


class FuzzyTokenOverlap:
    """Greedy fuzzy token matching: for each token in the smaller set, take
    the best still-unmatched token in the other set within edit distance k.
    Score = matched_pairs / union_size (union counted at the token-set level,
    same denominator shape as Jaccard so it's directly comparable)."""

    def __init__(self, k: int = 1, normalize_fn=normalize_token, bucket_by_len: bool = True):
        self.k = k
        self.normalize_fn = normalize_fn
        self.bucket_by_len = bucket_by_len
        self.token_sets: dict[str, list[str]] = {}

    def fit(self, recs: list[dict]) -> None:
        for r in recs:
            toks = sorted({self.normalize_fn(t) for t in r["tokens"] if t})
            self.token_sets[r["path"]] = toks

    def score(self, a: dict, b: dict) -> float:
        ta, tb = self.token_sets[a["path"]], self.token_sets[b["path"]]
        if not ta and not tb:
            return 0.0
        set_a, set_b = set(ta), set(tb)
        exact = set_a & set_b
        rem_a = sorted(set_a - exact)
        rem_b_list = sorted(set_b - exact)
        # bucket remaining tokens of b by length for a coarse length-band prefilter
        used_b = [False] * len(rem_b_list)
        matched = 0
        for tok in rem_a:
            best_j = -1
            for j, cand in enumerate(rem_b_list):
                if used_b[j]:
                    continue
                if abs(len(tok) - len(cand)) > self.k:
                    continue
                if _edit_distance_leq(tok, cand, self.k):
                    best_j = j
                    break
            if best_j >= 0:
                used_b[best_j] = True
                matched += 1
        inter = len(exact) + matched
        union = len(set_a | set_b)
        return inter / union if union else 0.0


# --------------------------------------------------------------------------
# Sentence-embedding cosine similarity (bge-small-en-v1.5, English-trained;
# text here is mostly Hebrew -- testing whether it still captures anything,
# not expecting strong results per the assignment brief)
# --------------------------------------------------------------------------

def embed_score_fn(recs: list[dict], model_name: str = "BAAI/bge-small-en-v1.5", max_chars: int = 2000):
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name)
    texts = [normalize_text(r["text"])[:max_chars] for r in recs]
    t0 = time.time()
    embs = model.encode(texts, batch_size=32, show_progress_bar=False, normalize_embeddings=True)
    encode_time = time.time() - t0
    emb_by_path = {r["path"]: embs[i] for i, r in enumerate(recs)}

    def score(a: dict, b: dict) -> float:
        return float(np.dot(emb_by_path[a["path"]], emb_by_path[b["path"]]))

    return score, encode_time


# --------------------------------------------------------------------------
# Combination scorers
# --------------------------------------------------------------------------

def combine_max(*fns):
    def score(a, b):
        return max(f(a, b) for f in fns)
    return score


def combine_avg(*fns):
    def score(a, b):
        vals = [f(a, b) for f in fns]
        return sum(vals) / len(vals)
    return score


# --------------------------------------------------------------------------
# Group-median helper: figures on SAME vs DIFFERENT score distributions
# --------------------------------------------------------------------------

def group_medians(recs: list[dict], score_fn) -> tuple[float, float]:
    same_scores = []
    diff_scores = []
    for a, b in combinations(recs, 2):
        s = score_fn(a, b)
        if a["group"] == b["group"]:
            same_scores.append(s)
        else:
            diff_scores.append(s)
    same_scores.sort()
    diff_scores.sort()
    med_same = same_scores[len(same_scores) // 2] if same_scores else float("nan")
    med_diff = diff_scores[len(diff_scores) // 2] if diff_scores else float("nan")
    return med_same, med_diff


def timed_pair_cost(score_fn, recs: list[dict], n_pairs: int = 500) -> float:
    """Rough per-pair wall time in milliseconds, averaged over a sample."""
    sample_pairs = list(combinations(recs, 2))[:n_pairs]
    t0 = time.time()
    for a, b in sample_pairs:
        score_fn(a, b)
    dt = time.time() - t0
    return 1000.0 * dt / len(sample_pairs) if sample_pairs else float("nan")


def hardest_negative(recs: list[dict], score_fn) -> tuple[float, str, str]:
    worst = (-1.0, None, None)
    for a, b in combinations(recs, 2):
        if a["group"] == b["group"]:
            continue
        s = score_fn(a, b)
        if s > worst[0]:
            worst = (s, a["path"], b["path"])
    return worst


def main():
    import random

    print("Loading records (waiting for file to be complete is the caller's job)...")
    recs = load()
    print(f"{len(recs)} document images, {len({r['group'] for r in recs})} groups")

    results_table = []

    def run(name, score_fn, fit_recs=None, subsample_note=None):
        t_recs = fit_recs if fit_recs is not None else recs

        # Measure true per-call latency BEFORE any memoization masks it.
        per_pair_ms = timed_pair_cost(score_fn, t_recs, n_pairs=300)

        # Memoize: evaluate(), group_medians(), and hardest_negative() each
        # walk every pair independently. For cheap scorers this is fine; for
        # expensive ones (fuzzy edit-distance matching) recomputing 3-4x over
        # is wasteful, so cache by (path_a, path_b) after the first pass.
        cache: dict[tuple[str, str], float] = {}

        def cached_fn(a, b):
            key = (a["path"], b["path"])
            if key not in cache:
                cache[key] = score_fn(a, b)
            return cache[key]

        res = evaluate(t_recs, cached_fn, name)
        report(res)
        med_same, med_diff = group_medians(t_recs, cached_fn)
        note = f"  [{subsample_note}]" if subsample_note else ""
        print(f"    runtime/pair: {per_pair_ms:.4f} ms   median SAME={med_same:.4f}  median DIFF={med_diff:.4f}{note}")
        results_table.append({
            "name": name + (f" (subsample)" if subsample_note else ""),
            "recall@0": res["results"].get(0, {}).get("recall"),
            "recall@5": res["results"].get(5, {}).get("recall"),
            "recall@25": res["results"].get(25, {}).get("recall"),
            "ms_per_pair": per_pair_ms,
            "median_same": med_same,
            "median_diff": med_diff,
        })
        return res, cached_fn

    # 0. Baseline
    run("BASELINE token-set Jaccard", token_jaccard)

    # 1. Hebrew-normalized token Jaccard
    ntj = NormalizedTokenJaccard()
    ntj.fit(recs)
    run("Normalized token Jaccard (final-forms/diacritics/confusables)", ntj.score)

    # 2. Confidence-weighted token overlap (on normalized tokens)
    cwj = ConfidenceWeightedJaccard()
    cwj.fit(recs)
    run("Confidence-weighted token Jaccard", cwj.score)

    # 3. Char n-gram TF-IDF cosine, n=3,4,5 (corpus-fit IDF, no labels)
    tfidf_scorers = {}
    for n in (3, 4, 5):
        tfidf = CharNgramTfidf(n)
        tfidf.fit(recs)
        tfidf_scorers[n] = tfidf
        run(f"Char {n}-gram TF-IDF cosine", tfidf.score)

    # 4. Char shingle Jaccard (what MinHash approximates), n=4
    shingle = CharShingleJaccard(4)
    shingle.fit(recs)
    run("Char 4-gram shingle-set Jaccard (MinHash target)", shingle.score)

    # 5. Fuzzy token overlap, edit distance <= 1 and <= 2.
    # A pre-check on this same corpus measured ~7.8 ms/pair for k=1 (greedy
    # O(tokens_a * tokens_b) bounded edit distance). On the full corpus
    # (~216k pairs at 658 docs) that is ~28 minutes PER k value -- too slow to
    # run twice inline, and a data point in itself: not viable in a request
    # path at this token-count scale. We evaluate recall on a fixed random
    # subsample of documents (token lists themselves are the real, full-length
    # ones from fit(recs) -- only the number of PAIRS scored is reduced) so
    # the recall trend is still visible without a multi-hour run, while
    # ms/pair is measured on real pairs from that same subsample and is
    # therefore still a true per-pair cost figure.
    n_fuzzy_sample = min(220, len(recs))
    recs_fuzzy = random.Random(1234).sample(recs, n_fuzzy_sample)
    n_fuzzy_pairs = n_fuzzy_sample * (n_fuzzy_sample - 1) // 2

    fuzzy1 = FuzzyTokenOverlap(k=1)
    fuzzy1.fit(recs)  # fit on full corpus so token lists are real/full-length
    res1, _ = run("Fuzzy token overlap (edit dist <= 1, greedy)", fuzzy1.score,
                  fit_recs=recs_fuzzy, subsample_note=f"subsample n={n_fuzzy_sample} ({n_fuzzy_pairs} pairs)")
    ms1 = results_table[-1]["ms_per_pair"]
    print(f"    extrapolated full {len(recs)}-doc corpus ({len(recs)*(len(recs)-1)//2} pairs) at {ms1:.2f} ms/pair: "
          f"~{len(recs)*(len(recs)-1)//2 * ms1 / 60000:.1f} min")

    fuzzy2 = FuzzyTokenOverlap(k=2)
    fuzzy2.fit(recs)
    res2, _ = run("Fuzzy token overlap (edit dist <= 2, greedy)", fuzzy2.score,
                  fit_recs=recs_fuzzy, subsample_note=f"subsample n={n_fuzzy_sample} ({n_fuzzy_pairs} pairs)")
    ms2 = results_table[-1]["ms_per_pair"]
    print(f"    extrapolated full {len(recs)}-doc corpus ({len(recs)*(len(recs)-1)//2} pairs) at {ms2:.2f} ms/pair: "
          f"~{len(recs)*(len(recs)-1)//2 * ms2 / 60000:.1f} min")

    # 6. Combination: char 4-gram TF-IDF + confidence-weighted token Jaccard
    combo = combine_avg(tfidf_scorers[4].score, cwj.score)
    run("Combo: avg(char4gram TF-IDF, confidence-weighted Jaccard)", combo)

    combo_max = combine_max(tfidf_scorers[4].score, cwj.score)
    run("Combo: max(char4gram TF-IDF, confidence-weighted Jaccard)", combo_max)

    # 7. Sentence embedding (bge-small-en-v1.5) -- report even if weak, per brief
    try:
        embed_fn, encode_time = embed_score_fn(recs)
        print(f"\n(bge-small-en-v1.5 batch-encoded {len(recs)} docs in {encode_time:.2f}s "
              f"= {1000*encode_time/len(recs):.2f} ms/doc; scoring is then a single dot product)")
        run("Sentence embedding cosine (bge-small-en-v1.5)", embed_fn)
    except Exception as e:
        print(f"\nEmbedding approach failed: {e!r}")

    # Hardest negative overall for best performer (char 4-gram tfidf as representative)
    print("\n--- Hardest negative pairs (highest-scoring different-document pair) ---")
    for label, fn in [
        ("token_jaccard", token_jaccard),
        ("char4gram_tfidf", tfidf_scorers[4].score),
        ("normalized_token_jaccard", ntj.score),
        ("confidence_weighted", cwj.score),
    ]:
        s, pa, pb = hardest_negative(recs, fn)
        print(f"  {label}: score={s:.4f}  {Path(pa).name}  vs  {Path(pb).name}")

    print("\n\n=== SUMMARY TABLE ===")
    header = f"{'approach':<55}{'@0':>8}{'@5':>8}{'@25':>8}{'ms/pair':>10}{'med_same':>10}{'med_diff':>10}"
    print(header)
    for r in results_table:
        def pct(x):
            return f"{100*x:.1f}%" if x is not None else "n/a"
        print(f"{r['name']:<55}{pct(r['recall@0']):>8}{pct(r['recall@5']):>8}{pct(r['recall@25']):>8}"
              f"{r['ms_per_pair']:>10.4f}{r['median_same']:>10.4f}{r['median_diff']:>10.4f}")

    print(f"\nBaseline to beat: {100*BASELINE_ZERO_MERGE_RECALL:.1f}% recall @ 0 merges")
    best = max(results_table, key=lambda r: (r["recall@0"] if r["recall@0"] is not None else -1))
    print(f"Best @0-merges: {best['name']} -> {100*best['recall@0']:.1f}%")


if __name__ == "__main__":
    main()
