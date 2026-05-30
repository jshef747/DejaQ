"""CLI entry point for the cache validator test harness.

Usage:
    uv run python -m harness.runner
    uv run python -m harness.runner --configs qwen_1_5b,qwen_0_5b
    uv run python -m harness.runner --metrics-only
    uv run python -m harness.runner --metrics-only --raw-from reports/20240101-120000
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib
import json
import logging
import sys
import time
from dataclasses import asdict
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("harness.runner")

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASET = ROOT / "dataset" / "pairs.json"
DATASET_DIR = ROOT / "dataset"
REPORTS_DIR = ROOT / "reports"
CONFIGS_DIR = ROOT / "configs"


def discover_configs() -> list[str]:
    return sorted(p.stem for p in CONFIGS_DIR.glob("*.py") if p.stem != "__init__")


def discover_datasets() -> list[Path]:
    return sorted(DATASET_DIR.glob("pairs*.json"))


def load_config(name: str) -> dict:
    module = importlib.import_module(f"configs.{name}")
    return module.CONFIG


def load_dataset(path: Path) -> list[dict]:
    with path.open() as f:
        data = json.load(f)
    return data if isinstance(data, list) else data["pairs"]


def build_messages(
    system_prompt: str,
    few_shots: list[tuple[str, str]],
    cached_query: str,
    cached_answer: str,
    new_query: str,
) -> list[dict]:
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    for user_content, assistant_content in few_shots:
        messages.append({"role": "user", "content": user_content})
        messages.append({"role": "assistant", "content": assistant_content})
    messages.append({
        "role": "user",
        "content": (
            f"CACHED QUESTION: {cached_query}\n"
            f"CACHED ANSWER: {cached_answer}\n"
            f"NEW QUESTION: {new_query}"
        ),
    })
    return messages


def run_config(config: dict, pairs: list[dict]) -> list[dict]:
    from harness.parser import parse_verdict
    from harness import prefilter as pf_module

    uses_prefilter = config.get("use_prefilter", False)
    uses_heuristic_only = config.get("heuristic_only", False)

    llm = None
    if not uses_heuristic_only:
        logger.info("Loading model for config '%s' (%s)", config["name"], config["loader"]["repo_id"])
        from llama_cpp import Llama
        llm = Llama.from_pretrained(verbose=False, **config["loader"])

    inference_kwargs = dict(config.get("inference", {}))
    rows: list[dict] = []
    total = len(pairs)
    done = 0

    for pair in pairs:
        start = time.time()

        prefilter_verdict = ""
        prefilter_reason = ""
        predicted_verdict = ""
        raw_output = ""

        if uses_heuristic_only or uses_prefilter:
            prefilter_verdict, prefilter_reason = pf_module.apply(
                pair["cached_query"],
                pair["cached_answer"],
                pair["new_query"],
            )

        if uses_heuristic_only:
            # heuristic_only config: AMBIGUOUS treated per config setting
            ambiguous_default = config.get("ambiguous_as", "VALID")
            predicted_verdict = prefilter_verdict if prefilter_verdict != "AMBIGUOUS" else ambiguous_default
            raw_output = f"prefilter:{prefilter_verdict}"
        elif uses_prefilter and prefilter_verdict in ("VALID", "INVALID"):
            predicted_verdict = prefilter_verdict
            raw_output = f"prefilter:{prefilter_verdict}"
        else:
            # Run LLM
            messages = build_messages(
                config["system_prompt"],
                config["few_shots"],
                pair["cached_query"],
                pair["cached_answer"],
                pair["new_query"],
            )
            output = llm.create_chat_completion(messages=messages, **inference_kwargs)
            raw_output = output["choices"][0]["message"]["content"].strip()
            predicted_verdict, _ = parse_verdict(raw_output)

        latency_ms = (time.time() - start) * 1000

        rows.append({
            "pair_id": pair["id"],
            "category": pair["category"],
            "cached_query": pair["cached_query"],
            "cached_answer": pair["cached_answer"],
            "new_query": pair["new_query"],
            "expected_verdict": pair["expected_verdict"],
            "predicted_verdict": predicted_verdict,
            "raw_output": raw_output,
            "latency_ms": latency_ms,
            "prefilter_verdict": prefilter_verdict,
            "prefilter_reason": prefilter_reason,
        })

        done += 1
        if done % 10 == 0 or done == total:
            logger.info("  [%s] %d/%d pairs", config["name"], done, total)

    if llm is not None:
        del llm
    return rows


def save_raw(out_dir: Path, config_name: str, rows: list[dict]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{config_name}_raw.json").write_text(json.dumps(rows, indent=2))


def load_raw(out_dir: Path, config_name: str) -> list[dict] | None:
    path = out_dir / f"{config_name}_raw.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DejaQ cache validator test harness")
    parser.add_argument("--configs", type=str, default=None,
                        help="Comma-separated config names (default: all enabled)")
    parser.add_argument("--dataset", type=Path, default=None,
                        help="Path to pairs JSON file")
    parser.add_argument("--all-datasets", action="store_true",
                        help="Run against all dataset/pairs*.json files")
    parser.add_argument("--metrics-only", action="store_true",
                        help="Recompute metrics from cached raw outputs")
    parser.add_argument("--raw-from", type=Path, default=None,
                        help="With --metrics-only: directory of cached outputs to read")
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
    from harness.metrics import ValidatorRow, compute_metrics
    from harness.report import write_reports

    args = parse_args()
    configs = resolve_configs(args.configs)
    if not configs:
        raise SystemExit("No configs to run.")
    logger.info("Running %d config(s): %s", len(configs), [c["name"] for c in configs])

    # Determine which datasets to use
    if args.all_datasets:
        dataset_paths = discover_datasets()
        if not dataset_paths:
            raise SystemExit("No dataset/pairs*.json files found.")
        logger.info("Using %d datasets: %s", len(dataset_paths), [p.stem for p in dataset_paths])
    else:
        dataset_paths = [args.dataset or DEFAULT_DATASET]

    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = REPORTS_DIR / timestamp

    if args.metrics_only:
        run_dir = args.raw_from or _latest_report_dir()
        if run_dir is None or not run_dir.exists():
            logger.error("No raw output directory for --metrics-only")
            return 1

    run_dir.mkdir(parents=True, exist_ok=True)

    all_metrics: list = []

    for dataset_path in dataset_paths:
        dataset_name = dataset_path.stem  # e.g. "pairs", "pairs_science"
        pairs = load_dataset(dataset_path)
        logger.info("[%s] Loaded %d pairs", dataset_name, len(pairs))

        for cfg in configs:
            raw_key = f"{dataset_name}_{cfg['name']}"
            if args.metrics_only:
                raw_rows = load_raw(run_dir, raw_key)
                if raw_rows is None:
                    logger.warning("No cached raw for '%s' — skipping", raw_key)
                    continue
            else:
                raw_rows = run_config(cfg, pairs)
                save_raw(run_dir, raw_key, raw_rows)

            validator_rows = [ValidatorRow(**r) for r in raw_rows]
            metrics = compute_metrics(cfg["name"], validator_rows, dataset=dataset_name)
            all_metrics.append(metrics)

    write_reports(run_dir, all_metrics)
    logger.info("Report: %s", run_dir / "report.md")

    print("\n=== Headline ===")
    for r in all_metrics:
        print(
            f"  [{r.dataset}] {r.config_name}: "
            f"F1={r.f1_invalid:.3f} "
            f"prec={r.precision_invalid * 100:.1f}% "
            f"recall={r.recall_invalid * 100:.1f}% "
            f"false-accept={r.false_accept_rate * 100:.1f}% "
            f"false-reject={r.false_reject_rate * 100:.1f}% "
            f"p95={r.p95_latency_ms:.0f}ms"
        )
    print(f"\nReport: {run_dir}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
