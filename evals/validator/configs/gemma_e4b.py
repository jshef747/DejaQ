"""Validator candidate: Gemma 4 E4B (`gemma4:e4b`), the local answering model.

Scores perfectly on the original 300-pair set and no better than granite on
`pairs_follow_up_fragment.json`, at the highest latency of the three. Kept as
a config because that contrast is the point: it is the case that proves one
corpus does not predict the other. Runs the production `ValidatorService`.
"""

CONFIG = {
    "name": "gemma_e4b",
    "enabled": True,
    "use_prefilter": False,
    "heuristic_only": False,
    "ollama_model": "gemma_local",
}
