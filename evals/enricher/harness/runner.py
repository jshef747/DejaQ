"""CLI entry point for the enricher test harness.

Usage:
    uv run python -m harness.runner
    uv run python -m harness.runner --configs baseline_qwen_0_5b
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

from llama_cpp import Llama

from harness.embedder import Embedder
from harness.metrics import EnrichedRow, compute_metrics
from harness.report import write_reports

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("harness.runner")

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASET = ROOT / "dataset" / "conversations.json"
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
    scenarios = data["scenarios"]
    for s in scenarios:
        if len(s["followups"]) != 3:
            raise ValueError(
                f"Scenario '{s['id']}' has {len(s['followups'])} followups; expected exactly 3"
            )
    return scenarios


def format_history(history: list[dict]) -> str:
    lines = []
    for msg in history:
        role = "User" if msg["role"] == "user" else "Assistant"
        lines.append(f"{role}: {msg['content']}")
    return "\n".join(lines)


def build_messages(
    system_prompt: str,
    few_shots: list[tuple[str, str, str]],
    history: list[dict],
    followup: str,
) -> list[dict]:
    """Build chat messages for the enricher.

    few_shots: list of (history_str, followup_input, expected_output)
    """
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    for history_str, shot_followup, shot_output in few_shots:
        messages.append({
            "role": "user",
            "content": f"HISTORY:\n{history_str}\n\nFOLLOW-UP: {shot_followup}",
        })
        messages.append({"role": "assistant", "content": shot_output})
    history_str = format_history(history)
    messages.append({
        "role": "user",
        "content": f"HISTORY:\n{history_str}\n\nFOLLOW-UP: {followup}",
    })
    return messages


def run_config(config: dict, scenarios: list[dict]) -> list[EnrichedRow]:
    passthrough = config.get("passthrough", False)
    precondition_fn = config.get("precondition_fn")  # optional gate: (followup) -> bool (needs enrichment)

    llm = None
    inference_kwargs = {}
    if not passthrough:
        logger.info("Loading model for config '%s' (%s)", config["name"], config["loader"]["repo_id"])
        llm = Llama.from_pretrained(verbose=False, **config["loader"])
        inference_kwargs = dict(config["inference"])
    else:
        logger.info("Config '%s' is passthrough mode (no LLM)", config["name"])

    rows: list[EnrichedRow] = []
    total = sum(len(s["followups"]) for s in scenarios)
    done = 0

    for scenario in scenarios:
        history = scenario["history"]
        for idx, followup_obj in enumerate(scenario["followups"]):
            followup_input = followup_obj["input"]
            expected = followup_obj["expected"]

            start = time.time()

            if passthrough or (precondition_fn and not precondition_fn(followup_input)):
                # No LLM — return input as-is
                enriched = followup_input
            else:
                messages = build_messages(
                    config["system_prompt"],
                    config["few_shots"],
                    history,
                    followup_input,
                )
                output = llm.create_chat_completion(messages=messages, **inference_kwargs)
                enriched = output["choices"][0]["message"]["content"].strip()

            latency_ms = (time.time() - start) * 1000

            rows.append(EnrichedRow(
                scenario_id=scenario["id"],
                category=scenario["category"],
                phrasing_index=idx,
                followup_input=followup_input,
                expected_standalone=expected,
                enriched=enriched,
                latency_ms=latency_ms,
            ))

            done += 1
            if done % 10 == 0 or done == total:
                logger.info("  [%s] %d/%d rows", config["name"], done, total)

    if llm is not None:
        del llm
    return rows


def save_raw(out_dir: Path, config_name: str, rows: list[EnrichedRow]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = [asdict(r) for r in rows]
    (out_dir / f"{config_name}_raw.json").write_text(json.dumps(payload, indent=2))


def load_raw(out_dir: Path, config_name: str) -> list[EnrichedRow] | None:
    path = out_dir / f"{config_name}_raw.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text())
    return [EnrichedRow(**row) for row in payload]


def discover_datasets() -> list[Path]:
    """Find all conversations*.json files in the dataset directory."""
    return sorted((ROOT / "dataset").glob("conversations*.json"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DejaQ enricher test harness")
    parser.add_argument("--configs", type=str, default=None,
                        help="Comma-separated config names (default: all enabled)")
    dataset_group = parser.add_mutually_exclusive_group()
    dataset_group.add_argument("--dataset", type=Path, default=None,
                        help="Path to a single conversations JSON file")
    dataset_group.add_argument("--all-datasets", action="store_true",
                        help="Run against all dataset/conversations*.json files")
    parser.add_argument("--metrics-only", action="store_true",
                        help="Skip inference; recompute metrics from cached raw outputs")
    parser.add_argument("--raw-from", type=Path, default=None,
                        help="With --metrics-only: directory of raw outputs to read")
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

    # Resolve which datasets to run
    if args.all_datasets:
        dataset_paths = discover_datasets()
        if not dataset_paths:
            raise SystemExit("No dataset/conversations*.json files found.")
        logger.info("Running against %d datasets: %s", len(dataset_paths), [p.name for p in dataset_paths])
    else:
        dataset_paths = [args.dataset or DEFAULT_DATASET]

    default_embedder = Embedder()
    embedder_cache: dict[str, Embedder] = {}

    def get_embedder(cfg: dict) -> Embedder:
        path = cfg.get("embedder_model_path")
        if not path:
            return default_embedder
        if path not in embedder_cache:
            embedder_cache[path] = Embedder(model_path=path)
        return embedder_cache[path]

    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = REPORTS_DIR / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)

    # Collect all results across all datasets for final summary
    all_headline: list[tuple[str, str, object]] = []  # (dataset_name, config_name, metrics)

    for dataset_path in dataset_paths:
        dataset_name = dataset_path.stem  # e.g. "conversations_coding"
        logger.info("=== Dataset: %s ===", dataset_name)

        if args.metrics_only:
            raw_dir = args.raw_from or _latest_report_dir()
            if raw_dir is None or not raw_dir.exists():
                logger.error("No raw output directory for --metrics-only")
                return 1
            ds_run_dir = raw_dir / dataset_name if args.all_datasets else raw_dir
        else:
            ds_run_dir = run_dir / dataset_name if len(dataset_paths) > 1 else run_dir
            ds_run_dir.mkdir(parents=True, exist_ok=True)

        scenarios = load_dataset(dataset_path)
        logger.info("  Loaded %d scenarios (%d rows)", len(scenarios), len(scenarios) * 3)

        results = []
        for cfg in configs:
            if args.metrics_only:
                rows = load_raw(ds_run_dir, cfg["name"])
                if rows is None:
                    logger.warning("No cached raw for config '%s' in %s — skipping", cfg["name"], dataset_name)
                    continue
            else:
                rows = run_config(cfg, scenarios)
                save_raw(ds_run_dir, cfg["name"], rows)
            metrics = compute_metrics(cfg["name"], rows, get_embedder(cfg))
            results.append(metrics)
            all_headline.append((dataset_name, cfg["name"], metrics))

        write_reports(ds_run_dir, results)
        logger.info("  Report: %s", ds_run_dir / "report.md")

    # Print combined headline
    print("\n=== Headline ===")
    current_ds = None
    for dataset_name, config_name, r in all_headline:
        if dataset_name != current_ds:
            print(f"\n[{dataset_name}]")
            current_ds = dataset_name
        print(
            f"  {config_name}: "
            f"fidelity@0.15={r.fidelity_at_015 * 100:.1f}% "
            f"fidelity@0.20={r.fidelity_at_020 * 100:.1f}% "
            f"passthrough={r.passthrough_rate * 100:.1f}% "
            f"mean_dist={r.mean_fidelity_distance:.4f} "
            f"p95_lat={r.p95_latency_ms:.0f}ms"
        )

    if len(dataset_paths) > 1:
        print(f"\nAll reports in: {run_dir}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
