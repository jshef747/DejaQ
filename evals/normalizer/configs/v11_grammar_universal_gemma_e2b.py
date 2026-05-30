"""v11: grammar-constrained universal normalizer.

Strategy: instead of trying to teach Gemma E2B complex rules via prose, we
constrain its output space directly with a GBNF grammar.

The grammar enforces:
- First token MUST be one of 12 intent tags (no hallucinated tags possible)
- Output is exactly: <intent> <noun> <noun> [<noun>] [<noun>]
- 3 to 5 keywords total (intent + 2-4 content nouns)
- Lowercase alphanumeric content nouns only

The runner post-processes the model's output to alphabetically sort content
nouns (intent stays first), removing the model's sort-order variance entirely.

Why 2-4 content nouns and not 1-2:
- Too aggressive (1 content noun) → cross-concept collisions
  (e.g., "best streaming" and "best phone" become indistinguishable)
- 2-4 nouns is the sweet spot — enough specificity to keep concepts apart,
  enough constraint to converge siblings
- Code queries use the upper end (4 nouns) to keep language + verb + object
"""

# GBNF grammar — 3 to 5 total tokens, intent first, content nouns lowercase
_GRAMMAR = r"""
root      ::= intent " " noun " " noun (" " noun)? (" " noun)? "\n"
intent    ::= "fact" | "explain" | "why" | "compare" | "create" | "howto" | "best" | "history" | "define" | "list" | "debug" | "summarize"
noun      ::= [a-z] [a-z0-9-]{1,14}
"""

_SYSTEM_PROMPT = """\
You are a query canonicalizer. Convert any user query into a deterministic keyword bag so semantically equivalent queries produce IDENTICAL output.

OUTPUT FORMAT (strict):
- First token: ONE intent tag (always)
- Then 2 to 4 content nouns (the topic of the question)
- Total: 3 to 5 keywords
- Lowercase only, space-separated
- Output ONLY the bag — no prefix, no quotes, no explanation, ends with newline

INTENT TAGS — choose exactly ONE, always first:
  fact      → factual lookup, no person/date answer (capital, speed, count, location, size)
  explain   → mechanism/process: how does X work, what causes X, what is [concept]
  why       → causation: why does/did/is X
  compare   → contrast: X vs Y, difference between X and Y, X compared to Y
  create    → ANY programming/code request (see CODE RULE below)
  howto     → non-code physical/life task: cook, fix, tie, plant, clean, build
  best      → opinion/preference: best X, recommend X, top X
  history   → answer is a person's name OR a date/year: who invented X, when did X happen
  define    → vocabulary lookup ONLY: what does X mean, definition of X
  list      → enumeration: list/name all X, what are the X
  debug     → troubleshoot a problem: my X is slow/broken
  summarize → overview/tldr of X

INTENT SELECTION (apply in order, first match wins):
1. Code/programming language mentioned → create
2. Answer is a person or date → history
3. "X vs Y" / "difference between X and Y" → compare
4. "Why" question → why
5. "How does X work / what causes X" → explain
6. "How to [physical task]" → howto
7. "What is the best X / recommend X" → best
8. "What does X mean" → define
9. "List/name the X" → list
10. "My X is broken/slow" → debug
11. "Summarize X" → summarize
12. Otherwise → fact

CONTENT NOUN RULES:
1. Pick 2 to 4 nouns that represent the TOPIC of the question.
2. ALWAYS keep the primary subject noun (planet, ocean, light, internet, button).
3. Use SINGULAR form (planet not planets, bone not bones, book not books).
4. Drop question words, articles, and filler — keep only topic-bearing nouns.
5. Use canonical synonyms: tie (not necktie), cut (not dice/chop), phone (not mobile/smartphone), car (not vehicle), best (not greatest/top/optimal), largest (not biggest), book (not novel), movie (not film), database (not postgres/mysql).
6. For abbreviations always use the short form: tcp, udp, api, ai, ml, css, html, sql, js, ts, cpr.
7. The post-processor will alphabetically sort the content nouns — pick the right WORDS, order doesn't matter.

CODE RULE — for create intent (programming queries):
- ALWAYS include the language/framework as a content noun (python, js, ts, java, go, rust, ruby, php, c, cpp, csharp, swift, kotlin, sql, html, css, react, vue, bash, docker)
- ALWAYS include the action verb (read, write, parse, fetch, center, loop, insert, select, connect, reverse, sort, map)
- ALWAYS include the object being acted on (file, list, div, table, array, function, component, button)
- Code queries should land at 4-5 total keywords (intent + 3-4 content nouns)
- Examples: "create file go read", "create center css div", "create list python reverse"

ABSOLUTE RULE: Different phrasings of the same question MUST produce byte-identical content nouns. Pick the most generic, canonical noun for each topic.\
"""

_FEW_SHOTS = [
    # ── fact ─────────────────────────────────────────────────────────────────
    ("what is the capital of france",                            "fact capital city france"),
    ("name france's capital city",                               "fact capital city france"),
    ("which planet is the coldest",                              "fact coldest planet solar"),
    ("how many bones in the human body",                         "fact body bone count human"),
    ("what is the speed of light",                               "fact light speed vacuum"),

    # ── explain ──────────────────────────────────────────────────────────────
    ("how does photosynthesis work",                             "explain photosynthesis plant process"),
    ("what causes gravity",                                      "explain force gravity mass"),
    ("how does a refrigerator keep things cold",                 "explain cold cooling refrigerator"),
    ("what is dark matter",                                      "explain dark matter universe"),

    # ── why ──────────────────────────────────────────────────────────────────
    ("why is the sky blue",                                      "why blue light sky"),
    ("why did the roman empire fall",                            "why empire fall rome"),
    ("why are russia and ukraine at war",                        "why russia ukraine war"),

    # ── compare ──────────────────────────────────────────────────────────────
    ("rust vs go for systems programming",                       "compare go rust"),
    ("difference between sql and nosql",                         "compare nosql sql"),
    ("tcp vs udp",                                               "compare tcp udp"),
    ("how does cardio differ from weightlifting",                "compare cardio weightlifting workout"),

    # ── create (code — language + verb + object) ─────────────────────────────
    ("write a python function to reverse a list",                "create list python reverse"),
    ("how do I read a file in go",                               "create file go read"),
    ("center a div in css",                                      "create center css div"),
    ("how do I insert a row in sql",                             "create insert row sql"),
    ("react useeffect to fetch data on mount",                   "create fetch react useeffect"),
    ("bash script to loop through files",                        "create bash file loop"),
    ("write a hello world program in c++",                       "create cpp hello world"),

    # ── howto (physical/life task) ───────────────────────────────────────────
    ("how to tie a tie",                                         "howto knot tie"),
    ("how to bake a chocolate cake",                             "howto bake cake chocolate"),
    ("how to plant a tree",                                      "howto plant soil tree"),
    ("how to dice an onion",                                     "howto cut onion"),
    ("how to perform cpr",                                       "howto adult cpr"),

    # ── best (opinion) ───────────────────────────────────────────────────────
    ("best programming language for machine learning",           "best language ml programming"),
    ("which car brand is the best",                              "best brand car"),
    ("best app for productivity",                                "best app productivity"),
    ("which streaming service is the best",                      "best service streaming"),

    # ── history (person/date answer) ─────────────────────────────────────────
    ("who invented the internet",                                "history internet invention"),
    ("who wrote romeo and juliet",                               "history juliet romeo"),
    ("when did world war 2 end",                                 "history end war ww2"),
    ("who was the first person in space",                        "history first person space"),

    # ── define (vocabulary lookup) ───────────────────────────────────────────
    ("what does entropy mean",                                   "define entropy meaning"),
    ("definition of recursion",                                  "define meaning recursion"),

    # ── list (enumeration) ───────────────────────────────────────────────────
    ("list all planets in the solar system",                     "list planet solar system"),
    ("what are the python data types",                           "list data python type"),

    # ── debug (troubleshoot) ─────────────────────────────────────────────────
    ("my postgres query is slow",                                "debug database query slow"),
    ("react component not rendering",                            "debug component react render"),

    # ── summarize ────────────────────────────────────────────────────────────
    ("summarize the theory of relativity",                       "summarize relativity theory"),
]

CONFIG = {
    "name": "v11_grammar_universal_gemma_e2b",
    "description": "Grammar-constrained output (GBNF) + alphabetical post-sort + stem-pattern few-shots, Gemma 4 E2B",
    "enabled": False,
    "loader": {
        "repo_id": "unsloth/gemma-4-E2B-it-GGUF",
        "filename": "gemma-4-E2B-it-Q4_K_M.gguf",
        "n_ctx": 8192,
    },
    "inference": {
        "max_tokens": 24,
        "temperature": 0.0,
    },
    "grammar": _GRAMMAR,
    "system_prompt": _SYSTEM_PROMPT,
    "few_shots": _FEW_SHOTS,
}
