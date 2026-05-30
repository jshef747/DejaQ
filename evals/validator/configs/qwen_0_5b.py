"""Validator config: Qwen 2.5-0.5B-Instruct. Sanity floor — fastest local model."""

from configs.qwen_1_5b import SYSTEM_PROMPT, FEW_SHOTS

CONFIG = {
    "name": "qwen_0_5b",
    "enabled": True,
    "use_prefilter": False,
    "heuristic_only": False,
    "loader": {
        "repo_id": "Qwen/Qwen2.5-0.5B-Instruct-GGUF",
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
