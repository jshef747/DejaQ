"""Validator config: Gemma 4 E2B-Instruct. Alternative architecture sanity check."""

from configs.qwen_1_5b import SYSTEM_PROMPT, FEW_SHOTS

CONFIG = {
    "name": "gemma_e2b",
    "enabled": True,
    "use_prefilter": False,
    "heuristic_only": False,
    "loader": {
        "repo_id": "unsloth/gemma-4-E2B-it-GGUF",
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
