"""Validator config: Qwen 2.5-1.5B-Instruct. LLM judge only (no heuristic prefilter).

Primary candidate for production — already loaded by context_adjuster in DejaQ.
"""

SYSTEM_PROMPT = (
    "You decide if a CACHED ANSWER can correctly answer a NEW QUESTION.\n"
    "Reply with exactly one word: VALID or INVALID.\n"
    "VALID = the cached answer already contains EVERY specific fact the new question asks for.\n"
    "INVALID = the cached answer is missing any requested fact, is about a different entity, or is off-topic.\n"
    "Two rules:\n"
    "- MULTIPLE FACTS: If the new question asks for two or more facts (e.g. 'A and B'), "
    "the answer must contain ALL of them. A partial answer is INVALID.\n"
    "- TONE: Ignore tone, formality, and language style. Casual or slang phrasing that "
    "asks for the same information is VALID if the answer contains it.\n"
    "When in doubt, choose INVALID."
)

FEW_SHOTS = [
    # exact_paraphrase -> VALID
    (
        "CACHED QUESTION: What is the capital of France?\n"
        "CACHED ANSWER: The capital of France is Paris.\n"
        "NEW QUESTION: What is France's capital city?",
        "VALID",
    ),
    # tone_variant -> VALID (very casual phrasing, same fact)
    (
        "CACHED QUESTION: What is gravity?\n"
        "CACHED ANSWER: Gravity is a fundamental force that attracts objects with mass toward each other.\n"
        "NEW QUESTION: bro what even is gravity and why do things fall",
        "VALID",
    ),
    # different_fact_same_topic -> INVALID (the original bug)
    (
        "CACHED QUESTION: What is the capital of New Zealand?\n"
        "CACHED ANSWER: Wellington is the capital city of New Zealand.\n"
        "NEW QUESTION: How many people live in the capital of New Zealand?",
        "INVALID",
    ),
    # different_entity -> INVALID
    (
        "CACHED QUESTION: What is the capital of France?\n"
        "CACHED ANSWER: The capital of France is Paris.\n"
        "NEW QUESTION: What is the capital of Germany?",
        "INVALID",
    ),
    # partial_overlap -> INVALID (answer has only one of two requested facts)
    (
        "CACHED QUESTION: What is the capital of New Zealand?\n"
        "CACHED ANSWER: Wellington is the capital of New Zealand.\n"
        "NEW QUESTION: What is the capital and largest city of New Zealand?",
        "INVALID",
    ),
    # partial_overlap -> INVALID (compound question, answer covers only author not date)
    (
        "CACHED QUESTION: Who wrote Hamlet?\n"
        "CACHED ANSWER: Hamlet was written by William Shakespeare.\n"
        "NEW QUESTION: Who wrote Hamlet and when was it written?",
        "INVALID",
    ),
    # different_topic -> INVALID
    (
        "CACHED QUESTION: What is machine learning?\n"
        "CACHED ANSWER: Machine learning is a branch of AI where systems learn from data.\n"
        "NEW QUESTION: What is deep learning?",
        "INVALID",
    ),
    # tone_variant -> VALID (slang, same concept)
    (
        "CACHED QUESTION: What is photosynthesis?\n"
        "CACHED ANSWER: Photosynthesis is the process by which plants convert sunlight, water, and CO2 into glucose and oxygen.\n"
        "NEW QUESTION: yo eli5 photosynthesis",
        "VALID",
    ),
]

CONFIG = {
    "name": "qwen_1_5b",
    "enabled": True,
    "use_prefilter": False,
    "heuristic_only": False,
    "loader": {
        "repo_id": "Qwen/Qwen2.5-1.5B-Instruct-GGUF",
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
