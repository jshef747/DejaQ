"""v0: raw passthrough — no normalizer, no LLM.

Baseline for option 3 of the normalizer investigation: feed the original query
directly into the embedder and measure how well ChromaDB's default embedding
model (all-MiniLM-L6-v2) can collapse sibling phrasings without any
preprocessing.

If this baseline beats v8/v10/v11 (~34–42% Hit@0.15), the normalizer is net
negative and DejaQ should embed raw queries instead.
"""

CONFIG = {
    "name": "v0_raw_passthrough",
    "description": "No normalizer — embed raw queries directly. Baseline for justifying the normalizer at all.",
    "enabled": False,
    "passthrough": True,
    # Dummy entries so the runner/metrics code that peeks at these doesn't break
    "loader": {},
    "inference": {},
    "system_prompt": "",
    "few_shots": [],
}
