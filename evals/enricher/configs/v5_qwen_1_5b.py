"""v5: Qwen 2.5-1.5B-Instruct — latency benchmark vs v4 (0.5B).

Same gate, same 4 few-shots as v4. Only change: model size 0.5B → 1.5B.
Purpose: measure latency cost of upgrading to 1.5B and whether it fixes
"which" comparative subject-injection failures.
"""

import re

_CONTEXT_DEPENDENT = re.compile(
    r"\b(it|its|they|them|their|this|that|he|she|him|her|those|these)\b"
    r"|\bones?\b"
    r"|what about|how about|tell me more"
    r"|and (the|what|how|why|when|where|who|which)"
    r"|but (what|how|why|when|where|who|which)"
    r"|also\b|elaborate|expand on"
    r"|more (about|on|details|info|information)"
    r"|how so\b|why so\b|explain more|and what|and how"
    r"|did (we|they|he|she|it)\b"
    r"|do (we|they|he|she|it)\b"
    r"|can (we|they|he|she|it)\b"
    r"|is (it|this|that|there)\b"
    r"|are (they|these|those|we)\b"
    r"|was (it|this|that|he|she)\b"
    r"|were (they|we)\b"
    r"|^(and|but|or)\b"
    r"|\bwhich (is|are|was|were|would|should|does|do|did|has|have|can|will|pays|burns|makes|gives|comes|works)\b"
    r"|\beach\b"
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
    "name": "v5_qwen_1_5b",
    "enabled": True,
    "loader": {
        "repo_id": "Qwen/Qwen2.5-1.5B-Instruct-GGUF",
        "filename": "*q4_k_m*",
        "n_ctx": 4096,
    },
    "inference": {
        "max_tokens": 256,
        "temperature": 0.0,
    },
    "system_prompt": SYSTEM_PROMPT,
    "few_shots": FEW_SHOTS,
    "precondition_fn": lambda q: bool(_CONTEXT_DEPENDENT.search(q)),
}
