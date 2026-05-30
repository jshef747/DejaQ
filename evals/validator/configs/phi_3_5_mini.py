"""Validator config: Phi-3.5-Mini-Instruct (3.8B). Stronger reasoning, latency upper bound."""

from configs.qwen_1_5b import SYSTEM_PROMPT, FEW_SHOTS

CONFIG = {
    "name": "phi_3_5_mini",
    "enabled": True,
    "use_prefilter": False,
    "heuristic_only": False,
    "loader": {
        "repo_id": "bartowski/Phi-3.5-mini-instruct-GGUF",
        "filename": "*Q4_K_M.gguf",
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
