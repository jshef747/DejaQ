"""v21: raw passthrough + BAAI/bge-base-en-v1.5 embedder.

Same hypothesis as v20 but with the 768-dim base variant — 2x dimensionality,
another ~3-5 MTEB points, ~5x inference latency on CPU (still <50ms/query).

Run:
    cd normalization-test && uv run python -m harness.runner --configs v21_raw_bge_base
"""

CONFIG = {
    "name": "v21_raw_bge_base",
    "description": "Raw query (no normalizer) + BAAI/bge-base-en-v1.5 off-the-shelf embedder (768-dim).",
    "enabled": True,
    "passthrough": True,
    "embedder_model_path": "BAAI/bge-base-en-v1.5",
    "loader": {},
    "inference": {},
    "system_prompt": "",
    "few_shots": [],
}
