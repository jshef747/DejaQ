"""Baseline: Qwen 2.5-1.5B — mirrors production context_adjuster.py adjust() exactly."""

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
    "name": "baseline_qwen_1_5b",
    "enabled": True,
    "loader": {
        "repo_id": "Qwen/Qwen2.5-1.5B-Instruct-GGUF",
        "filename": "*q4_k_m.gguf",
        "n_ctx": 4096,
    },
    "inference": {
        "max_tokens": 1024,
        "temperature": 0.3,
    },
    "system_prompt": SYSTEM_PROMPT,
    "few_shots": FEW_SHOTS,
}
