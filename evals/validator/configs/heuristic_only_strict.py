"""Validator config: heuristic rules only, strict mode.

AMBIGUOUS rows are treated as INVALID (conservative: reject anything uncertain).
Compare with heuristic_only (permissive) to bracket heuristic performance.
"""

CONFIG = {
    "name": "heuristic_only_strict",
    "enabled": True,
    "heuristic_only": True,
    "ambiguous_as": "INVALID",  # conservative: AMBIGUOUS → INVALID (max hallucination prevention)
}
