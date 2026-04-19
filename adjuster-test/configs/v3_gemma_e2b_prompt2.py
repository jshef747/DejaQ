"""v3: Gemma 4 E2B — improved prompt targeting Gemma's failure modes.

Changes vs v2:
- System prompt explicitly instructs: match the query's register, don't overcorrect
- Added few-shots for formal (academic register) and brief (compression)
- Added explicit neutral/technical passthrough example to stop casual overcorrection
"""

SYSTEM_PROMPT = (
    "Rewrite the ANSWER to match the tone and register of the QUESTION. "
    "Follow these rules strictly:\n"
    "- If the question is casual or uses slang, make the answer conversational\n"
    "- If the question is formal or academic, use elevated vocabulary and complex sentence structure\n"
    "- If the question asks for brevity (tl;dr, quick, one sentence), give a short compressed answer\n"
    "- If the question is neutral or technical, keep the answer factual and direct — do NOT add slang or casual language\n"
    "- Always keep every fact from the original answer\n"
    "Output only the rewritten answer."
)

FEW_SHOTS = [
    # Casual → conversational
    (
        "QUESTION: yo whats the capital of france\n"
        "ANSWER: The capital of France is Paris.",
        "It's Paris!",
    ),
    # ELI5 → simple analogies
    (
        "QUESTION: explain gravity like I'm 5\n"
        "ANSWER: Gravity is a fundamental force of attraction between objects with mass.",
        "Imagine you have a ball. When you throw it up, it comes back down! "
        "That's because the Earth is really big and pulls everything toward it. "
        "That pulling is called gravity!",
    ),
    # Formal → academic register
    (
        "QUESTION: Could you elucidate the biochemical mechanism of photosynthesis?\n"
        "ANSWER: Photosynthesis is how plants make food from sunlight.",
        "Photosynthesis constitutes the biochemical process by which plants, algae, and certain "
        "bacteria transduce light energy into chemical energy. Carbon dioxide and water are "
        "transformed into glucose and oxygen through light-dependent reactions and the Calvin cycle "
        "within the chloroplasts.",
    ),
    # Brief → compressed, no filler
    (
        "QUESTION: tl;dr what is DNA?\n"
        "ANSWER: DNA (deoxyribonucleic acid) is a molecule that carries genetic instructions for "
        "the development, functioning, and reproduction of all known organisms. It has a "
        "double-helix structure.",
        "Molecule carrying genetic instructions for all life. Double-helix structure.",
    ),
    # Technical/neutral → factual, no casual language added
    (
        "QUESTION: What is the mechanism of TCP flow control?\n"
        "ANSWER: TCP flow control uses a sliding window protocol where the receiver advertises "
        "its buffer size to the sender, limiting how much data can be in transit at once.",
        "TCP flow control uses a sliding window protocol where the receiver advertises its buffer "
        "size to the sender, limiting how much unacknowledged data can be in transit at once.",
    ),
]

CONFIG = {
    "name": "v3_gemma_e2b_prompt2",
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
