"""Report writers: markdown + CSV."""

from __future__ import annotations

import csv
from pathlib import Path

from harness.metrics import (
    ConfigMetrics,
    CONTENT_THRESHOLD_TIGHT,
    CONTENT_THRESHOLD_RELAXED,
    PASSTHROUGH_THRESHOLD,
)


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
    lines.append("# Context Adjuster Test Report\n")
    lines.append(
        f"Tone scoring: LLM judge (Haiku 4.5, 1-5 scale) · "
        f"Content embedding thresholds: tight={CONTENT_THRESHOLD_TIGHT} · relaxed={CONTENT_THRESHOLD_RELAXED} · "
        f"passthrough={PASSTHROUGH_THRESHOLD}\n"
    )

    # Headline table
    lines.append("## Headline comparison\n")
    lines.append(
        "| Config | N | Tone (avg) | Tone>=4 | Tone>=3 | "
        "Content (avg) | Content>=4 | "
        "Embed@0.20 | Embed@0.30 | Passthrough | Mean lat | P95 lat |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in results:
        lines.append(
            f"| {r.config_name} | {r.n_scenarios} | "
            f"{r.mean_tone_score:.2f} | {_fmt_pct(r.pct_tone_gte_4)} | {_fmt_pct(r.pct_tone_gte_3)} | "
            f"{r.mean_content_score:.2f} | {_fmt_pct(r.pct_content_gte_4)} | "
            f"{_fmt_pct(r.content_at_020)} | {_fmt_pct(r.content_at_030)} | {_fmt_pct(r.passthrough_rate)} | "
            f"{r.mean_latency_ms:.1f} | {r.p95_latency_ms:.1f} |"
        )
    lines.append("")

    # Per-config detail
    for r in results:
        lines.append(f"## {r.config_name}\n")

        if r.by_category:
            lines.append("### Per-category breakdown\n")
            lines.append(
                "| Category | N | Tone (avg) | Tone>=4 | Tone>=3 | "
                "Content (avg) | Content>=4 | Embed@0.20 | Passthrough |"
            )
            lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
            for cat in r.by_category:
                pt = _fmt_pct(cat.passthrough_rate) if cat.passthrough_rate is not None else "\u2014"
                lines.append(
                    f"| {cat.category} | {cat.n_rows} | "
                    f"{cat.mean_tone_score:.2f} | {_fmt_pct(cat.pct_tone_gte_4)} | {_fmt_pct(cat.pct_tone_gte_3)} | "
                    f"{cat.mean_content_score:.2f} | {_fmt_pct(cat.pct_content_gte_4)} | "
                    f"{_fmt_pct(cat.content_at_020)} | {pt} |"
                )
            lines.append("")

        if r.worst_tone:
            lines.append("### Worst tone scores (lowest first)\n")
            lines.append("| # | Scenario | Category | Tone | Content | Query | Adjusted | Reason |")
            lines.append("|---|---|---|---:|---:|---|---|---|")
            for i, wc in enumerate(r.worst_tone, 1):
                # Truncate long strings for readability
                query_short = wc.query[:60] + "..." if len(wc.query) > 60 else wc.query
                adjusted_short = wc.adjusted[:80] + "..." if len(wc.adjusted) > 80 else wc.adjusted
                lines.append(
                    f"| {i} | `{wc.scenario_id}` | {wc.category} | "
                    f"{wc.tone_score} | {wc.content_score} | "
                    f"{query_short} | {adjusted_short} | {wc.tone_reason} |"
                )
            lines.append("")

        if r.worst_content:
            lines.append("### Worst content scores (lowest first)\n")
            lines.append("| # | Scenario | Category | Content | Tone | Query | Adjusted | Reason |")
            lines.append("|---|---|---|---:|---:|---|---|---|")
            for i, wc in enumerate(r.worst_content, 1):
                query_short = wc.query[:60] + "..." if len(wc.query) > 60 else wc.query
                adjusted_short = wc.adjusted[:80] + "..." if len(wc.adjusted) > 80 else wc.adjusted
                lines.append(
                    f"| {i} | `{wc.scenario_id}` | {wc.category} | "
                    f"{wc.content_score} | {wc.tone_score} | "
                    f"{query_short} | {adjusted_short} | {wc.content_reason} |"
                )
            lines.append("")

    path.write_text("\n".join(lines))


def _write_csv(path: Path, results: list[ConfigMetrics]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "config", "scenario_id", "category",
            "tone_score", "content_score",
            "query", "adjusted",
            "tone_reason", "content_reason",
        ])
        for r in results:
            # Write all worst cases (tone + content deduplicated)
            seen = set()
            for wc in r.worst_tone + r.worst_content:
                if wc.scenario_id in seen:
                    continue
                seen.add(wc.scenario_id)
                writer.writerow([
                    r.config_name, wc.scenario_id, wc.category,
                    wc.tone_score, wc.content_score,
                    wc.query, wc.adjusted,
                    wc.tone_reason, wc.content_reason,
                ])
