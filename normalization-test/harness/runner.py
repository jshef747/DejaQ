"""CLI entry point for the normalization test harness.

Usage:
    uv run python -m harness.runner
    uv run python -m harness.runner --configs baseline_qwen_0_5b,v2_bag_qwen_0_5b
    uv run python -m harness.runner --dataset dataset/prompts.json
    uv run python -m harness.runner --metrics-only
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
from llama_cpp.llama_grammar import LlamaGrammar

from harness.embedder import Embedder
from harness.metrics import NormalizedRow, compute_metrics
from harness.report import write_reports

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("harness.runner")

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASET = ROOT / "dataset" / "prompts.json"
REPORTS_DIR = ROOT / "reports"
CONFIGS_DIR = ROOT / "configs"


def discover_configs() -> list[str]:
    """Find all config modules in configs/ (excluding __init__)."""
    return sorted(
        p.stem for p in CONFIGS_DIR.glob("*.py") if p.stem != "__init__"
    )


def load_config(name: str) -> dict:
    module = importlib.import_module(f"configs.{name}")
    return module.CONFIG


def load_dataset(path: Path) -> list[dict]:
    with path.open() as f:
        data = json.load(f)
    concepts = data["concepts"]
    for c in concepts:
        if len(c["phrasings"]) != 3:
            raise ValueError(
                f"Concept '{c['id']}' has {len(c['phrasings'])} phrasings; expected exactly 3"
            )
    return concepts


def build_messages(system_prompt: str, few_shots: list[tuple[str, str]], query: str) -> list[dict]:
    """Mirror the chat-completion layout from server/app/services/normalizer.py."""
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    for user_input, assistant_output in few_shots:
        messages.append({"role": "user", "content": f"INPUT: {user_input}\nQUERY:"})
        messages.append({"role": "assistant", "content": assistant_output})
    messages.append({"role": "user", "content": f"INPUT: {query}\nQUERY:"})
    return messages


def postprocess(raw: str) -> str:
    """Sort content nouns alphabetically while keeping intent tag first."""
    parts = raw.strip().lower().split()
    if not parts:
        return ""
    intent = parts[0]
    content = sorted(parts[1:])
    return " ".join([intent] + content)


def run_config(config: dict, concepts: list[dict]) -> list[NormalizedRow]:
    passthrough = config.get("passthrough", False)
    custom_postprocess = config.get("postprocess_fn")  # callable(raw, original_query) -> str

    llm = None
    inference_kwargs = {}
    if not passthrough:
        logger.info("Loading model for config '%s' (%s)", config["name"], config["loader"]["repo_id"])
        llm = Llama.from_pretrained(verbose=False, **config["loader"])

        # Build grammar object once if config provides a GBNF string
        inference_kwargs = dict(config["inference"])
        grammar_str = config.get("grammar")
        if grammar_str:
            inference_kwargs["grammar"] = LlamaGrammar.from_string(grammar_str, verbose=False)
            logger.info("  [%s] grammar-constrained decoding enabled", config["name"])
    else:
        logger.info("Config '%s' is passthrough mode (no LLM)", config["name"])

    rows: list[NormalizedRow] = []
    total = sum(len(c["phrasings"]) for c in concepts)
    done = 0
    precondition_fn = config.get("precondition_fn")  # optional per-prompt LLM gate
    for concept in concepts:
        for idx, phrasing in enumerate(concept["phrasings"]):
            start = time.time()
            if passthrough or (precondition_fn and not precondition_fn(phrasing)):
                raw = phrasing
            else:
                messages = build_messages(config["system_prompt"], config["few_shots"], phrasing)
                output = llm.create_chat_completion(messages=messages, **inference_kwargs)
                raw = output["choices"][0]["message"]["content"].strip()
            latency_ms = (time.time() - start) * 1000
            if custom_postprocess:
                normalized = custom_postprocess(raw, phrasing)
            elif passthrough:
                normalized = raw  # raw query goes straight to the embedder
            else:
                normalized = postprocess(raw)
            rows.append(
                NormalizedRow(
                    concept_id=concept["id"],
                    category=concept["category"],
                    phrasing_index=idx,
                    original=phrasing,
                    normalized=normalized,
                    latency_ms=latency_ms,
                )
            )
            done += 1
            if done % 10 == 0 or done == total:
                logger.info("  [%s] %d/%d prompts", config["name"], done, total)

    # Free the model before loading the next one — llama.cpp holds GPU memory
    if llm is not None:
        del llm
    return rows


def save_raw(out_dir: Path, config_name: str, rows: list[NormalizedRow]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = [asdict(r) for r in rows]
    (out_dir / f"{config_name}_raw.json").write_text(json.dumps(payload, indent=2))


def load_raw(out_dir: Path, config_name: str) -> list[NormalizedRow] | None:
    path = out_dir / f"{config_name}_raw.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text())
    return [NormalizedRow(**row) for row in payload]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DejaQ normalizer test harness")
    parser.add_argument(
        "--configs",
        type=str,
        default=None,
        help="Comma-separated config names (default: all enabled configs)",
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET,
        help="Path to dataset JSON (default: dataset/prompts.json)",
    )
    parser.add_argument(
        "--metrics-only",
        action="store_true",
        help="Skip inference; recompute metrics from cached raw outputs in the latest run dir",
    )
    parser.add_argument(
        "--raw-from",
        type=Path,
        default=None,
        help="When used with --metrics-only, directory to read raw outputs from (default: latest report dir)",
    )
    return parser.parse_args()


def resolve_configs(requested: str | None) -> list[dict]:
    available = discover_configs()
    if requested:
        names = [n.strip() for n in requested.split(",") if n.strip()]
        unknown = [n for n in names if n not in available]
        if unknown:
            raise SystemExit(f"Unknown config(s): {unknown}. Available: {available}")
        configs = [load_config(n) for n in names]
    else:
        configs = [load_config(n) for n in available]
        configs = [c for c in configs if c.get("enabled", True)]
    if not configs:
        raise SystemExit("No configs to run. Enable at least one config or pass --configs.")
    return configs


def main() -> int:
    args = parse_args()
    configs = resolve_configs(args.configs)
    logger.info("Running %d config(s): %s", len(configs), [c["name"] for c in configs])

    concepts = load_dataset(args.dataset)
    logger.info("Loaded %d concepts (%d prompts) from %s", len(concepts), len(concepts) * 3, args.dataset)

    default_embedder = Embedder()
    embedder_cache: dict[str, Embedder] = {}

    def get_embedder(cfg: dict) -> Embedder:
        path = cfg.get("embedder_model_path")
        if not path:
            return default_embedder
        if path not in embedder_cache:
            logger.info("Loading custom embedder for '%s' from %s", cfg["name"], path)
            embedder_cache[path] = Embedder(model_path=path)
        return embedder_cache[path]

    if args.metrics_only:
        raw_dir = args.raw_from or _latest_report_dir()
        if raw_dir is None or not raw_dir.exists():
            logger.error("No raw output directory found for --metrics-only")
            return 1
        logger.info("Reading cached raw outputs from %s", raw_dir)
        run_dir = raw_dir
        results = []
        for cfg in configs:
            rows = load_raw(raw_dir, cfg["name"])
            if rows is None:
                logger.warning("No cached raw output for config '%s' — skipping", cfg["name"])
                continue
            results.append(compute_metrics(cfg["name"], rows, get_embedder(cfg)))
    else:
        timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        run_dir = REPORTS_DIR / timestamp
        run_dir.mkdir(parents=True, exist_ok=True)
        results = []
        for cfg in configs:
            rows = run_config(cfg, concepts)
            save_raw(run_dir, cfg["name"], rows)
            results.append(compute_metrics(cfg["name"], rows, get_embedder(cfg)))

    write_reports(run_dir, results)
    logger.info("Report written to %s", run_dir / "report.md")

    # Print headline to stdout for quick scanning
    print("\n=== Headline ===")
    for r in results:
        print(
            f"{r.config_name}: "
            f"hit@0.15={r.hit_rate_at_015 * 100:.1f}% "
            f"hit@0.20={r.hit_rate_at_020 * 100:.1f}% "
            f"fp@0.15={r.cross_fp_rate_at_015 * 100:.1f}% "
            f"fp@0.20={r.cross_fp_rate_at_020 * 100:.1f}% "
            f"mean_dist={r.mean_sibling_distance:.4f} "
            f"p95_lat={r.p95_latency_ms:.0f}ms"
        )
    return 0


def _latest_report_dir() -> Path | None:
    if not REPORTS_DIR.exists():
        return None
    dirs = [p for p in REPORTS_DIR.iterdir() if p.is_dir() and p.name != "__pycache__"]
    if not dirs:
        return None
    return max(dirs, key=lambda p: p.stat().st_mtime)


if __name__ == "__main__":
    sys.exit(main())
