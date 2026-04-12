"""Report writers: markdown + CSV."""

from __future__ import annotations

import csv
from pathlib import Path

from harness.metrics import ConfigMetrics, PRODUCTION_THRESHOLD, TRUSTED_THRESHOLD


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
    lines.append("# Normalization Test Report\n")
    lines.append(
        f"Thresholds: production={PRODUCTION_THRESHOLD} · trusted={TRUSTED_THRESHOLD}\n"
    )

    # Headline table
    lines.append("## Headline comparison\n")
    lines.append(
        "| Config | Concepts | Prompts | Hit@0.15 | Hit@0.20 | Mean dist | P95 dist | Cross FP@0.15 | Cross FP@0.20 | Mean lat (ms) | P95 lat (ms) |"
    )
    lines.append(
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
    )
    for r in results:
        lines.append(
            f"| {r.config_name} | {r.n_concepts} | {r.n_prompts} | "
            f"{_fmt_pct(r.hit_rate_at_015)} | {_fmt_pct(r.hit_rate_at_020)} | "
            f"{_fmt_dist(r.mean_sibling_distance)} | {_fmt_dist(r.p95_sibling_distance)} | "
            f"{_fmt_pct(r.cross_fp_rate_at_015)} | {_fmt_pct(r.cross_fp_rate_at_020)} | "
            f"{r.mean_latency_ms:.1f} | {r.p95_latency_ms:.1f} |"
        )
    lines.append("")

    # Per-config detail sections
    for r in results:
        lines.append(f"## {r.config_name}\n")

        if r.by_category:
            lines.append("### Per-category breakdown\n")
            lines.append(
                "| Category | Concepts | Hit@0.15 | Hit@0.20 | Mean dist | P95 dist |"
            )
            lines.append("|---|---:|---:|---:|---:|---:|")
            for cat in r.by_category:
                lines.append(
                    f"| {cat.category} | {cat.n_concepts} | "
                    f"{_fmt_pct(cat.hit_rate_at_015)} | {_fmt_pct(cat.hit_rate_at_020)} | "
                    f"{_fmt_dist(cat.mean_sibling_distance)} | {_fmt_dist(cat.p95_sibling_distance)} |"
                )
            lines.append("")

        if r.worst_siblings:
            lines.append("### Worst sibling pairs (top 20 by max pairwise distance)\n")
            for i, sr in enumerate(r.worst_siblings, 1):
                lines.append(
                    f"**{i}. `{sr.concept_id}`** (category: {sr.category}, "
                    f"max distance: {_fmt_dist(sr.max_distance)})"
                )
                lines.append("")
                lines.append("| # | Original | Normalized |")
                lines.append("|---|---|---|")
                for idx, (orig, norm) in enumerate(zip(sr.originals, sr.normalized)):
                    lines.append(f"| {idx} | {orig} | `{norm}` |")
                lines.append("")
                lines.append("Pairwise distances: " + ", ".join(_fmt_dist(d) for d in sr.distances))
                lines.append("")

    path.write_text("\n".join(lines))


def _write_csv(path: Path, results: list[ConfigMetrics]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "config",
                "concept_id",
                "category",
                "original_0",
                "original_1",
                "original_2",
                "normalized_0",
                "normalized_1",
                "normalized_2",
                "dist_0_1",
                "dist_0_2",
                "dist_1_2",
                "max_distance",
            ]
        )
        for r in results:
            for sr in r.all_siblings:
                originals = sr.originals + [""] * (3 - len(sr.originals))
                normalized = sr.normalized + [""] * (3 - len(sr.normalized))
                dists = sr.distances + [0.0] * (3 - len(sr.distances))
                writer.writerow(
                    [
                        r.config_name,
                        sr.concept_id,
                        sr.category,
                        *originals[:3],
                        *normalized[:3],
                        *(f"{d:.6f}" for d in dists[:3]),
                        f"{sr.max_distance:.6f}",
                    ]
                )
