"""Validator config: Qwen 2.5-1.5B + heuristic prefilter.

Heuristic runs first (free). If it fires VALID or INVALID, return that result
without calling the LLM. Only AMBIGUOUS cases go to Qwen 1.5B.
This is the PRIMARY production candidate.
"""

from configs.qwen_1_5b import SYSTEM_PROMPT, FEW_SHOTS

CONFIG = {
    "name": "qwen_1_5b_prefilter",
    "enabled": True,
    "use_prefilter": True,
    "heuristic_only": False,
    "loader": {
        "repo_id": "Qwen/Qwen2.5-1.5B-Instruct-GGUF",
        "filename": "*q4_k_m.gguf",
        "n_ctx": 2048,
    },
    "inference": {
        "max_tokens": 8,
        "temperature": 0.0,
        "top_p": 1.0,
        "stop": ["\n", "REASON", " "],
    },
    "system_prompt": SYSTEM_PROMPT,
    "few_shots": FEW_SHOTS,
}
