"""Validator config: heuristic rules only — no LLM.

AMBIGUOUS rows are treated as VALID (permissive mode) to measure recall floor.
Run alongside heuristic_only_strict to bracket heuristic performance.
"""

CONFIG = {
    "name": "heuristic_only",
    "enabled": True,
    "heuristic_only": True,
    "ambiguous_as": "VALID",  # permissive: AMBIGUOUS → VALID (max cache utilization)
}
