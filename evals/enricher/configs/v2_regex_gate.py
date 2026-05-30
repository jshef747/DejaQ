"""v2: Regex gate before LLM — standalone queries skip inference entirely.

Same model and few-shots as baseline. Adds a precondition_fn that detects
context-dependent signals (pronouns, continuation markers). If none found,
the follow-up is returned as-is with zero LLM cost.

Expected improvement: passthrough rate 60% → ~100%, fidelity unchanged.
"""

import re

_CONTEXT_DEPENDENT = re.compile(
    # Pronouns that reference prior context
    r"\b(it|its|they|them|their|this|that|he|she|him|her|those|these)\b"
    # Continuation / elaboration markers
    r"|what about|how about|tell me more"
    r"|and (the|what|how|why|when|where|who|which)"
    r"|but (what|how|why|when|where|who|which)"
    r"|also\b|elaborate|expand on"
    r"|more (about|on|details|info|information)"
    r"|how so\b|why so\b|explain more|and what|and how"
    # Pronoun + verb combos
    r"|did (we|they|he|she|it)\b"
    r"|do (we|they|he|she|it)\b"
    r"|can (we|they|he|she|it)\b"
    r"|is (it|this|that|there)\b"
    r"|are (they|these|those|we)\b"
    r"|was (it|this|that|he|she)\b"
    r"|were (they|we)\b"
    # Sentence-leading conjunctions ("And generators?", "But why?")
    r"|^(and|but|or)\b"
    # Comparison references without explicit subject — "which is X?", "which pays more?"
    # Catches multi-reference follow-ups like "Which is easier?" / "Which pays more?"
    r"|\bwhich (is|are|was|were|would|should|does|do|did|has|have|can|will|pays|burns|makes|gives|comes|works)\b"
    # "each" almost always references a set from history ("use each", "do each")
    r"|\beach\b"
    # "which one", "one over the other", "one of them", "the other one"
    r"|\bwhich one\b"
    r"|\bone (of them|over the other|is better|is worse|first|second)\b"
    r"|\bthe other\b",
    re.IGNORECASE,
)

SYSTEM_PROMPT = (
    "You are a query rewriter. Given a conversation history and a follow-up message, "
    "rewrite the follow-up into a standalone question that includes all necessary context. "
    "Output ONLY the rewritten question. If the message is already standalone, return it unchanged."
)

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
    "name": "v2_regex_gate",
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
    # Gate: return True if the follow-up needs enrichment (has context signals)
    # Return False to skip the LLM and pass through as-is
    "precondition_fn": lambda q: bool(_CONTEXT_DEPENDENT.search(q)),
}
