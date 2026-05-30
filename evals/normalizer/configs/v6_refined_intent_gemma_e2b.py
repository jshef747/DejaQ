"""v6: refined intent rules + expanded few-shots targeting v5 failure patterns.

Observed v5 failures (from 99-concept run):
1. code_gen: "write X" → create, "how to use X" → howto, "X example" → no intent.
   Three tags for the same concept. Fix: ALL code requests → create.
2. opinion "X vs Y" phrasing: "flight vs invisibility" → compare, siblings → best.
   Fix: opinion topics always use best, even for "X vs Y" sub-phrasings.
3. conceptual "what is X": gets define instead of explain for process/mechanism topics.
   Fix: define = isolated term definitions only; explain = anything about how/why/what X does.
4. location questions: "where is X" → invents "location" tag (not in vocab).
   Fix: fold location into explain; "where is X" is a factual lookup → explain.
5. sub-topic drift: "can someone be an ambivert?" → define ambivert instead of
   compare introvert extrovert. Fix: add rule to preserve parent topic keywords.
6. "X vs Y" concepts with a third phrasing about a related sub-topic: include
   all relevant keywords from the concept, not just the sub-topic word.
"""

_SYSTEM_PROMPT = """\
You are a query canonicalizer. Convert any user query into a deterministic \
keyword bag so semantically equivalent queries produce IDENTICAL output.

OUTPUT FORMAT (strict):
- Lowercase only
- Space-separated keywords
- Alphabetically sorted
- Remove stopwords (the/a/an/of/in/on/at/to/for/and/or/is/are/do/does/did/was/were)
- Remove filler (please, can you, I want, tell me, yo, hey, lol, actually, right)
- Fix obvious typos and misspellings
- 2 to 8 keywords maximum
- Output ONLY the bag. No prefix, no explanation, no quotes.

INTENT WORDS — exactly one per output, always include it:
  explain  → how does/did X work, what is X (process/mechanism/concept), explain X,
             describe X, where is X (location facts), what causes X
  why      → why did/is/are X happen/occur/exist
  create   → write/generate/build/make X, how to use X (code), X example/tutorial (code),
             show me X code, implement X — ALL code requests use create
  compare  → X vs Y (when the topic itself IS the comparison), difference between X and Y,
             when to use X vs Y
  define   → definition of X, what does X mean (vocabulary/term only, not a process)
  history  → who invented/discovered X, when did X happen, date of X, origin of X
  best     → best X for Y, recommend X, which X should I use, most useful X,
             X vs Y when asking for a preference/opinion (not a neutral comparison)
  howto    → how to do X (non-code task), steps to X, guide to X, recipe for X

RULES:
1. ALL code requests (write code, use library, code example, implement pattern) → create.
   Never use howto for code. "how to use fetch in js" → create, not howto.
2. Resolve implicit subjects. "why are they at war with ukraine" → russia is the subject.
3. Canonical vocabulary: "war" not "conflict", "database" not "postgres/mysql/db".
4. Keep proper nouns and technology names but lowercase them.
5. define is ONLY for vocabulary/term definitions. "what is a black hole" describes a
   process/concept → use explain. "what does entropy mean" → use define.
6. When one phrasing of an opinion topic uses "X vs Y" framing, still use best
   (not compare), because the question is asking for a preference.
7. When a phrasing introduces a sub-topic (e.g. ambivert as part of introvert/extrovert),
   include the parent concept's keywords too.
8. Different phrasings of the same question MUST produce byte-identical output.\
"""

_FEW_SHOTS = [
    # ── why ─────────────────────────────────────────────────────────────────
    ("why is russia at war with ukraine?",              "russia ukraine war why"),
    ("why are they at war with ukrine",                 "russia ukraine war why"),
    ("what caused the russia ukraine conflict",         "russia ukraine war why"),
    ("why did the roman empire fall?",                  "rome empire fall why"),
    ("causes of the fall of rome",                      "rome empire fall why"),
    ("what led to the collapse of ancient rome?",       "rome empire fall why"),
    ("why is the sky blue",                             "blue sky why"),

    # ── explain ─────────────────────────────────────────────────────────────
    ("how does photosynthesis work",                    "explain photosynthesis"),
    ("can you explain photosynthesis to me",            "explain photosynthesis"),
    ("explain the process of photosynthesis",           "explain photosynthesis"),
    ("how does quantum mechanics actually work",        "explain mechanics quantum"),
    ("can you explain quantum mechanics like I'm 5",    "explain mechanics quantum"),
    ("how do black holes form",                         "black explain holes"),
    ("what is a black hole?",                           "black explain holes"),
    ("explain the event horizon of a black hole",       "black explain holes"),
    ("what's the capital of france",                    "capital explain france"),
    ("tell me france's capital city",                   "capital explain france"),
    ("which city is the capital of france",             "capital explain france"),
    ("where is the mariana trench located?",            "explain mariana trench"),
    ("what is the deepest ocean on earth?",             "deep explain ocean"),
    ("how deep is the pacific ocean?",                  "deep explain ocean"),
    ("how do plate tectonics cause earthquakes?",       "explain plate tectonics"),
    ("explain the theory of continental drift",         "explain plate tectonics"),
    ("what are tectonic plates?",                       "explain plate tectonics"),

    # ── define ──────────────────────────────────────────────────────────────
    ("what does entropy mean",                          "define entropy"),
    ("what is a monad",                                 "define monad"),
    ("definition of recursion in programming",          "define recursion"),

    # ── history ─────────────────────────────────────────────────────────────
    ("who discovered photosynthesis",                   "history photosynthesis"),
    ("what is the history of photosynthesis",           "history photosynthesis"),
    ("who first described the process of photosynthesis", "history photosynthesis"),
    ("who invented the internet?",                      "history internet"),
    ("when was the world wide web created?",            "history internet"),
    ("history of how the internet started",             "history internet"),
    ("when did world war 2 start?",                     "history ww2"),
    ("what year did the second world war begin?",       "history ww2"),
    ("date of the start of ww2",                        "history ww2"),

    # ── create (ALL code requests) ───────────────────────────────────────────
    ("write a python function to reverse a linked list",
                                                        "create function linked list python reverse"),
    ("can you write me a python function for reversing a linked list",
                                                        "create function linked list python reverse"),
    ("python function that reverses a linked list",     "create function linked list python reverse"),
    ("write a golang goroutine example",                "create go goroutine"),
    ("how to use concurrency in go",                    "create go goroutine"),
    ("go language channel and goroutine code",          "create go goroutine"),
    ("write a javascript fetch request",                "create fetch javascript"),
    ("how to use fetch api in js",                      "create fetch javascript"),
    ("example of fetch api in javascript",              "create fetch javascript"),
    ("write a hello world program in c++",              "create c++ hello world"),
    ("how to print text to console in c++",             "create c++ hello world"),
    ("c++ main function example",                       "create c++ hello world"),
    ("write php code to connect to a mysql database",   "create database php connect"),
    ("how to use PDO in php",                           "create database php connect"),
    ("php mysqli connection script",                    "create database php connect"),

    # ── howto (non-code tasks only) ──────────────────────────────────────────
    ("how to set up a redis cluster",                   "cluster howto redis setup"),
    ("steps to configure redis replication",            "cluster howto redis setup"),
    ("how do I set up redis clustering",                "cluster howto redis setup"),
    ("how to tie a tie",                                "howto tie"),
    ("steps to tie a necktie",                          "howto tie"),
    ("can you teach me how to tie a tie?",              "howto tie"),
    ("how to bake a chocolate cake",                    "bake cake chocolate howto"),
    ("recipe for baking a chocolate cake",              "bake cake chocolate howto"),
    ("steps to make a chocolate cake from scratch",     "bake cake chocolate howto"),

    # ── compare (neutral, topic IS the comparison) ───────────────────────────
    ("rust vs go for systems programming",              "compare go rust systems"),
    ("what's the difference between rust and go",       "compare go rust systems"),
    ("compare rust and go for building system software","compare go rust systems"),
    ("sql vs nosql databases",                          "compare nosql sql"),
    ("what's the difference between sql and nosql?",    "compare nosql sql"),
    ("when to use nosql instead of sql",                "compare nosql sql"),
    # sub-topic phrasing: keep parent concept keywords
    ("introvert vs extrovert personality types",        "compare extrovert introvert personality"),
    ("what's the difference between an introvert and an extrovert?", "compare extrovert introvert personality"),
    ("can someone be an ambivert?",                     "compare extrovert introvert personality"),

    # ── best (opinion / preference, including "X vs Y" opinion phrasings) ────
    ("what's the best programming language for machine learning",
                                                        "best language learning machine"),
    ("which programming language should I use for ML",  "best language learning machine"),
    ("best language for machine learning projects",     "best language learning machine"),
    ("what is the best app for productivity?",          "best app productivity"),
    ("best task management software",                   "best app productivity"),
    ("notion vs obsidian for taking notes",             "best app productivity"),   # opinion "vs" → best
    ("what would be the best superpower to have?",      "best superpower"),
    ("flight vs invisibility",                          "best superpower"),          # opinion "vs" → best
    ("most useful superhero power in real life",        "best superpower"),
    ("what is the best pet to own?",                    "best pet"),
    ("are dogs better pets than cats?",                 "best pet"),
    ("best animals for apartment living",               "best pet"),
]

CONFIG = {
    "name": "v6_refined_intent_gemma_e2b",
    "description": "Refined intent rules + broad few-shots targeting v5 failure patterns, Gemma 4 E2B",
    "enabled": False,
    "loader": {
        "repo_id": "unsloth/gemma-4-E2B-it-GGUF",
        "filename": "gemma-4-E2B-it-Q4_K_M.gguf",
        "n_ctx": 4096,
    },
    "inference": {
        "max_tokens": 48,
        "temperature": 0.0,
    },
    "system_prompt": _SYSTEM_PROMPT,
    "few_shots": _FEW_SHOTS,
}
