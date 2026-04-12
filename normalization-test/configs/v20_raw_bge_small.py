"""v20: raw passthrough + BAAI/bge-small-en-v1.5 embedder.

Hypothesis: the v18/v19 ceiling (~56%) may be the embedder, not the normalizer.
Both use sentence-transformers/all-MiniLM-L6-v2 (384-dim, weak).

BGE-small-en-v1.5 is also 384-dim but ranks ~8 points higher on MTEB paraphrase
and has no fine-tuning cost — just a different off-the-shelf checkpoint.

Run:
    cd normalization-test && uv run python -m harness.runner --configs v20_raw_bge_small
"""

CONFIG = {
    "name": "v20_raw_bge_small",
    "description": "Raw query (no normalizer) + BAAI/bge-small-en-v1.5 off-the-shelf embedder.",
    "enabled": True,
    "passthrough": True,
    "embedder_model_path": "BAAI/bge-small-en-v1.5",
    # Dummies for harness compatibility
    "loader": {},
    "inference": {},
    "system_prompt": "",
    "few_shots": [],
}
