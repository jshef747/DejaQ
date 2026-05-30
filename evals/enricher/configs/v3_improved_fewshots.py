"""v3: Gate fix (\bone\b) + expanded few-shots (8 examples).

Three improvements over v2:
1. Gate: adds \bones?\b to catch "How do I create one?", "Can I write custom ones?"
2. Few-shots: adds subject-injection examples for short "which" comparatives
   (model must name both subjects from history, not echo the bare comparative)
3. Few-shots: adds 3-turn deep-chain example where pronoun refers to turn-1 entity
"""

import re

_CONTEXT_DEPENDENT = re.compile(
    # Pronouns that reference prior context
    r"\b(it|its|they|them|their|this|that|he|she|him|her|those|these)\b"
    # Bare pronoun "one" / "ones" referencing a noun from history
    # e.g. "How do I create one?", "Can I write custom ones?"
    r"|\bones?\b"
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
    r"|\bwhich (is|are|was|were|would|should|does|do|did|has|have|can|will|pays|burns|makes|gives|comes|works)\b"
    # "each" almost always references a set from history
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
    # --- pronoun resolution ---
    (
        "User: What is Python?\nAssistant: Python is a high-level programming language.",
        "Tell me more about its features",
        "What are the main features of the Python programming language?",
    ),
    (
        "User: What is a Python virtual environment?\nAssistant: A virtual environment is an isolated Python installation that keeps project dependencies separate.",
        "How do I create one?",
        "How do I create a Python virtual environment?",
    ),
    # --- topic continuation ---
    (
        "User: How does photosynthesis work?\nAssistant: Photosynthesis converts light energy into chemical energy in plants.",
        "What about the dark reactions?",
        "What are the dark reactions in photosynthesis?",
    ),
    # --- subject-injection for bare comparatives ---
    # "Which is X?" with no pronouns — model must name both subjects from history
    (
        "User: What are the differences between a gym membership and working out at home?\n"
        "Assistant: Gym memberships offer more equipment and classes; home workouts have lower long-term cost and convenience.",
        "Which is cheaper in the long run?",
        "Is a gym membership or home workout setup cheaper in the long run?",
    ),
    (
        "User: What is the difference between Python and Go?\n"
        "Assistant: Python is a dynamically-typed scripting language; Go is a statically-typed compiled language.",
        "Which is faster?",
        "Is Python or Go faster?",
    ),
    (
        "User: Can you compare term life insurance and whole life insurance?\n"
        "Assistant: Term life is cheaper and time-limited; whole life has a cash value component and lasts a lifetime.",
        "Which is better for most people?",
        "Is term life insurance or whole life insurance better for most people?",
    ),
    # --- deep-chain: pronoun refers to entity from turn 1, not most recent turn ---
    (
        "User: What is carbon capture?\n"
        "Assistant: Carbon capture is the process of capturing CO2 emissions from sources like power plants before they reach the atmosphere.\n"
        "User: How is the CO2 stored?\n"
        "Assistant: Captured CO2 is typically compressed and injected into deep geological formations underground.",
        "Is it effective enough to matter?",
        "Is carbon capture effective enough to significantly reduce atmospheric CO2?",
    ),
    # --- passthrough: already standalone, different topic ---
    (
        "User: What is gravity?\nAssistant: Gravity is a fundamental force of attraction.",
        "What is the capital of France?",
        "What is the capital of France?",
    ),
]

CONFIG = {
    "name": "v3_improved_fewshots",
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
    "precondition_fn": lambda q: bool(_CONTEXT_DEPENDENT.search(q)),
}
