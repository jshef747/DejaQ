"""Metric computation for enricher test runs.

For each (followup_input, expected_standalone, enriched_output) triple, we measure:

- Fidelity: cosine distance between embed(enriched) and embed(expected_standalone)
  - fidelity@0.15: % of rows where distance <= 0.15
  - fidelity@0.20: % of rows where distance <= 0.20
- Passthrough rate: for the 'passthrough' category, % where enriched ≈ input (distance < 0.05)
- Latency: mean and p95 per config
- Per-category breakdown

Thresholds mirror production (0.15 = SIMILARITY_THRESHOLD, 0.20 = TRUSTED_SIMILARITY).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import numpy as np

from harness.embedder import Embedder, cosine_distance

PRODUCTION_THRESHOLD = 0.15
TRUSTED_THRESHOLD = 0.20
PASSTHROUGH_THRESHOLD = 0.05  # enriched ≈ original for standalone queries


@dataclass
class EnrichedRow:
    scenario_id: str
    category: str
    phrasing_index: int
    followup_input: str
    expected_standalone: str
    enriched: str
    latency_ms: float


@dataclass
class WorstCase:
    scenario_id: str
    category: str
    followup_input: str
    expected_standalone: str
    enriched: str
    fidelity_distance: float


@dataclass
class CategoryMetrics:
    category: str
    n_rows: int
    mean_fidelity_distance: float
    p95_fidelity_distance: float
    fidelity_at_015: float
    fidelity_at_020: float
    passthrough_rate: float | None  # only set for 'passthrough' category


@dataclass
class ConfigMetrics:
    config_name: str
    n_scenarios: int
    n_rows: int
    # Fidelity (enriched vs expected_standalone)
    mean_fidelity_distance: float
    p95_fidelity_distance: float
    fidelity_at_015: float
    fidelity_at_020: float
    # Passthrough rate (passthrough category only)
    passthrough_rate: float
    n_passthrough_rows: int
    # Latency
    mean_latency_ms: float
    p95_latency_ms: float
    # Per-category
    by_category: list[CategoryMetrics]
    # Worst cases sorted by fidelity distance descending
    worst_cases: list[WorstCase] = field(default_factory=list)


def _percentile(values: Iterable[float], p: float) -> float:
    arr = np.asarray(list(values), dtype=np.float64)
    if arr.size == 0:
        return 0.0
    return float(np.percentile(arr, p))


def compute_metrics(
    config_name: str,
    rows: list[EnrichedRow],
    embedder: Embedder,
) -> ConfigMetrics:
    # Embed enriched outputs and expected standalones in one batch
    enriched_texts = [r.enriched for r in rows]
    expected_texts = [r.expected_standalone for r in rows]
    passthrough_inputs = [r.followup_input for r in rows if r.category == "passthrough"]

    all_texts = enriched_texts + expected_texts + passthrough_inputs
    all_vecs = embedder.embed(all_texts)

    n = len(rows)
    enriched_vecs = all_vecs[:n]
    expected_vecs = all_vecs[n : n * 2]

    passthrough_rows = [r for r in rows if r.category == "passthrough"]
    passthrough_input_vecs = all_vecs[n * 2 :]

    # Per-row fidelity distances
    fidelity_distances: list[float] = []
    for i in range(n):
        d = cosine_distance(enriched_vecs[i], expected_vecs[i])
        fidelity_distances.append(d)

    hit_015 = sum(1 for d in fidelity_distances if d <= PRODUCTION_THRESHOLD)
    hit_020 = sum(1 for d in fidelity_distances if d <= TRUSTED_THRESHOLD)

    mean_fid = float(np.mean(fidelity_distances)) if fidelity_distances else 0.0
    p95_fid = _percentile(fidelity_distances, 95)

    # Passthrough rate
    passthrough_hits = 0
    for i, row in enumerate(passthrough_rows):
        row_idx = rows.index(row)
        d_enriched_vs_input = cosine_distance(enriched_vecs[row_idx], passthrough_input_vecs[i])
        if d_enriched_vs_input <= PASSTHROUGH_THRESHOLD:
            passthrough_hits += 1
    passthrough_rate = (passthrough_hits / len(passthrough_rows)) if passthrough_rows else 0.0

    # Latency
    latencies = [r.latency_ms for r in rows]
    mean_lat = float(np.mean(latencies)) if latencies else 0.0
    p95_lat = _percentile(latencies, 95)

    # Per-category
    by_cat: dict[str, list[tuple[EnrichedRow, float]]] = {}
    for row, dist in zip(rows, fidelity_distances):
        by_cat.setdefault(row.category, []).append((row, dist))

    cat_metrics: list[CategoryMetrics] = []
    for cat, items in sorted(by_cat.items()):
        cat_dists = [d for _, d in items]
        cat_passthrough: float | None = None
        if cat == "passthrough":
            cat_passthrough = passthrough_rate
        cat_metrics.append(
            CategoryMetrics(
                category=cat,
                n_rows=len(items),
                mean_fidelity_distance=float(np.mean(cat_dists)),
                p95_fidelity_distance=_percentile(cat_dists, 95),
                fidelity_at_015=sum(1 for d in cat_dists if d <= PRODUCTION_THRESHOLD)
                / len(cat_dists),
                fidelity_at_020=sum(1 for d in cat_dists if d <= TRUSTED_THRESHOLD)
                / len(cat_dists),
                passthrough_rate=cat_passthrough,
            )
        )

    # Worst 20 cases by fidelity distance
    worst = sorted(
        [
            WorstCase(
                scenario_id=row.scenario_id,
                category=row.category,
                followup_input=row.followup_input,
                expected_standalone=row.expected_standalone,
                enriched=row.enriched,
                fidelity_distance=dist,
            )
            for row, dist in zip(rows, fidelity_distances)
        ],
        key=lambda w: w.fidelity_distance,
        reverse=True,
    )[:20]

    scenario_ids = {r.scenario_id for r in rows}

    return ConfigMetrics(
        config_name=config_name,
        n_scenarios=len(scenario_ids),
        n_rows=len(rows),
        mean_fidelity_distance=mean_fid,
        p95_fidelity_distance=p95_fid,
        fidelity_at_015=hit_015 / n if n else 0.0,
        fidelity_at_020=hit_020 / n if n else 0.0,
        passthrough_rate=passthrough_rate,
        n_passthrough_rows=len(passthrough_rows),
        mean_latency_ms=mean_lat,
        p95_latency_ms=p95_lat,
        by_category=cat_metrics,
        worst_cases=worst,
    )
