"""Baseline config: mirrors current production context_enricher.py exactly.

- Model: Qwen 2.5-0.5B-Instruct (Q4_K_M)
- 4 few-shots (same as server/app/services/context_enricher.py)
- No regex gate (every query with history goes through the LLM)
- max_tokens=256, temperature=0.0
"""

SYSTEM_PROMPT = (
    "You are a query rewriter. Given a conversation history and a follow-up message, "
    "rewrite the follow-up into a standalone question that includes all necessary context. "
    "Output ONLY the rewritten question. If the message is already standalone, return it unchanged."
)

# Each shot: (history_str, followup_input, expected_output)
FEW_SHOTS = [
    (
        "User: What is Python?\nAssistant: Python is a high-level programming language.",
        "Tell me more about its features",
        "What are the main features of the Python programming language?",
    ),
    (
        "User: How does photosynthesis work?\nAssistant: Photosynthesis converts light energy into chemical energy in plants.",
        "What about the dark reactions?",
        "What are the dark reactions in photosynthesis?",
    ),
    (
        "User: What is the capital of Italy?\nAssistant: The capital of Italy is Rome.",
        "I am traveling there recommend me restaurants",
        "What restaurants should I visit in Rome?",
    ),
    (
        "User: What is gravity?\nAssistant: Gravity is a fundamental force of attraction.",
        "What is the capital of France?",
        "What is the capital of France?",
    ),
]

CONFIG = {
    "name": "baseline_qwen_0_5b",
    "enabled": True,
    "loader": {
        "repo_id": "Qwen/Qwen2.5-0.5B-Instruct-GGUF",
        "filename": "*q4_k_m*",
        "n_ctx": 4096,
    },
    "inference": {
        "max_tokens": 256,
        "temperature": 0.0,
    },
    "system_prompt": SYSTEM_PROMPT,
    "few_shots": FEW_SHOTS,
    # No embedder_model_path → uses default (BAAI/bge-small-en-v1.5)
}
