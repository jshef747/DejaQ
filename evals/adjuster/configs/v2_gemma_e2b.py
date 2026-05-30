"""v2: Gemma 4 E2B — same prompts as baseline, different model.

Purpose: evaluate whether Gemma 4 E2B produces better tone matching
than Qwen 2.5-1.5B for the adjust() task.
"""

SYSTEM_PROMPT = (
    "Rewrite the ANSWER to match the tone of the QUESTION. "
    "Keep all facts. Output only the rewritten answer."
)

FEW_SHOTS = [
    # (user_content, assistant_content)
    (
        "QUESTION: explain gravity like I'm 5\n"
        "ANSWER: Gravity is a fundamental force of attraction between objects with mass.",
        "Imagine you have a ball. When you throw it up, it comes back down! "
        "That's because the Earth is really big and pulls everything toward it. "
        "That pulling is called gravity!",
    ),
    (
        "QUESTION: yo whats the capital of france\n"
        "ANSWER: The capital of France is Paris.",
        "It's Paris!",
    ),
    (
        "QUESTION: provide a detailed analysis of photosynthesis\n"
        "ANSWER: Photosynthesis is how plants make food from sunlight.",
        "Photosynthesis is the biochemical process by which plants, algae, and certain bacteria "
        "convert light energy into chemical energy. During this process, carbon dioxide and water "
        "are transformed into glucose and oxygen through light-dependent and light-independent "
        "reactions within the chloroplasts.",
    ),
]

CONFIG = {
    "name": "v2_gemma_e2b",
    "enabled": True,
    "loader": {
        "repo_id": "unsloth/gemma-4-E2B-it-GGUF",
        "filename": "*Q4_K_M.gguf",
        "n_ctx": 2048,
    },
    "inference": {
        "max_tokens": 1024,
        "temperature": 0.3,
    },
    "system_prompt": SYSTEM_PROMPT,
    "few_shots": FEW_SHOTS,
}
