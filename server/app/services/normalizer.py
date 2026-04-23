"""Normalizer v22: opinion-gated LLM rewrite + raw passthrough + bge-small embedding.

Non-opinion queries: lowercase passthrough (no LLM).
Opinion queries: Gemma 4 E2B rewrites to "best <noun>" via regex-gated few-shot prompt.
Fallback: if LLM output fails the "best <noun>" format check, return lowercase passthrough.
"""

from __future__ import annotations

import logging
import re
import time

from spellchecker import SpellChecker

from app.services.model_backends import CompletionRequest, ModelBackend

_spell = SpellChecker()
# Common proper nouns the base dictionary lacks.
# Load at high frequency so they're preferred over phonetically similar common words
# (e.g., "ukrine" → "ukraine" not "urine").
_PROPER_NOUNS = [
    # Geopolitics
    "ukraine", "ukrainian", "russia", "russian", "israel", "israeli", "palestine",
    "palestinian", "iran", "iranian", "china", "chinese", "taiwan", "taiwanese",
    "korean", "korea", "japan", "japanese", "nato", "biden", "putin", "zelensky",
    # Cities / places
    "aviv", "tel", "beijing", "shanghai", "tokyo", "seoul", "dubai", "cairo",
    "paris", "berlin", "london", "rome", "madrid", "lisbon", "amsterdam",
    "stockholm", "oslo", "helsinki", "warsaw", "prague", "budapest", "vienna",
    "zurich", "geneva", "brussels", "athens", "istanbul", "moscow", "kyiv",
    "riyadh", "doha", "tehran", "kabul", "nairobi", "lagos", "accra", "dakar",
    "mumbai", "delhi", "bangalore", "karachi", "dhaka", "colombo", "kathmandu",
    "singapore", "jakarta", "manila", "hanoi", "bangkok", "kuala",
    "sydney", "melbourne", "auckland", "toronto", "montreal", "vancouver",
    "chicago", "houston", "phoenix", "dallas", "seattle", "boston", "miami",
    "denver", "atlanta", "detroit", "portland", "nashville", "austin",
    # Tech / AI
    "elon", "musk", "openai", "chatgpt", "llm", "api", "gpu", "cpu",
    "golang", "kotlin", "rust", "typescript", "javascript", "python",
    "nodejs", "django", "fastapi", "flask", "react", "nextjs", "vuejs",
    "angular", "svelte", "tailwind", "webpack", "vite", "docker", "kubernetes",
    "postgres", "postgresql", "mongodb", "redis", "sqlite", "mysql",
    "graphql", "grpc", "kafka", "rabbitmq", "nginx", "apache",
    "github", "gitlab", "bitbucket", "jira", "confluence", "slack",
    "linux", "ubuntu", "debian", "fedora", "macos", "windows",
    "tensorflow", "pytorch", "numpy", "pandas", "sklearn", "scipy",
    "gemini", "claude", "anthropic", "mistral", "llama", "gemma",
    "huggingface", "langchain", "chromadb", "pinecone", "weaviate",
    "celery", "uvicorn", "pydantic", "sqlalchemy",
    # People / companies
    "google", "microsoft", "amazon", "netflix", "nvidia", "intel", "apple",
    "meta", "bytedance", "alibaba", "tencent", "baidu", "samsung",
    "zuckerberg", "bezos", "altman", "pichai", "nadella", "huang",
]
_spell.word_frequency.load_words(_PROPER_NOUNS * 10_000)
_WORD_RE = re.compile(r"([a-zA-Z'-]+|[^a-zA-Z'-]+)")

logger = logging.getLogger("dejaq.services.normalizer")

# ---------------------------------------------------------------------------
# Regex gates (ported verbatim from normalization-test/configs/v22_opinion_llm_rewrite_bge_small.py)
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Opinion rewrite prompt
# ---------------------------------------------------------------------------

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


def _spell_correct(query: str) -> str:
    """Correct misspelled words in the query.

    Tokenizes on word/non-word boundaries so punctuation isn't swallowed into
    tokens. Only fixes unknown alphabetic tokens ≥ 4 chars; leaves proper nouns
    in the custom word list, short tokens, and non-alpha tokens unchanged.
    """
    tokens = _WORD_RE.findall(query)
    # Collect alphabetic tokens to batch-check
    alpha_tokens = [t for t in tokens if t.isalpha() and len(t) >= 4]
    unknown = _spell.unknown(alpha_tokens)
    if not unknown:
        return query

    changed = []
    result = []
    for token in tokens:
        low = token.lower()
        # Skip capitalized tokens — proper nouns (cities, names, brands) are
        # capitalized in natural input and must not be "corrected".
        if token.isalpha() and len(token) >= 4 and low in unknown and not token[0].isupper():
            fix = _spell.correction(low)
            if fix and fix != low:
                result.append(fix)
                changed.append(f"{token!r}→{fix!r}")
            else:
                result.append(token)
        else:
            result.append(token)

    if changed:
        logger.debug("Spell corrections: %s", ", ".join(changed))
    return "".join(result)


def _is_opinion(query: str) -> bool:
    return bool(_OPINION_GATE.search(query) and not _HOWTO_ADVERBIAL.search(query))


def _postprocess(raw: str, original: str) -> str:
    """Validate LLM output. Falls back to lowercase passthrough on format failure."""
    text = raw.strip().split("\n")[0].strip().lower()
    text = re.sub(r"[^\w\s-]", " ", text)
    text = " ".join(text.split())
    if not _BEST_FORM.match(text):
        logger.warning("Opinion rewrite failed format check; falling back to passthrough. raw=%r", raw)
        return original.strip().lower()
    return text


def _build_opinion_messages(query: str) -> list[dict]:
    messages: list[dict] = [{"role": "system", "content": _SYSTEM_PROMPT}]
    for user_input, assistant_output in _FEW_SHOTS:
        messages.append({"role": "user", "content": f"INPUT: {user_input}\nQUERY:"})
        messages.append({"role": "assistant", "content": assistant_output})
    messages.append({"role": "user", "content": f"INPUT: {query}\nQUERY:"})
    return messages


class NormalizerService:
    def __init__(self, backend: ModelBackend, model_name: str):
        self.backend = backend
        self.model_name = model_name

    async def normalize(self, raw_query: str) -> str:
        logger.debug("Normalizing query: %s", raw_query)
        start = time.time()

        query = _spell_correct(raw_query)

        if not _is_opinion(query):
            normalized = query.strip().lower()
            latency = (time.time() - start) * 1000
            logger.info(
                "Normalization (passthrough) in %.2f ms. Raw: %r -> Normalized: %r",
                latency, raw_query, normalized,
            )
            return normalized

        messages = _build_opinion_messages(query)
        raw_output = await self.backend.complete(
            CompletionRequest(
                model_name=self.model_name,
                messages=messages,
                max_tokens=8,
                temperature=0.0,
            )
        )
        normalized = _postprocess(raw_output, raw_query)

        latency = (time.time() - start) * 1000
        logger.info(
            "Normalization (opinion rewrite) in %.2f ms. Raw: %r -> Normalized: %r",
            latency, raw_query, normalized,
        )
        return normalized
