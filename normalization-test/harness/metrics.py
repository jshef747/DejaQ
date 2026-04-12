"""Metric computation for normalization test runs.

Given a list of (concept_id, category, phrasing_index, normalized_text) rows
for a single config, compute:

- Sibling cosine distance statistics (mean, median, p95, max)
- Sibling hit rate @ 0.15 (production SIMILARITY_THRESHOLD)
- Sibling hit rate @ 0.20 (production FEEDBACK_TRUSTED_SIMILARITY)
- Cross-concept false-positive rate @ 0.15 (sampled)
- Per-category breakdown
- Latency statistics (mean, p95)
- Worst sibling pairs for debugging

Thresholds mirror server/app/services/memory_chromaDB.py:12 and
server/app/config.py FEEDBACK_TRUSTED_SIMILARITY.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from itertools import combinations
from typing import Iterable

import numpy as np

from harness.embedder import Embedder, pairwise_cosine_distance

PRODUCTION_THRESHOLD = 0.15
TRUSTED_THRESHOLD = 0.20
CROSS_SAMPLE_SIZE = 5000


@dataclass
class NormalizedRow:
    concept_id: str
    category: str
    phrasing_index: int
    original: str
    normalized: str
    latency_ms: float


@dataclass
class SiblingPairResult:
    concept_id: str
    category: str
    distances: list[float]  # 3 pairwise distances for 3 phrasings
    max_distance: float
    originals: list[str]
    normalized: list[str]


@dataclass
class CategoryMetrics:
    category: str
    n_concepts: int
    mean_sibling_distance: float
    p95_sibling_distance: float
    hit_rate_at_015: float
    hit_rate_at_020: float


@dataclass
class ConfigMetrics:
    config_name: str
    n_concepts: int
    n_prompts: int
    # Sibling distance stats (across all pairs from all concepts)
    mean_sibling_distance: float
    median_sibling_distance: float
    p95_sibling_distance: float
    max_sibling_distance: float
    # Hit rates (% of sibling pairs under threshold)
    hit_rate_at_015: float
    hit_rate_at_020: float
    # Cross-concept false positive rate
    cross_fp_rate_at_015: float
    cross_fp_rate_at_020: float
    n_cross_pairs_sampled: int
    # Latency
    mean_latency_ms: float
    p95_latency_ms: float
    # Per-category
    by_category: list[CategoryMetrics]
    # Worst sibling pairs (sorted by max pairwise distance, descending)
    worst_siblings: list[SiblingPairResult]
    # Raw per-concept results (for CSV)
    all_siblings: list[SiblingPairResult] = field(default_factory=list)


def _percentile(values: Iterable[float], p: float) -> float:
    arr = np.asarray(list(values), dtype=np.float64)
    if arr.size == 0:
        return 0.0
    return float(np.percentile(arr, p))


def compute_metrics(
    config_name: str,
    rows: list[NormalizedRow],
    embedder: Embedder,
    seed: int = 42,
) -> ConfigMetrics:
    # Group by concept_id
    by_concept: dict[str, list[NormalizedRow]] = {}
    for row in rows:
        by_concept.setdefault(row.concept_id, []).append(row)
    for concept_rows in by_concept.values():
        concept_rows.sort(key=lambda r: r.phrasing_index)

    # Embed ALL normalized outputs in one batch for speed
    all_texts = [r.normalized for r in rows]
    all_vecs = embedder.embed(all_texts)
    text_to_vec: dict[int, np.ndarray] = {i: all_vecs[i] for i in range(len(rows))}
    row_index: dict[tuple[str, int], int] = {
        (r.concept_id, r.phrasing_index): i for i, r in enumerate(rows)
    }

    # Per-concept sibling distances
    sibling_results: list[SiblingPairResult] = []
    for concept_id, concept_rows in by_concept.items():
        if len(concept_rows) < 2:
            continue
        indices = [row_index[(concept_id, r.phrasing_index)] for r in concept_rows]
        vecs = np.stack([text_to_vec[i] for i in indices])
        pairwise = pairwise_cosine_distance(vecs)
        distances: list[float] = []
        n = len(concept_rows)
        for i, j in combinations(range(n), 2):
            distances.append(float(pairwise[i, j]))
        sibling_results.append(
            SiblingPairResult(
                concept_id=concept_id,
                category=concept_rows[0].category,
                distances=distances,
                max_distance=max(distances) if distances else 0.0,
                originals=[r.original for r in concept_rows],
                normalized=[r.normalized for r in concept_rows],
            )
        )

    # Flatten all pairwise sibling distances
    all_sibling_distances: list[float] = []
    for sr in sibling_results:
        all_sibling_distances.extend(sr.distances)

    hit_at_015 = sum(1 for d in all_sibling_distances if d <= PRODUCTION_THRESHOLD)
    hit_at_020 = sum(1 for d in all_sibling_distances if d <= TRUSTED_THRESHOLD)
    n_sibling_pairs = len(all_sibling_distances)

    mean_sibling = float(np.mean(all_sibling_distances)) if all_sibling_distances else 0.0
    median_sibling = float(np.median(all_sibling_distances)) if all_sibling_distances else 0.0
    p95_sibling = _percentile(all_sibling_distances, 95)
    max_sibling = max(all_sibling_distances) if all_sibling_distances else 0.0

    # Cross-concept false positive rate (sampled) — measured at both thresholds
    rng = random.Random(seed)
    cross_fp_015, cross_fp_020, n_cross = _compute_cross_fp(rows, text_to_vec, rng)

    # Latency
    latencies = [r.latency_ms for r in rows]
    mean_lat = float(np.mean(latencies)) if latencies else 0.0
    p95_lat = _percentile(latencies, 95)

    # Per-category breakdown
    by_cat: dict[str, list[SiblingPairResult]] = {}
    for sr in sibling_results:
        by_cat.setdefault(sr.category, []).append(sr)
    cat_metrics: list[CategoryMetrics] = []
    for cat, srs in sorted(by_cat.items()):
        cat_distances: list[float] = []
        for sr in srs:
            cat_distances.extend(sr.distances)
        if not cat_distances:
            continue
        cat_metrics.append(
            CategoryMetrics(
                category=cat,
                n_concepts=len(srs),
                mean_sibling_distance=float(np.mean(cat_distances)),
                p95_sibling_distance=_percentile(cat_distances, 95),
                hit_rate_at_015=sum(1 for d in cat_distances if d <= PRODUCTION_THRESHOLD)
                / len(cat_distances),
                hit_rate_at_020=sum(1 for d in cat_distances if d <= TRUSTED_THRESHOLD)
                / len(cat_distances),
            )
        )

    # Worst 20 siblings
    worst = sorted(sibling_results, key=lambda sr: sr.max_distance, reverse=True)[:20]

    return ConfigMetrics(
        config_name=config_name,
        n_concepts=len(sibling_results),
        n_prompts=len(rows),
        mean_sibling_distance=mean_sibling,
        median_sibling_distance=median_sibling,
        p95_sibling_distance=p95_sibling,
        max_sibling_distance=max_sibling,
        hit_rate_at_015=(hit_at_015 / n_sibling_pairs) if n_sibling_pairs else 0.0,
        hit_rate_at_020=(hit_at_020 / n_sibling_pairs) if n_sibling_pairs else 0.0,
        cross_fp_rate_at_015=cross_fp_015,
        cross_fp_rate_at_020=cross_fp_020,
        n_cross_pairs_sampled=n_cross,
        mean_latency_ms=mean_lat,
        p95_latency_ms=p95_lat,
        by_category=cat_metrics,
        worst_siblings=worst,
        all_siblings=sibling_results,
    )


def _compute_cross_fp(
    rows: list[NormalizedRow],
    text_to_vec: dict[int, np.ndarray],
    rng: random.Random,
) -> tuple[float, float, int]:
    """Sample random pairs of prompts from DIFFERENT concepts and measure
    what fraction fall under the production (0.15) and trusted (0.20) thresholds.

    Returns (fp_rate_at_015, fp_rate_at_020, n_sampled).
    """
    n = len(rows)
    if n < 2:
        return 0.0, 0.0, 0

    # Build list of (idx, concept_id) for sampling
    cross_pairs: list[tuple[int, int]] = []
    attempts = 0
    max_attempts = CROSS_SAMPLE_SIZE * 10
    while len(cross_pairs) < CROSS_SAMPLE_SIZE and attempts < max_attempts:
        i = rng.randrange(n)
        j = rng.randrange(n)
        attempts += 1
        if i == j:
            continue
        if rows[i].concept_id == rows[j].concept_id:
            continue
        cross_pairs.append((i, j))

    if not cross_pairs:
        return 0.0, 0.0, 0

    fp_015 = 0
    fp_020 = 0
    for i, j in cross_pairs:
        d = float(1.0 - np.dot(text_to_vec[i], text_to_vec[j]))
        if d <= PRODUCTION_THRESHOLD:
            fp_015 += 1
        if d <= TRUSTED_THRESHOLD:
            fp_020 += 1
    return fp_015 / len(cross_pairs), fp_020 / len(cross_pairs), len(cross_pairs)
