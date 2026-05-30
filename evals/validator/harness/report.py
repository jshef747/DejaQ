"""Report writers: markdown + CSV."""

from __future__ import annotations

import csv
from pathlib import Path

from harness.metrics import ConfigMetrics

ACCEPTANCE = {
    "precision_invalid": 0.95,
    "recall_invalid": 0.90,
    "false_reject_rate": 0.10,
    "unparseable_rate": 0.01,
    "p95_latency_ms": 300.0,
    "p50_latency_ms": 150.0,
}

DFST_RECALL_THRESHOLD = 0.95  # recall on different_fact_same_topic specifically


def write_reports(out_dir: Path, results: list[ConfigMetrics]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_markdown(out_dir / "report.md", results)
    _write_csv(out_dir / "results.csv", results)


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _f(x: float, decimals: int = 3) -> str:
    return f"{x:.{decimals}f}"


def _check(value: float, threshold: float, lower_is_better: bool = False) -> str:
    if lower_is_better:
        return "✓" if value <= threshold else "✗"
    return "✓" if value >= threshold else "✗"


def _write_markdown(path: Path, results: list[ConfigMetrics]) -> None:
    lines: list[str] = []
    lines.append("# Cache Validator Test Report\n")
    lines.append(
        "INVALID = positive class (hallucination trigger). "
        "Acceptance: precision≥0.95, recall≥0.90, false-reject≤0.10, "
        "unparseable≤1%, p95_lat≤300ms\n"
    )

    multi_dataset = len({r.dataset for r in results}) > 1

    # Headline table
    lines.append("## Headline comparison\n")
    if multi_dataset:
        lines.append(
            "| Dataset | Config | N | F1 | Precision | Recall | False-accept | False-reject | "
            "Unparseable | Prefilter% | p50ms | p95ms |"
        )
        lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for r in results:
            lines.append(
                f"| {r.dataset} | {r.config_name} | {r.n} | {_f(r.f1_invalid)} | "
                f"{_pct(r.precision_invalid)} | {_pct(r.recall_invalid)} | "
                f"{_pct(r.false_accept_rate)} | {_pct(r.false_reject_rate)} | "
                f"{_pct(r.unparseable_rate)} | {_pct(r.prefilter_resolved_pct)} | "
                f"{r.p50_latency_ms:.0f} | {r.p95_latency_ms:.0f} |"
            )
    else:
        lines.append(
            "| Config | N | F1 | Precision | Recall | False-accept | False-reject | "
            "Unparseable | Prefilter% | p50ms | p95ms |"
        )
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for r in results:
            lines.append(
                f"| {r.config_name} | {r.n} | {_f(r.f1_invalid)} | "
                f"{_pct(r.precision_invalid)} | {_pct(r.recall_invalid)} | "
                f"{_pct(r.false_accept_rate)} | {_pct(r.false_reject_rate)} | "
                f"{_pct(r.unparseable_rate)} | {_pct(r.prefilter_resolved_pct)} | "
                f"{r.p50_latency_ms:.0f} | {r.p95_latency_ms:.0f} |"
            )
    lines.append("")

    # Acceptance gate table
    lines.append("## Acceptance gate\n")
    if multi_dataset:
        lines.append("| Dataset | Config | prec≥0.95 | recall≥0.90 | dfst_recall≥0.95 | false-reject≤0.10 | unparseable≤0.01 | p50≤150ms | p95≤300ms | PASS? |")
        lines.append("|---|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|")
    else:
        lines.append("| Config | prec≥0.95 | recall≥0.90 | dfst_recall≥0.95 | false-reject≤0.10 | unparseable≤0.01 | p50≤150ms | p95≤300ms | PASS? |")
        lines.append("|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|")
    for r in results:
        dfst = next((c for c in r.by_category if c.category == "different_fact_same_topic"), None)
        dfst_recall = dfst.recall_invalid if dfst else 0.0
        checks = [
            _check(r.precision_invalid, 0.95),
            _check(r.recall_invalid, 0.90),
            _check(dfst_recall, DFST_RECALL_THRESHOLD),
            _check(r.false_reject_rate, 0.10, lower_is_better=True),
            _check(r.unparseable_rate, 0.01, lower_is_better=True),
            _check(r.p50_latency_ms, 150.0, lower_is_better=True),
            _check(r.p95_latency_ms, 300.0, lower_is_better=True),
        ]
        overall = "✓ PASS" if all(c == "✓" for c in checks) else "✗ FAIL"
        if multi_dataset:
            lines.append(f"| {r.dataset} | {r.config_name} | {' | '.join(checks)} | {overall} |")
        else:
            lines.append(f"| {r.config_name} | {' | '.join(checks)} | {overall} |")
    lines.append("")

    # Per-config detail
    for r in results:
        section_header = f"{r.dataset} / {r.config_name}" if multi_dataset else r.config_name
        lines.append(f"## {section_header}\n")
        lines.append(
            f"Confusion: TP={r.tp} FP={r.fp} TN={r.tn} FN={r.fn} "
            f"Unparseable={r.unparseable} Accuracy={_pct(r.accuracy)}\n"
        )

        if r.by_category:
            lines.append("### Per-category breakdown\n")
            lines.append("| Category | N | Precision | Recall | F1 | False-accept | False-reject |")
            lines.append("|---|---:|---:|---:|---:|---:|---:|")
            for cat in r.by_category:
                lines.append(
                    f"| {cat.category} | {cat.n} | {_pct(cat.precision_invalid)} | "
                    f"{_pct(cat.recall_invalid)} | {_f(cat.f1_invalid)} | "
                    f"{_pct(cat.false_accept_rate)} | {_pct(cat.false_reject_rate)} |"
                )
            lines.append("")

        if r.worst_cases:
            lines.append(f"### Misclassifications ({len(r.worst_cases)} rows)\n")
            lines.append("| # | ID | Category | Expected | Predicted | New Query | Cached Answer (trunc) | Raw Output |")
            lines.append("|---|---|---|---|---|---|---|---|")
            for i, wc in enumerate(r.worst_cases, 1):
                nq = (wc.new_query[:60] + "...") if len(wc.new_query) > 60 else wc.new_query
                ca = (wc.cached_answer[:60] + "...") if len(wc.cached_answer) > 60 else wc.cached_answer
                raw = (wc.raw_output[:30] + "...") if len(wc.raw_output) > 30 else wc.raw_output
                lines.append(
                    f"| {i} | `{wc.pair_id}` | {wc.category} | {wc.expected_verdict} | "
                    f"{wc.predicted_verdict} | {nq} | {ca} | `{raw}` |"
                )
            lines.append("")

    path.write_text("\n".join(lines))


def _write_csv(path: Path, results: list[ConfigMetrics]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "dataset", "config", "pair_id", "category",
            "expected_verdict", "predicted_verdict",
            "prefilter_verdict", "prefilter_reason",
            "new_query", "cached_query", "cached_answer",
            "raw_output", "latency_ms",
        ])
        for r in results:
            for row in r.worst_cases:
                writer.writerow([
                    r.dataset, r.config_name, row.pair_id, row.category,
                    row.expected_verdict, row.predicted_verdict,
                    row.prefilter_verdict, row.prefilter_reason,
                    row.new_query, row.cached_query, row.cached_answer,
                    row.raw_output, f"{row.latency_ms:.1f}",
                ])
