"""Metric computation for adjuster test runs.

For each (query, neutral_answer, adjusted_output) triple, we measure:

- Tone score (1-5): LLM judge (Haiku 4.5) rates how well adjusted output matches query tone
- Content score (1-5): LLM judge rates how well facts are preserved
- Content preservation (embedding): cosine distance between embed(adjusted) and embed(neutral_answer)
  - content@0.20: % of rows where distance <= 0.20
  - content@0.30: % of rows where distance <= 0.30
- Passthrough rate: for 'neutral_passthrough' category, % where adjusted ≈ neutral (distance < 0.05)
- Latency: mean and p95 per config
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import numpy as np

from harness.embedder import Embedder, cosine_distance

CONTENT_THRESHOLD_TIGHT = 0.20
CONTENT_THRESHOLD_RELAXED = 0.30
PASSTHROUGH_THRESHOLD = 0.05


@dataclass
class AdjustedRow:
    scenario_id: str
    category: str
    query: str
    neutral_answer: str
    expected_adjusted: str
    adjusted: str
    latency_ms: float
    # LLM judge scores (filled during metrics computation)
    tone_score: int = 0
    content_score: int = 0
    tone_reason: str = ""
    content_reason: str = ""


@dataclass
class WorstCase:
    scenario_id: str
    category: str
    query: str
    neutral_answer: str
    adjusted: str
    tone_score: int
    content_score: int
    tone_reason: str
    content_reason: str


@dataclass
class CategoryMetrics:
    category: str
    n_rows: int
    # LLM judge tone (1-5)
    mean_tone_score: float
    pct_tone_gte_4: float  # % scoring 4 or 5
    pct_tone_gte_3: float  # % scoring 3, 4, or 5
    # LLM judge content (1-5)
    mean_content_score: float
    pct_content_gte_4: float
    # Embedding content preservation
    mean_content_distance: float
    content_at_020: float
    content_at_030: float
    # Passthrough (only for neutral_passthrough)
    passthrough_rate: float | None


@dataclass
class ConfigMetrics:
    config_name: str
    n_scenarios: int
    # LLM judge tone (1-5)
    mean_tone_score: float
    pct_tone_gte_4: float
    pct_tone_gte_3: float
    # LLM judge content (1-5)
    mean_content_score: float
    pct_content_gte_4: float
    # Embedding content preservation
    mean_content_distance: float
    p95_content_distance: float
    content_at_020: float
    content_at_030: float
    # Passthrough
    passthrough_rate: float
    n_passthrough_rows: int
    # Latency
    mean_latency_ms: float
    p95_latency_ms: float
    # Per-category
    by_category: list[CategoryMetrics]
    # Worst tone cases (lowest tone_score)
    worst_tone: list[WorstCase] = field(default_factory=list)
    # Worst content cases (lowest content_score)
    worst_content: list[WorstCase] = field(default_factory=list)


def _percentile(values: Iterable[float], p: float) -> float:
    arr = np.asarray(list(values), dtype=np.float64)
    if arr.size == 0:
        return 0.0
    return float(np.percentile(arr, p))


def compute_metrics(
    config_name: str,
    rows: list[AdjustedRow],
    embedder: Embedder,
    judge_results: list[dict],
) -> ConfigMetrics:
    n = len(rows)

    # Apply judge scores to rows
    for row, jr in zip(rows, judge_results):
        row.tone_score = jr.get("tone_score", 0)
        row.content_score = jr.get("content_score", 0)
        row.tone_reason = jr.get("tone_reason", "")
        row.content_reason = jr.get("content_reason", "")

    # Embedding-based content preservation
    adjusted_texts = [r.adjusted for r in rows]
    neutral_texts = [r.neutral_answer for r in rows]

    all_texts = adjusted_texts + neutral_texts
    all_vecs = embedder.embed(all_texts)

    adjusted_vecs = all_vecs[:n]
    neutral_vecs = all_vecs[n:]

    content_distances: list[float] = []
    for i in range(n):
        content_d = cosine_distance(adjusted_vecs[i], neutral_vecs[i])
        content_distances.append(content_d)

    # Aggregate LLM judge scores
    tone_scores = [r.tone_score for r in rows]
    content_scores = [r.content_score for r in rows]

    mean_tone = float(np.mean(tone_scores)) if tone_scores else 0.0
    pct_tone_gte_4 = (sum(1 for s in tone_scores if s >= 4) / n) if n else 0.0
    pct_tone_gte_3 = (sum(1 for s in tone_scores if s >= 3) / n) if n else 0.0

    mean_content_j = float(np.mean(content_scores)) if content_scores else 0.0
    pct_content_gte_4 = (sum(1 for s in content_scores if s >= 4) / n) if n else 0.0

    # Aggregate embedding content
    content_hit_020 = sum(1 for d in content_distances if d <= CONTENT_THRESHOLD_TIGHT)
    content_hit_030 = sum(1 for d in content_distances if d <= CONTENT_THRESHOLD_RELAXED)
    mean_content_d = float(np.mean(content_distances)) if content_distances else 0.0
    p95_content_d = _percentile(content_distances, 95)

    # Passthrough rate (neutral_passthrough category)
    passthrough_indices = [i for i, r in enumerate(rows) if r.category == "neutral_passthrough"]
    passthrough_hits = sum(1 for i in passthrough_indices if content_distances[i] <= PASSTHROUGH_THRESHOLD)
    passthrough_rate = (passthrough_hits / len(passthrough_indices)) if passthrough_indices else 0.0

    # Latency
    latencies = [r.latency_ms for r in rows]
    mean_lat = float(np.mean(latencies)) if latencies else 0.0
    p95_lat = _percentile(latencies, 95)

    # Per-category
    by_cat: dict[str, list[int]] = {}
    for i, row in enumerate(rows):
        by_cat.setdefault(row.category, []).append(i)

    cat_metrics: list[CategoryMetrics] = []
    for cat, indices in sorted(by_cat.items()):
        cat_n = len(indices)
        cat_tone = [tone_scores[i] for i in indices]
        cat_content_j = [content_scores[i] for i in indices]
        cat_content_d = [content_distances[i] for i in indices]

        cat_passthrough: float | None = None
        if cat == "neutral_passthrough":
            cat_passthrough = passthrough_rate

        cat_metrics.append(
            CategoryMetrics(
                category=cat,
                n_rows=cat_n,
                mean_tone_score=float(np.mean(cat_tone)),
                pct_tone_gte_4=(sum(1 for s in cat_tone if s >= 4) / cat_n),
                pct_tone_gte_3=(sum(1 for s in cat_tone if s >= 3) / cat_n),
                mean_content_score=float(np.mean(cat_content_j)),
                pct_content_gte_4=(sum(1 for s in cat_content_j if s >= 4) / cat_n),
                mean_content_distance=float(np.mean(cat_content_d)),
                content_at_020=sum(1 for d in cat_content_d if d <= CONTENT_THRESHOLD_TIGHT) / cat_n,
                content_at_030=sum(1 for d in cat_content_d if d <= CONTENT_THRESHOLD_RELAXED) / cat_n,
                passthrough_rate=cat_passthrough,
            )
        )

    # Worst 15 by tone score (ascending — worst first)
    worst_tone = sorted(
        [
            WorstCase(
                scenario_id=rows[i].scenario_id,
                category=rows[i].category,
                query=rows[i].query,
                neutral_answer=rows[i].neutral_answer,
                adjusted=rows[i].adjusted,
                tone_score=rows[i].tone_score,
                content_score=rows[i].content_score,
                tone_reason=rows[i].tone_reason,
                content_reason=rows[i].content_reason,
            )
            for i in range(n)
        ],
        key=lambda w: (w.tone_score, w.content_score),
    )[:15]

    # Worst 15 by content score (ascending)
    worst_content = sorted(
        [
            WorstCase(
                scenario_id=rows[i].scenario_id,
                category=rows[i].category,
                query=rows[i].query,
                neutral_answer=rows[i].neutral_answer,
                adjusted=rows[i].adjusted,
                tone_score=rows[i].tone_score,
                content_score=rows[i].content_score,
                tone_reason=rows[i].tone_reason,
                content_reason=rows[i].content_reason,
            )
            for i in range(n)
        ],
        key=lambda w: (w.content_score, w.tone_score),
    )[:15]

    return ConfigMetrics(
        config_name=config_name,
        n_scenarios=n,
        mean_tone_score=mean_tone,
        pct_tone_gte_4=pct_tone_gte_4,
        pct_tone_gte_3=pct_tone_gte_3,
        mean_content_score=mean_content_j,
        pct_content_gte_4=pct_content_gte_4,
        mean_content_distance=mean_content_d,
        p95_content_distance=p95_content_d,
        content_at_020=content_hit_020 / n if n else 0.0,
        content_at_030=content_hit_030 / n if n else 0.0,
        passthrough_rate=passthrough_rate,
        n_passthrough_rows=len(passthrough_indices),
        mean_latency_ms=mean_lat,
        p95_latency_ms=p95_lat,
        by_category=cat_metrics,
        worst_tone=worst_tone,
        worst_content=worst_content,
    )
