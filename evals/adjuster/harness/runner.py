"""CLI entry point for the adjuster test harness.

Usage:
    uv run python -m harness.runner
    uv run python -m harness.runner --configs baseline_qwen_1_5b
    uv run python -m harness.runner --metrics-only
    uv run python -m harness.runner --metrics-only --raw-from reports/20240101-120000

Requires ANTHROPIC_API_KEY environment variable for LLM judge scoring.
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib
import json
import logging
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path

from llama_cpp import Llama

# Load .env from the project root if present
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

from harness.embedder import Embedder
from harness.judge import judge_batch
from harness.metrics import AdjustedRow, compute_metrics
from harness.report import write_reports

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("harness.runner")

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASET = ROOT / "dataset" / "scenarios.json"
REPORTS_DIR = ROOT / "reports"
CONFIGS_DIR = ROOT / "configs"


def discover_configs() -> list[str]:
    return sorted(p.stem for p in CONFIGS_DIR.glob("*.py") if p.stem != "__init__")


def load_config(name: str) -> dict:
    module = importlib.import_module(f"configs.{name}")
    return module.CONFIG


def load_dataset(path: Path) -> list[dict]:
    with path.open() as f:
        data = json.load(f)
    return data if isinstance(data, list) else data["scenarios"]


def build_messages(
    system_prompt: str,
    few_shots: list[tuple[str, str]],
    query: str,
    neutral_answer: str,
) -> list[dict]:
    """Build chat messages for the adjuster.

    few_shots: list of (user_content, assistant_content) pairs.
    """
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    for user_content, assistant_content in few_shots:
        messages.append({"role": "user", "content": user_content})
        messages.append({"role": "assistant", "content": assistant_content})
    messages.append({
        "role": "user",
        "content": f"QUESTION: {query}\nANSWER: {neutral_answer}",
    })
    return messages


def run_config(config: dict, scenarios: list[dict]) -> list[AdjustedRow]:
    logger.info("Loading model for config '%s' (%s)", config["name"], config["loader"]["repo_id"])
    llm = Llama.from_pretrained(verbose=False, **config["loader"])
    inference_kwargs = dict(config["inference"])

    rows: list[AdjustedRow] = []
    total = len(scenarios)
    done = 0

    for scenario in scenarios:
        start = time.time()

        messages = build_messages(
            config["system_prompt"],
            config["few_shots"],
            scenario["query"],
            scenario["neutral_answer"],
        )
        output = llm.create_chat_completion(messages=messages, **inference_kwargs)
        adjusted = output["choices"][0]["message"]["content"].strip()

        latency_ms = (time.time() - start) * 1000

        rows.append(AdjustedRow(
            scenario_id=scenario["id"],
            category=scenario["category"],
            query=scenario["query"],
            neutral_answer=scenario["neutral_answer"],
            expected_adjusted=scenario["expected_adjusted"],
            adjusted=adjusted,
            latency_ms=latency_ms,
        ))

        done += 1
        if done % 5 == 0 or done == total:
            logger.info("  [%s] %d/%d scenarios", config["name"], done, total)

    del llm
    return rows


def save_raw(out_dir: Path, config_name: str, rows: list[AdjustedRow]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = [asdict(r) for r in rows]
    (out_dir / f"{config_name}_raw.json").write_text(json.dumps(payload, indent=2))


def load_raw(out_dir: Path, config_name: str) -> list[AdjustedRow] | None:
    path = out_dir / f"{config_name}_raw.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text())
    return [AdjustedRow(**row) for row in payload]


def save_judge(out_dir: Path, config_name: str, results: list[dict]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{config_name}_judge.json").write_text(json.dumps(results, indent=2))


def load_judge(out_dir: Path, config_name: str) -> list[dict] | None:
    path = out_dir / f"{config_name}_judge.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DejaQ adjuster test harness")
    parser.add_argument("--configs", type=str, default=None,
                        help="Comma-separated config names (default: all enabled)")
    parser.add_argument("--dataset", type=Path, default=None,
                        help="Path to scenarios JSON file")
    parser.add_argument("--metrics-only", action="store_true",
                        help="Skip inference AND judge; recompute metrics from cached outputs")
    parser.add_argument("--raw-from", type=Path, default=None,
                        help="With --metrics-only: directory of cached outputs to read")
    parser.add_argument("--skip-judge", action="store_true",
                        help="Skip LLM judge scoring (use cached judge results if available)")
    return parser.parse_args()


def resolve_configs(requested: str | None) -> list[dict]:
    available = discover_configs()
    if requested:
        names = [n.strip() for n in requested.split(",") if n.strip()]
        unknown = [n for n in names if n not in available]
        if unknown:
            raise SystemExit(f"Unknown config(s): {unknown}. Available: {available}")
        return [load_config(n) for n in names]
    configs = [load_config(n) for n in available]
    return [c for c in configs if c.get("enabled", True)]


def _latest_report_dir() -> Path | None:
    if not REPORTS_DIR.exists():
        return None
    dirs = [p for p in REPORTS_DIR.iterdir() if p.is_dir() and p.name != "__pycache__"]
    if not dirs:
        return None
    return max(dirs, key=lambda p: p.stat().st_mtime)


def main() -> int:
    args = parse_args()
    configs = resolve_configs(args.configs)
    if not configs:
        raise SystemExit("No configs to run.")
    logger.info("Running %d config(s): %s", len(configs), [c["name"] for c in configs])

    dataset_path = args.dataset or DEFAULT_DATASET
    scenarios = load_dataset(dataset_path)
    logger.info("Loaded %d scenarios", len(scenarios))

    embedder = Embedder()

    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = REPORTS_DIR / timestamp

    if args.metrics_only:
        run_dir = args.raw_from or _latest_report_dir()
        if run_dir is None or not run_dir.exists():
            logger.error("No raw output directory for --metrics-only")
            return 1

    run_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for cfg in configs:
        # Step 1: Get raw inference results
        if args.metrics_only:
            rows = load_raw(run_dir, cfg["name"])
            if rows is None:
                logger.warning("No cached raw for config '%s' — skipping", cfg["name"])
                continue
        else:
            rows = run_config(cfg, scenarios)
            save_raw(run_dir, cfg["name"], rows)

        # Step 2: LLM judge scoring
        judge_results = None
        if args.metrics_only or args.skip_judge:
            judge_results = load_judge(run_dir, cfg["name"])
            if judge_results is not None:
                logger.info("Loaded cached judge results for '%s'", cfg["name"])

        if judge_results is None:
            logger.info("Running LLM judge for '%s' (%d scenarios)...", cfg["name"], len(rows))
            judge_results = judge_batch([
                {"query": r.query, "neutral_answer": r.neutral_answer, "adjusted": r.adjusted}
                for r in rows
            ])
            save_judge(run_dir, cfg["name"], judge_results)

        # Step 3: Compute metrics
        metrics = compute_metrics(cfg["name"], rows, embedder, judge_results)
        results.append(metrics)

    write_reports(run_dir, results)
    logger.info("Report: %s", run_dir / "report.md")

    # Print headline
    print("\n=== Headline ===")
    for r in results:
        print(
            f"  {r.config_name}: "
            f"tone={r.mean_tone_score:.2f}/5 "
            f"tone>=4: {r.pct_tone_gte_4 * 100:.1f}% "
            f"content={r.mean_content_score:.2f}/5 "
            f"embed_content@0.20={r.content_at_020 * 100:.1f}% "
            f"passthrough={r.passthrough_rate * 100:.1f}% "
            f"p95_lat={r.p95_latency_ms:.0f}ms"
        )

    print(f"\nReport: {run_dir}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
