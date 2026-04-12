"""v22: opinion-gated LLM rewrite to 'best <noun>' + BAAI/bge-small-en-v1.5.

v20 champion (raw passthrough + bge-small) scored 74.7% Hit@0.20 overall but only
35.7% on the opinion category. Every failing pair is a superlative query where
bge-small can't collapse noun drift ("greatest category of books" vs "genre of
literature") without help. This config patches only that one category.

Approach
--------
Stage 1 — regex gate. Detect opinion queries via superlative markers
          ("best", "greatest", "ultimate", "finest", "top-rated",
           "most highly recommended", "absolute best", "arguably").
Stage 2 — LLM rewrite (Gemma 4 E2B, already cached). The LLM is asked to
          output exactly "best <noun>" on one line. Few-shots use topics
          disjoint from the test set.

In the test harness the LLM runs on EVERY prompt (runner has no conditional
passthrough). `_postprocess` then discards the LLM output for non-opinion
queries and returns the raw query lowercased — same behavior as v20 for those.
On a live request the server path will gate on the regex first and skip the
LLM entirely for ~95% of traffic; reported mean-latency here is therefore an
upper bound, not the prod number.

Test-set concepts excluded from few-shots (reused from v18 exclusion list):
  opinion: best_browser, best_tv_show_finale, best_language_for_data_science,
           best_car_brand, best_season_of_the_year, best_cuisine_in_the_world,
           best_exercise_for_weight_loss, best_streaming_service,
           best_book_genre, best_music_genre, best_way_to_cook_steak,
           best_board_game, best_city_to_live_in, best_cloud_provider

Run
---
    cd normalization-test && VIRTUAL_ENV= uv run python -m harness.runner \\
        --configs v22_opinion_llm_rewrite_bge_small
"""

from __future__ import annotations

import re

_SYSTEM_PROMPT = """\
You rewrite user superlative queries into a canonical short form.

RULES:
1. Output EXACTLY: "best <noun>" on one line. No prefix, no explanation.
2. The noun is 1-3 words. Prefer the shortest common English noun:
   "browser" not "internet browser", "car brand" not "automobile manufacturer",
   "city" not "metropolitan area", "music genre" not "musical style".
3. Drop every superlative word (best, greatest, ultimate, finest, top-rated,
   highly recommended, absolute, arguably, most, single). They all mean "best".
4. Drop every filler word (in your opinion, of all time, ever, you consider,
   do you think, widely considered, the one, to use, to play, to buy, overall).
5. Drop redundant qualifiers (drop "internet" from "internet browser", drop
   "traditional" from "traditional food", drop "fictional" from "fictional book").
6. Two paraphrases of the same concept MUST produce the same "best <noun>".
"""

# ~18 few-shots, topics disjoint from the 14 opinion concepts in the test set.
_FEW_SHOTS: list[tuple[str, str]] = [
    # hiking boot cluster
    ("Which hiking boot is the best for long trails?", "best hiking boot"),
    ("What are the top-rated boots for thru-hiking?", "best hiking boot"),
    ("Which brand makes the ultimate trekking boot?", "best hiking boot"),
    # coffee cluster
    ("What is the greatest coffee bean origin?", "best coffee"),
    ("Which country produces the finest coffee?", "best coffee"),
    # pillow cluster
    ("Which pillow is most highly recommended for back sleepers?", "best pillow"),
    ("What is the absolute best pillow to buy?", "best pillow"),
    # running shoe cluster
    ("Which running shoe is considered the greatest?", "best running shoe"),
    ("What are the top recommended shoes for marathons?", "best running shoe"),
    # camera cluster
    ("Which digital camera is the finest for beginners?", "best camera"),
    ("What is arguably the ultimate DSLR?", "best camera"),
    # novel cluster
    ("Which novel is widely considered the greatest ever written?", "best novel"),
    ("In your opinion what is the absolute best book of all time?", "best novel"),
    # single-word noun
    ("What is the greatest dog breed?", "best dog breed"),
    ("Which breed of dog is top recommended?", "best dog breed"),
    # noun-redundancy-drop demonstration
    ("Which smartphone manufacturer is the ultimate best?", "best smartphone brand"),
    ("What is the top recommended phone company?", "best smartphone brand"),
    # watch cluster (category-qualifier drop)
    ("What is arguably the finest luxury wristwatch?", "best watch"),
    ("Which timepiece is the greatest ever made?", "best watch"),
]

_OPINION_GATE = re.compile(
    r"\b(best|greatest|ultimate|finest|top[- ]?rated|top recommendation|"
    r"top recommended|most highly recommended|highly recommend|absolute best|"
    r"arguably|most (?:delicious|perfect|flavorful|amazing|beautiful)"
    r"|widely considered)\b",
    re.IGNORECASE,
)
# Howto queries use "best" adverbially: "best way/technique/method/approach to X".
# These must NOT fire the opinion gate or they collide with the howto sibling.
_HOWTO_ADVERBIAL = re.compile(
    r"\bbest\s+(way|method|technique|approach|strategy|practice|thing|"
    r"time|place|tool|tools|tip|tips)\s+(to|for|of)\b",
    re.IGNORECASE,
)
_BEST_FORM = re.compile(r"^best\s+[a-z][a-z\s-]{0,40}$")


def _postprocess(raw: str, original: str) -> str:
    """Gate on the original query. Non-opinion → raw passthrough (matches v20).

    Opinion → use LLM output, but fall back to raw if the model failed the
    expected "best <noun>" format.
    """
    if _HOWTO_ADVERBIAL.search(original):
        return original.strip().lower()
    if not _OPINION_GATE.search(original):
        return original.strip().lower()

    text = raw.strip().split("\n")[0].strip().lower()
    text = re.sub(r"[^\w\s-]", " ", text)
    text = " ".join(text.split())
    if not _BEST_FORM.match(text):
        return original.strip().lower()
    return text


CONFIG = {
    "name": "v22_opinion_llm_rewrite_bge_small",
    "description": (
        "Opinion queries -> Gemma 4 E2B rewrites to 'best <noun>'. "
        "Non-opinion queries pass through raw. bge-small-en-v1.5 embedder."
    ),
    "enabled": True,
    "passthrough": False,
    "embedder_model_path": "BAAI/bge-small-en-v1.5",
    "loader": {
        "repo_id": "unsloth/gemma-4-E2B-it-GGUF",
        "filename": "*Q4_K_M.gguf",
        "n_ctx": 2048,
    },
    "inference": {
        "max_tokens": 8,
        "temperature": 0.0,
    },
    "system_prompt": _SYSTEM_PROMPT,
    "few_shots": _FEW_SHOTS,
    "postprocess_fn": _postprocess,
    "precondition_fn": lambda q: bool(_OPINION_GATE.search(q) and not _HOWTO_ADVERBIAL.search(q)),
}
