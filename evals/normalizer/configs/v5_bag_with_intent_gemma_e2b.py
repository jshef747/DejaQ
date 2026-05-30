"""v5: sorted keyword bag + intent tags on Gemma 4 E2B.

Same prompt as v4, swapped to Gemma 4 E2B. This isolates the model variable:
  v2 vs v4 = prompt change (no intent vs intent), same Qwen 0.5B model
  v4 vs v5 = model change (Qwen 0.5B vs Gemma E2B), same intent prompt
"""

from configs.v4_bag_with_intent_qwen_0_5b import CONFIG as V4_CONFIG

CONFIG = {
    "name": "v5_bag_with_intent_gemma_e2b",
    "description": "Sorted keyword bag + intent tags, Gemma 4 E2B (~2B active params)",
    "enabled": False,
    "loader": {
        "repo_id": "unsloth/gemma-4-E2B-it-GGUF",
        "filename": "gemma-4-E2B-it-Q4_K_M.gguf",
        "n_ctx": 4096,
    },
    "inference": {
        "max_tokens": 48,
        "temperature": 0.0,
    },
    "system_prompt": V4_CONFIG["system_prompt"],
    "few_shots": V4_CONFIG["few_shots"],
}
