"""v4: Gemma 4 E2B — balanced few-shots, no explicit rules.

Approach: simple system prompt + 6 diverse few-shots covering all registers.
Let examples do the teaching instead of rigid rules (which caused v3 to
default to formal for everything).

Changes vs v3:
- Reverted to simple system prompt (no ruleset)
- Kept v2 casual + eli5 shots (those worked)
- Added formal shot from v3 (that worked)
- Added proper brief shot (extreme compression)
- Added humorous shot
- Added neutral/technical passthrough shot
"""

SYSTEM_PROMPT = (
    "Rewrite the ANSWER to match the tone and style of the QUESTION. "
    "Keep all facts. Output only the rewritten answer."
)

FEW_SHOTS = [
    # Casual → conversational slang
    (
        "QUESTION: yo whats the capital of france\n"
        "ANSWER: The capital of France is Paris.",
        "It's Paris!",
    ),
    # ELI5 → simple analogies, enthusiasm
    (
        "QUESTION: explain gravity like I'm 5\n"
        "ANSWER: Gravity is a fundamental force of attraction between objects with mass.",
        "Imagine you have a ball. When you throw it up, it comes back down! "
        "That's because the Earth is really big and pulls everything toward it. "
        "That pulling is called gravity!",
    ),
    # Formal → academic register, elevated vocabulary
    (
        "QUESTION: Could you elucidate the biochemical mechanism of photosynthesis?\n"
        "ANSWER: Photosynthesis is how plants make food from sunlight.",
        "Photosynthesis constitutes the biochemical process by which plants, algae, and certain "
        "bacteria transduce light energy into chemical energy. Carbon dioxide and water are "
        "transformed into glucose and oxygen through light-dependent reactions and the Calvin cycle "
        "within the chloroplasts.",
    ),
    # Brief → extreme compression, fragments OK
    (
        "QUESTION: tl;dr boiling point of water?\n"
        "ANSWER: Water boils at 100 degrees Celsius (212 degrees Fahrenheit) at standard "
        "atmospheric pressure. The boiling point decreases at higher altitudes.",
        "100°C / 212°F at sea level. Lower at altitude.",
    ),
    # Humorous → jokes, playful framing, keep all facts
    (
        "QUESTION: explain the water cycle but make it funny\n"
        "ANSWER: The water cycle is the continuous movement of water through evaporation, "
        "condensation, and precipitation. Water evaporates from oceans and lakes, rises as "
        "vapor, condenses into clouds, and falls back as rain or snow.",
        "Water has serious commitment issues — it evaporates from the ocean, floats up into "
        "the sky as vapor, hangs out as clouds for a bit, then crashes back down as rain or snow. "
        "It's been doing this same dramatic loop for billions of years and shows no signs of stopping.",
    ),
    # Neutral/technical → factual, no casual language added
    (
        "QUESTION: What is the mechanism of TCP flow control?\n"
        "ANSWER: TCP flow control uses a sliding window protocol where the receiver advertises "
        "its buffer size to the sender, limiting how much data can be in transit at once.",
        "TCP flow control uses a sliding window protocol where the receiver advertises its buffer "
        "size to the sender, limiting how much unacknowledged data can be in transit at once.",
    ),
]

CONFIG = {
    "name": "v4_gemma_e2b_balanced",
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
