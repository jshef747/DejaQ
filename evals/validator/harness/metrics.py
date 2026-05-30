"""Metric computation for validator test runs.

INVALID is the positive class (we are detecting hallucination-causing cache misuses).

Primary:
  precision_invalid = TP / (TP + FP)
  recall_invalid    = TP / (TP + FN)
  f1_invalid        = harmonic mean

Secondary:
  false_accept_rate  = FN / (TP + FN)   (complement of recall_invalid)
  false_reject_rate  = FP / (TN + FP)   (VALID classified as INVALID)
  unparseable_rate   = unparseable / total
  accuracy           = (TP + TN) / total
  prefilter_resolved_pct = rows decided by heuristic without LLM
  mean/p50/p95 latency_ms
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import numpy as np


@dataclass
class ValidatorRow:
    pair_id: str
    category: str
    cached_query: str
    cached_answer: str
    new_query: str
    expected_verdict: str       # "VALID" or "INVALID"
    predicted_verdict: str      # "VALID", "INVALID", or "UNPARSEABLE"
    raw_output: str
    latency_ms: float
    prefilter_verdict: str = ""  # "VALID", "INVALID", "AMBIGUOUS", or "" if not used
    prefilter_reason: str = ""


@dataclass
class CategoryMetrics:
    category: str
    n: int
    precision_invalid: float
    recall_invalid: float
    f1_invalid: float
    false_accept_rate: float
    false_reject_rate: float
    tp: int
    fp: int
    tn: int
    fn: int


@dataclass
class ConfigMetrics:
    config_name: str
    dataset: str
    n: int
    # Primary
    precision_invalid: float
    recall_invalid: float
    f1_invalid: float
    # Secondary
    false_accept_rate: float
    false_reject_rate: float
    accuracy: float
    unparseable_rate: float
    # Prefilter
    prefilter_resolved_pct: float
    # Confusion matrix
    tp: int
    fp: int
    tn: int
    fn: int
    unparseable: int
    # Latency
    mean_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    # Per-category
    by_category: list[CategoryMetrics]
    # Worst misclassifications (FP + FN)
    worst_cases: list[ValidatorRow] = field(default_factory=list)


def _percentile(values: Iterable[float], p: float) -> float:
    arr = np.asarray(list(values), dtype=np.float64)
    if arr.size == 0:
        return 0.0
    return float(np.percentile(arr, p))


def _confusion(rows: list[ValidatorRow]) -> tuple[int, int, int, int, int]:
    """Return (tp, fp, tn, fn, unparseable)."""
    tp = fp = tn = fn = unparseable = 0
    for r in rows:
        pred = r.predicted_verdict
        if pred == "UNPARSEABLE":
            # Counted as INVALID (fail-safe) for confusion matrix
            pred = "INVALID"
            unparseable += 1
        expected = r.expected_verdict
        if expected == "INVALID" and pred == "INVALID":
            tp += 1
        elif expected == "VALID" and pred == "INVALID":
            fp += 1
        elif expected == "VALID" and pred == "VALID":
            tn += 1
        elif expected == "INVALID" and pred == "VALID":
            fn += 1
    return tp, fp, tn, fn, unparseable


def _safe_div(a: int, b: int) -> float:
    return a / b if b else 0.0


def _cat_metrics(category: str, rows: list[ValidatorRow]) -> CategoryMetrics:
    tp, fp, tn, fn, _ = _confusion(rows)
    n = len(rows)
    precision = _safe_div(tp, tp + fp)
    recall = _safe_div(tp, tp + fn)
    f1 = _safe_div(2 * precision * recall, precision + recall)
    false_accept = _safe_div(fn, tp + fn)
    false_reject = _safe_div(fp, tn + fp)
    return CategoryMetrics(
        category=category,
        n=n,
        precision_invalid=precision,
        recall_invalid=recall,
        f1_invalid=f1,
        false_accept_rate=false_accept,
        false_reject_rate=false_reject,
        tp=tp, fp=fp, tn=tn, fn=fn,
    )


def compute_metrics(config_name: str, rows: list[ValidatorRow], dataset: str = "main") -> ConfigMetrics:
    n = len(rows)
    tp, fp, tn, fn, unparseable = _confusion(rows)

    precision = _safe_div(tp, tp + fp)
    recall = _safe_div(tp, tp + fn)
    f1 = _safe_div(2 * precision * recall, precision + recall)
    false_accept = _safe_div(fn, tp + fn)
    false_reject = _safe_div(fp, tn + fp)
    accuracy = _safe_div(tp + tn, n)
    unparseable_rate = _safe_div(unparseable, n)

    prefilter_resolved = sum(
        1 for r in rows
        if r.prefilter_verdict in ("VALID", "INVALID")
    )
    prefilter_resolved_pct = _safe_div(prefilter_resolved, n)

    latencies = [r.latency_ms for r in rows]
    mean_lat = float(np.mean(latencies)) if latencies else 0.0
    p50_lat = _percentile(latencies, 50)
    p95_lat = _percentile(latencies, 95)

    by_cat: dict[str, list[ValidatorRow]] = {}
    for r in rows:
        by_cat.setdefault(r.category, []).append(r)

    cat_metrics = [
        _cat_metrics(cat, cat_rows)
        for cat, cat_rows in sorted(by_cat.items())
    ]

    # Worst cases: all FP and FN rows, sorted by category then id
    misclassified = [
        r for r in rows
        if (r.expected_verdict == "INVALID" and r.predicted_verdict in ("VALID", "UNPARSEABLE"))
        or (r.expected_verdict == "VALID" and r.predicted_verdict == "INVALID")
    ]
    misclassified.sort(key=lambda r: (r.category, r.pair_id))

    return ConfigMetrics(
        config_name=config_name,
        dataset=dataset,
        n=n,
        precision_invalid=precision,
        recall_invalid=recall,
        f1_invalid=f1,
        false_accept_rate=false_accept,
        false_reject_rate=false_reject,
        accuracy=accuracy,
        unparseable_rate=unparseable_rate,
        prefilter_resolved_pct=prefilter_resolved_pct,
        tp=tp, fp=fp, tn=tn, fn=fn, unparseable=unparseable,
        mean_latency_ms=mean_lat,
        p50_latency_ms=p50_lat,
        p95_latency_ms=p95_lat,
        by_category=cat_metrics,
        worst_cases=misclassified,
    )
