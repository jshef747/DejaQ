"""Report writers: markdown + CSV."""

from __future__ import annotations

import csv
from pathlib import Path

from harness.metrics import ConfigMetrics, PRODUCTION_THRESHOLD, TRUSTED_THRESHOLD, PASSTHROUGH_THRESHOLD


def write_reports(out_dir: Path, results: list[ConfigMetrics]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_markdown(out_dir / "report.md", results)
    _write_csv(out_dir / "report.csv", results)


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _fmt_dist(x: float) -> str:
    return f"{x:.4f}"


def _write_markdown(path: Path, results: list[ConfigMetrics]) -> None:
    lines: list[str] = []
    lines.append("# Enricher Test Report\n")
    lines.append(
        f"Thresholds: fidelity production={PRODUCTION_THRESHOLD} · trusted={TRUSTED_THRESHOLD} · passthrough={PASSTHROUGH_THRESHOLD}\n"
    )

    # Headline table
    lines.append("## Headline comparison\n")
    lines.append(
        "| Config | Scenarios | Rows | Fidelity@0.15 | Fidelity@0.20 | Mean dist | P95 dist | Passthrough rate | Mean lat (ms) | P95 lat (ms) |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in results:
        lines.append(
            f"| {r.config_name} | {r.n_scenarios} | {r.n_rows} | "
            f"{_fmt_pct(r.fidelity_at_015)} | {_fmt_pct(r.fidelity_at_020)} | "
            f"{_fmt_dist(r.mean_fidelity_distance)} | {_fmt_dist(r.p95_fidelity_distance)} | "
            f"{_fmt_pct(r.passthrough_rate)} | "
            f"{r.mean_latency_ms:.1f} | {r.p95_latency_ms:.1f} |"
        )
    lines.append("")

    # Per-config detail
    for r in results:
        lines.append(f"## {r.config_name}\n")

        if r.by_category:
            lines.append("### Per-category breakdown\n")
            lines.append(
                "| Category | Rows | Fidelity@0.15 | Fidelity@0.20 | Mean dist | P95 dist | Passthrough rate |"
            )
            lines.append("|---|---:|---:|---:|---:|---:|---:|")
            for cat in r.by_category:
                pt = _fmt_pct(cat.passthrough_rate) if cat.passthrough_rate is not None else "—"
                lines.append(
                    f"| {cat.category} | {cat.n_rows} | "
                    f"{_fmt_pct(cat.fidelity_at_015)} | {_fmt_pct(cat.fidelity_at_020)} | "
                    f"{_fmt_dist(cat.mean_fidelity_distance)} | {_fmt_dist(cat.p95_fidelity_distance)} | "
                    f"{pt} |"
                )
            lines.append("")

        if r.worst_cases:
            lines.append("### Worst cases (top 20 by fidelity distance)\n")
            lines.append("| # | Scenario | Category | Follow-up input | Expected | Enriched | Distance |")
            lines.append("|---|---|---|---|---|---|---:|")
            for i, wc in enumerate(r.worst_cases, 1):
                lines.append(
                    f"| {i} | `{wc.scenario_id}` | {wc.category} | {wc.followup_input} | "
                    f"{wc.expected_standalone} | {wc.enriched} | {_fmt_dist(wc.fidelity_distance)} |"
                )
            lines.append("")

    path.write_text("\n".join(lines))


def _write_csv(path: Path, results: list[ConfigMetrics]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "config", "scenario_id", "category", "phrasing_index",
            "followup_input", "expected_standalone", "enriched", "fidelity_distance",
        ])
        for r in results:
            for wc in r.worst_cases:
                writer.writerow([
                    r.config_name, wc.scenario_id, wc.category, "",
                    wc.followup_input, wc.expected_standalone, wc.enriched,
                    f"{wc.fidelity_distance:.6f}",
                ])
