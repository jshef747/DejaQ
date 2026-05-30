"""v12: hybrid — LLM picks intent only, Python rules extract content nouns.

v8–v11 all failed because Gemma E2B can't reliably canonicalize synonyms across
phrasings. Same concept → different nouns every time. v12 removes noun selection
from the model entirely:

1. LLM call is grammar-locked to ONE token: the intent tag (12 options).
   This is the only thing the model is actually good at.
2. A deterministic Python pipeline processes the ORIGINAL query:
   - lowercase
   - strip punctuation
   - remove stopwords, fillers, scope-modifiers
   - apply a synonym canonicalization map
   - crude singularization (trailing s/es/ies)
   - keep top-K most informative tokens (by length and non-fillerness)
   - alphabetically sort
3. Final output: `<intent> <sorted content nouns>`

The rule pipeline is what v8–v11 were asking the LLM to do via prose. Doing it
in Python makes it deterministic and eliminates cross-phrasing variance.
"""

from __future__ import annotations

import re

# ── GBNF: force output to be exactly one intent tag ─────────────────────────
_GRAMMAR = r"""
root   ::= intent "\n"
intent ::= "fact" | "explain" | "why" | "compare" | "create" | "howto" | "best" | "history" | "define" | "list" | "debug" | "summarize"
"""

_SYSTEM_PROMPT = """\
You are an intent classifier. Given a user query, output EXACTLY ONE intent tag from this list and nothing else:

  fact      → factual lookup (capital, speed, count, location, size) with NO person/date answer
  explain   → mechanism/process/concept: how does X work, what causes X
  why       → causation: why does/did X
  compare   → X vs Y, difference between X and Y
  create    → ANY programming/code request (language/framework mentioned)
  howto     → non-code physical/life task: cook, fix, tie, plant, clean, build
  best      → opinion/preference: best X, recommend X, top X
  history   → answer is a person's name OR a date/year (who invented/wrote X, when did X)
  define    → vocabulary lookup only: what does X mean
  list      → enumeration: list all X, name the X
  debug     → troubleshoot: my X is slow/broken
  summarize → overview/tldr of X

Rules (apply in order, first match wins):
1. Programming language mentioned → create
2. Answer is a person or date → history
3. "X vs Y" or "difference between X and Y" → compare
4. "Why" question → why
5. "How does X work / what causes X" → explain
6. "How to [physical task]" → howto
7. "Best X / recommend X" → best
8. "What does X mean" → define
9. "List/name the X" → list
10. "My X is broken/slow" → debug
11. "Summarize X" → summarize
12. Otherwise → fact

Output ONLY the intent tag, lowercase, nothing else.\
"""

_FEW_SHOTS = [
    ("what is the capital of france",                      "fact"),
    ("how many planets are in the solar system",           "fact"),
    ("what is the speed of light",                         "fact"),
    ("how does photosynthesis work",                       "explain"),
    ("what causes gravity",                                "explain"),
    ("what is dark matter",                                "explain"),
    ("why is the sky blue",                                "why"),
    ("why did the roman empire fall",                      "why"),
    ("rust vs go for systems programming",                 "compare"),
    ("difference between sql and nosql",                   "compare"),
    ("tcp vs udp",                                         "compare"),
    ("write a python function to reverse a list",          "create"),
    ("how do i center a div in css",                       "create"),
    ("bash script to loop through files",                  "create"),
    ("how do i read a file in go",                         "create"),
    ("how to tie a tie",                                   "howto"),
    ("how to bake a chocolate cake",                       "howto"),
    ("how to plant a tree",                                "howto"),
    ("best programming language for machine learning",     "best"),
    ("which car brand is the best",                        "best"),
    ("best streaming service",                             "best"),
    ("who invented the internet",                          "history"),
    ("who wrote romeo and juliet",                         "history"),
    ("when did world war 2 end",                           "history"),
    ("what does entropy mean",                             "define"),
    ("definition of recursion",                            "define"),
    ("list all planets in the solar system",               "list"),
    ("what are the python data types",                     "list"),
    ("my postgres query is slow",                          "debug"),
    ("react component not rendering",                      "debug"),
    ("summarize the theory of relativity",                 "summarize"),
]

# ── Rule pipeline ────────────────────────────────────────────────────────────

# Words that carry no topic meaning. Dropped unconditionally.
_STOPWORDS = frozenset("""
a an the and or but of in on at to for from with without by into onto upon
is are was were be been being am do does did doing done have has had having
will would could should may might must shall can cannot
i me my mine we us our ours you your yours he him his she her hers it its
they them their theirs this that these those what which who whom whose
how when where why whether if then than as so such also just only even still
yet very much more most less least many few some any all every each no not
please kindly hey hi hello thanks thank ok okay well actually basically really
truly simply literally kind sort type exactly precisely rather quite fairly
tell show give teach guide help walk let make me us through step steps stepbystep
want trying need looking about get got getting going go come came ever never
always sometimes often usually generally typically normally currently recently
today tomorrow yesterday now later sooner longer shorter
thing things stuff matter way ways method methods process kind
there here everywhere somewhere anywhere nowhere
good better great nice new old young big large small little
mean means meaning called named known said
""".split())

# Filler phrases that appear verbatim (before tokenization they get dropped)
_FILLER_PHRASES = [
    "step by step", "step-by-step", "from scratch", "of all time", "all time",
    "in general", "in the world", "on earth", "in the universe",
    "in our solar system", "highly recommended", "widely considered",
    "in your opinion", "would you say", "do you think", "like a pro",
    "right now", "these days", "at home", "for beginners",
]

# Canonicalize variants → single form. Applied AFTER tokenization, per token.
_SYNONYMS = {
    # abbreviations — always short form
    "javascript": "js", "typescript": "ts", "python": "py",
    "csharp": "c-sharp",
    "tcp": "tcp", "udp": "udp", "api": "api", "ml": "ml", "ai": "ai",
    "ui": "ui", "db": "db", "css": "css", "html": "html", "sql": "sql",
    "js": "js", "ts": "ts", "cpr": "cpr", "http": "http", "url": "url",
    "cpu": "cpu", "gpu": "gpu", "ram": "ram",
    # object/noun canonicalization
    "necktie": "tie", "knot": "tie",
    "dice": "cut", "chop": "cut", "slice": "cut", "mince": "cut",
    "mobile": "phone", "smartphone": "phone", "cellphone": "phone", "cell": "phone",
    "vehicle": "car", "automobile": "car", "auto": "car",
    "novel": "book", "publication": "book", "text": "book", "story": "book",
    "film": "movie", "picture": "movie", "adaptation": "movie",
    "application": "app", "software": "app", "tool": "app", "program": "app", "platform": "app",
    "pc": "computer", "machine": "computer", "device": "computer",
    "snippet": "code", "script": "code",
    "error": "bug", "issue": "bug", "defect": "bug", "problem": "bug",
    "laggy": "slow", "sluggish": "slow",
    "postgres": "database", "mysql": "database", "mongo": "database",
    "mongodb": "database", "datastore": "database", "postgresql": "database",
    "holiday": "vacation", "trip": "vacation", "getaway": "vacation",
    "place": "destination", "location": "destination", "spot": "destination",
    "brand": "company", "manufacturer": "company", "maker": "company",
    "exercise": "workout", "fitness": "workout", "training": "workout",
    "cv": "resume",
    "reside": "live", "residing": "live", "living": "live",
    "metropolitan": "city", "metropolis": "city",
    "prepare": "cook", "preparation": "cook", "cooking": "cook",
    "grilling": "cook", "searing": "cook",
    "tabletop": "board",
    "cinema": "movie", "series": "show", "episode": "show", "finale": "show",
    "television": "tv",
    "genre": "genre", "category": "genre",
    "literature": "book", "fiction": "book",
    "wash": "clean", "cleaning": "clean", "streakless": "clean",
    "streak-free": "clean", "streak": "clean",
    "bedroom": "room", "interior": "room",
    "prep": "paint", "painting": "paint",
    "wrap": "wrap", "wrapping": "wrap", "present": "gift",
    # superlatives → canonical
    "biggest": "largest", "greatest": "best", "top": "best", "finest": "best",
    "ultimate": "best", "optimal": "best", "ideal": "best", "premier": "best",
    "superior": "best", "highest": "largest", "tallest": "largest",
    "tiniest": "smallest", "littlest": "smallest", "least": "smallest",
    "quickest": "fastest", "speediest": "fastest", "swiftest": "fastest",
    "ancient": "oldest", "earliest": "oldest",
    "toughest": "hardest", "strongest": "hardest",
    "poorest": "worst", "lowest": "worst",
    # historic events
    "wwii": "ww2", "ww-ii": "ww2",
    "wwi": "ww1", "ww-i": "ww1",
    # verbs around history questions
    "invented": "invention", "discovered": "discovery",
    "created": "creation", "founded": "founding",
    "assassinated": "assassination", "killed": "assassination", "shot": "assassination",
    # shape/object words
    "shape": "structure", "form": "structure",
    # people noise
    "scientists": "scientist", "scientist": "scientist",
}


def _singularize(token: str) -> str:
    """Crude singularization — handles the common cases only."""
    if len(token) < 4:
        return token
    if token.endswith("ies"):
        return token[:-3] + "y"
    if token.endswith("sses") or token.endswith("xes") or token.endswith("ches") or token.endswith("shes"):
        return token[:-2]
    if token.endswith("s") and not token.endswith("ss") and not token.endswith("us"):
        return token[:-1]
    return token


_WORD_RE = re.compile(r"[a-z][a-z0-9+#-]*")


def _extract_content_nouns(query: str, intent: str, max_nouns: int = 4) -> list[str]:
    q = query.lower()
    # drop filler phrases first (before tokenization)
    for phrase in _FILLER_PHRASES:
        q = q.replace(phrase, " ")
    # tokenize
    tokens = _WORD_RE.findall(q)
    # filter stopwords, singularize, canonicalize
    out: list[str] = []
    seen: set[str] = set()
    for t in tokens:
        if t in _STOPWORDS:
            continue
        if len(t) < 2:
            continue
        t = _singularize(t)
        t = _SYNONYMS.get(t, t)
        # re-check stopwords after canonicalization
        if t in _STOPWORDS:
            continue
        if t in seen:
            continue
        # skip intent-matching words (they're redundant with the intent tag)
        if t == intent:
            continue
        seen.add(t)
        out.append(t)

    # For code (create intent), preserve as much as possible — code queries
    # need language + verb + object. We keep up to max_nouns tokens.
    if intent == "create":
        limit = max_nouns
    elif intent == "compare":
        limit = 2  # compare is exactly X vs Y
    else:
        limit = 3  # most intents: topic + 1-2 qualifiers is enough for specificity

    # Prefer shorter (more canonical) and distinctive tokens.
    # Sort by length then alpha to pick consistently across phrasings.
    # Then alphabetically sort the final selection.
    if len(out) > limit:
        # rank by "informativeness" — longer is usually more specific, but we
        # want CONVERGENCE, so prefer the tokens most likely to recur.
        # Heuristic: alphabetical (deterministic) after preferring length 4-10.
        def rank(tok: str) -> tuple[int, str]:
            # tier 1: nouns of length 4-10 (sweet spot for content nouns)
            tier = 0 if 4 <= len(tok) <= 10 else 1
            return (tier, tok)
        out = sorted(out, key=rank)[:limit]

    return sorted(out)


def v12_postprocess(raw: str, original_query: str) -> str:
    """Take the LLM's intent tag + original query, run the rule pipeline."""
    intent = raw.strip().lower().split()[0] if raw.strip() else "fact"
    valid_intents = {"fact", "explain", "why", "compare", "create", "howto",
                     "best", "history", "define", "list", "debug", "summarize"}
    if intent not in valid_intents:
        intent = "fact"
    nouns = _extract_content_nouns(original_query, intent)
    return " ".join([intent] + nouns) if nouns else intent


CONFIG = {
    "name": "v12_hybrid_rules_gemma_e2b",
    "description": "Hybrid: LLM → intent only (grammar-locked), Python rules → content nouns from original query",
    "enabled": False,
    "loader": {
        "repo_id": "unsloth/gemma-4-E2B-it-GGUF",
        "filename": "gemma-4-E2B-it-Q4_K_M.gguf",
        "n_ctx": 8192,
    },
    "inference": {
        "max_tokens": 4,
        "temperature": 0.0,
    },
    "grammar": _GRAMMAR,
    "system_prompt": _SYSTEM_PROMPT,
    "few_shots": _FEW_SHOTS,
    "postprocess_fn": v12_postprocess,
}
