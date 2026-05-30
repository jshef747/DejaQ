"""v3: same sorted-bag prompt as v2, but on Gemma 4 E2B instead of Qwen 0.5B.

Hypothesis: if v2 improves over baseline but still has instability (e.g. the
model can't consistently hold the alphabetical-sort rule), the bottleneck is
the 0.5B model capacity. Gemma 4 E2B is the smallest Gemma 4 variant
(~2B active params via MoE) and should follow multi-rule instructions better.

DISABLED BY DEFAULT: downloading this model is ~3.1GB. Flip `enabled` to
True to include it in a run, or pass --configs v3_bag_gemma_e2b explicitly.
"""

from configs.v2_bag_qwen_0_5b import CONFIG as V2_CONFIG

CONFIG = {
    "name": "v3_bag_gemma_e2b",
    "description": "Sorted keyword bag prompt, Gemma 4 E2B (~2B active params)",
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
    # Reuse the exact same prompt + few-shots as v2 so the only variable is the model.
    "system_prompt": V2_CONFIG["system_prompt"],
    "few_shots": V2_CONFIG["few_shots"],
}
