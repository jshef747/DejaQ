# normalizer eval (evals/normalizer)

Standalone harness for evaluating DejaQ query normalizer configurations against a fixed dataset of semantically-equivalent prompt groups.

## Why this exists

The DejaQ semantic cache was missing on obviously-equivalent queries (e.g. three phrasings of "why is Russia at war with Ukraine?" produced three different normalized outputs, all missing the cache). Before changing production code in `../server/`, we iterate here on `(model, system_prompt, few_shots)` combinations and measure which config produces the most stable normalized output across semantically-equivalent inputs.

This folder is **completely independent** from `../server/` — no shared imports, no shared venv, no side effects on production code.

## Install

```bash
cd evals/normalizer

# Mac (Apple Silicon) - Metal GPU
CMAKE_ARGS="-DLLAMA_METAL=on" uv sync

# Windows (NVIDIA) - CUDA
$env:CMAKE_ARGS = "-DLLAMA_CUBLAS=on"; uv sync

# CPU only
uv sync
```

## Run

```bash
# Default: runs all enabled configs
uv run python -m harness.runner

# Run specific configs by name (comma-separated)
uv run python -m harness.runner --configs baseline_qwen_0_5b,v2_bag_qwen_0_5b

# Use a tiny dataset for smoke-testing
uv run python -m harness.runner --dataset dataset/prompts.json

# Re-generate metrics from cached inference outputs (no model re-run)
uv run python -m harness.runner --metrics-only
```

Reports are written to `reports/<timestamp>/report.md` and `report.csv`.

## Dataset format

`dataset/prompts.json`:

```json
{
  "concepts": [
    {
      "id": "concept_identifier",
      "category": "factual_qa",
      "phrasings": [
        "phrasing one",
        "phrasing two",
        "phrasing three"
      ]
    }
  ]
}
```

Each concept must have **exactly 3 phrasings**. Target: 100 concepts = 300 prompts total.

Recommended categories: `factual_qa`, `geopolitical`, `conceptual`, `technical_debug`, `code_gen`, `creative`, `opinion`, `definition`, `comparison`, `instruction`.

## Adding a new config

Create `configs/my_config.py` exporting a single `CONFIG` dict:

```python
CONFIG = {
    "name": "my_config",
    "description": "Short description of what this config tests",
    "enabled": True,
    "loader": {
        "repo_id": "Qwen/Qwen2.5-0.5B-Instruct-GGUF",
        "filename": "*q4_k_m.gguf",
        "n_ctx": 4096,
    },
    "inference": {
        "max_tokens": 64,
        "temperature": 0.0,
    },
    "system_prompt": "Your system prompt here.",
    "few_shots": [
        ("user input", "expected normalized output"),
    ],
}
```

Set `"enabled": False` to skip a config by default (useful for configs that require a large model download).

## Reading the report

The `report.md` contains:

1. **Headline comparison table** — one row per config with sibling hit rate @ 0.15, mean sibling cosine distance, cross-concept false-positive rate, p95 latency.
2. **Per-category breakdown** — same metrics grouped by category, so you can see which query types each config handles well.
3. **Worst sibling pairs** — the 20 concepts where siblings diverged the most. This is the main debugging view: it shows original phrasings, normalized outputs, and pairwise distances.

**Decision criterion:** pick the config with the highest sibling hit rate @ 0.15 AND a cross-concept false-positive rate below ~2%. That config is the one to promote into `../server/app/services/normalizer.py`.
