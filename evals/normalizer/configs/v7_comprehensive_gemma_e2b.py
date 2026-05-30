"""v7: comprehensive prompt addressing all observed failure classes.

Failure classes addressed vs v6:
1. Synonym divergence — explicit lookup table: sew/reattach/stitch→sew,
   dice/cut/chop→cut, app/application/tool/software→app,
   CPR/cardiopulmonary resuscitation→cpr, fossil fuels→non-renewable energy,
   largest/biggest/most landmass→largest. Always prefer the shorter/more
   common form.
2. Over/under topic keyword inclusion — rule: always keep the core subject noun
   from the question. Never drop the primary topic word (planet, ocean, space).
3. Intent flip on same concept — explicit rules for ambiguous phrasings:
   "how does X differ from Y" / "difference between" → compare (not explain),
   "what is the best way to do [physical task]" → howto (not best),
   "X vs Y" when asking neutrally → compare.
4. Extraneous context keywords — rule: drop situational modifiers that don't
   define the topic ("in my yard", "for cooking", "young", "on my shirt").
5. define leaking into explain — stricter rule with more examples. "what is a
   black hole" = process/concept → explain. "what does X mean" = vocabulary → define.
6. Abbreviations — always use the SHORT canonical form. Full names → abbreviation.
7. SQL/code intent — "what is the X command/syntax/function" → create not explain/howto.
"""

_SYSTEM_PROMPT = """\
You are a query canonicalizer. Convert any user query into a deterministic \
keyword bag so semantically equivalent queries produce IDENTICAL output.

OUTPUT FORMAT (strict):
- Lowercase only
- Space-separated keywords
- Alphabetically sorted
- Remove stopwords (the/a/an/of/in/on/at/to/for/and/or/is/are/do/does/did/was/were/my/your/our/its)
- Remove filler (please, can you, I want, tell me, yo, hey, lol, actually, right, just, give me, show me, teach me, guide me, walk me through, name the, let me know)
- Remove incidental context modifiers (young, old, simple, basic, quick, proper, efficient, step-by-step, from scratch, like a pro, in my yard, for cooking, on my shirt, at home)
- Fix obvious typos and misspellings
- 2 to 7 keywords maximum
- Output ONLY the bag. No prefix, no explanation, no quotes.

SYNONYM CANONICALIZATION — always prefer the listed canonical form:
  app           ← application, tool, software, program, platform
  cut           ← dice, chop, slice, mince (for food preparation)
  sew           ← reattach, stitch, attach (for fabric/clothing)
  cpr           ← cardiopulmonary resuscitation
  tcp           ← transmission control protocol
  udp           ← user datagram protocol
  non-renewable ← fossil fuels, fossil fuel
  largest       ← biggest, greatest, most landmass, highest, tallest (superlatives)
  workout       ← exercise routine, fitness regimen, training plan
  invest        ← investing, investment strategy, financial planning (money growth topic)

ABBREVIATION RULE — always use the short form when both forms appear:
  Examples: "cardiopulmonary resuscitation" → cpr, "Transmission Control Protocol" → tcp,
  "User Datagram Protocol" → udp, "Artificial Intelligence" → ai, "Machine Learning" → ml,
  "Application Programming Interface" → api, "User Interface" → ui

INTENT WORDS — exactly one per output:
  explain  → how does X work, what is X (concept/process/mechanism), explain X,
             describe X, where is X (location facts), what causes X,
             "what is a [thing that has behavior or structure]"
  why      → why did/is/are X happen/occur/exist
  create   → write/generate/build/make X code, how to use X (library/API/command),
             X code example, implement X pattern, what is the X command/syntax/function
  compare  → X vs Y (neutral), difference between X and Y, how does X differ from Y,
             how do X and Y compare, compare X and Y, when to use X vs Y,
             X compared to Y, X or Y (when asking for differences, not preference)
  define   → definition of X, what does X mean (vocabulary term only, NOT a concept
             with behavior). ONLY use define for pure vocabulary lookups.
  history  → who invented/discovered X, when did X happen, date of X, origin of X,
             who was the first to X, who led/created X
  best     → best X for Y, recommend X, which X should I use, most useful X,
             what is the greatest/top X, which X is considered the best,
             "what is the best way to [achieve a goal/outcome]" (not a task)
  howto    → how to do X (non-code physical/life task), steps to X, recipe for X,
             "what is the best way to [perform a physical task like cooking/fixing]"

CRITICAL DISAMBIGUATION RULES:
1. ALL code requests → create. This includes: "how to use [library/API]",
   "[language] [thing] example", "what is the [SQL/code] command to X",
   "how do I query/fetch/connect/implement in [language]".
2. "How does X differ from Y" / "difference between X and Y" / "X compared to Y"
   → compare (NOT explain, even if phrased as "how does").
3. "What is the best way to [cook/fix/build/clean/physical task]" → howto.
   "What is the best [thing to own/use/watch/eat]" → best.
4. "What is a/the [concept with structure or behavior]" → explain (not define).
   "What does [word] mean" / "define [word]" → define.
5. Always keep the PRIMARY TOPIC NOUN. Never drop the word that names the subject
   (planet, ocean, space, river, building). Modifiers like "coldest", "largest",
   "tallest" are also important — keep them when they ARE the question.
6. Drop incidental modifiers that come from the phrasing style, not the topic:
   "in my yard", "for cooking", "on my shirt", "young tree", "at home" — these
   don't define the topic. Keep only words that would appear in every phrasing.
7. When one phrasing uses a synonym, canonicalize to the form in the SYNONYM table.
8. Different phrasings of the same question MUST produce byte-identical output.\
"""

_FEW_SHOTS = [
    # ── why ─────────────────────────────────────────────────────────────────
    ("why is russia at war with ukraine?",                       "russia ukraine war why"),
    ("why are they at war with ukrine",                          "russia ukraine war why"),
    ("what caused the russia ukraine conflict",                  "russia ukraine war why"),
    ("why did the roman empire fall?",                           "rome empire fall why"),
    ("causes of the fall of rome",                               "rome empire fall why"),
    ("what led to the collapse of ancient rome?",                "rome empire fall why"),
    ("why is the sky blue",                                      "blue sky why"),
    ("what makes the sky appear blue?",                         "blue sky why"),
    ("why does the sky have a blue color?",                      "blue sky why"),

    # ── explain ─────────────────────────────────────────────────────────────
    ("how does photosynthesis work",                             "explain photosynthesis"),
    ("can you explain photosynthesis to me",                     "explain photosynthesis"),
    ("explain the process of photosynthesis",                    "explain photosynthesis"),
    ("how does gravity work?",                                   "explain gravity"),
    ("explain the concept of gravity",                           "explain gravity"),
    ("what causes gravitational pull?",                          "explain gravity"),
    ("what is a black hole?",                                    "black explain holes"),
    ("how are black holes formed?",                              "black explain holes"),
    ("explain the event horizon of a black hole",                "black explain holes"),
    # explain: location is a fact lookup → explain
    ("what's the capital of france",                             "capital explain france"),
    ("tell me france's capital city",                            "capital explain france"),
    ("which city is the capital of france",                      "capital explain france"),
    ("where is the mariana trench located?",                     "explain mariana trench"),
    ("what is the deepest ocean on earth?",                      "deep explain ocean"),
    ("how deep is the pacific ocean?",                           "deep explain ocean"),
    # explain: "what is a [thing with structure/behavior]" NOT define
    ("what is a blockchain?",                                    "blockchain explain"),
    ("how does blockchain technology work?",                     "blockchain explain"),
    ("explain the concept of a decentralized ledger",            "blockchain explain"),
    ("what is quantum supremacy?",                               "explain quantum computing"),
    ("explain quantum computing simply",                         "explain quantum computing"),
    ("how do quantum computers work?",                           "explain quantum computing"),
    # explain: magnetism — different topic words all refer to same concept
    ("what causes magnetism?",                                   "explain magnetism"),
    ("explain how magnetic fields work",                         "explain magnetism"),
    ("why do magnets attract and repel each other?",             "explain magnetism"),
    # explain: superlative factual — keep the superlative word
    ("which planet is the coldest?",                             "coldest explain planet"),
    ("what is the chilliest planet orbiting our sun?",           "coldest explain planet"),
    ("name the solar system's coldest planet",                   "coldest explain planet"),
    ("which ocean is the largest on earth?",                     "explain largest ocean"),
    ("what is the biggest ocean in the world?",                  "explain largest ocean"),
    ("name the largest body of water on the planet",             "explain largest ocean"),
    ("what is the tallest building in the world?",               "building explain largest"),
    ("which skyscraper is the highest?",                         "building explain largest"),
    ("where is the burj khalifa?",                               "building explain largest"),
    ("what is the longest river in the world?",                  "explain longest river"),
    ("name the longest river on earth",                          "explain longest river"),
    ("is the nile or amazon river longer?",                      "explain longest river"),

    # ── define (vocabulary ONLY) ─────────────────────────────────────────────
    ("what does entropy mean",                                   "define entropy"),
    ("what is a monad",                                          "define monad"),
    ("definition of recursion in programming",                   "define recursion"),
    ("what does API stand for?",                                 "api define"),
    ("what does the word 'algorithm' mean?",                     "algorithm define"),

    # ── history ─────────────────────────────────────────────────────────────
    ("who discovered photosynthesis",                            "history photosynthesis"),
    ("what is the history of photosynthesis",                    "history photosynthesis"),
    ("who first described the process of photosynthesis",        "history photosynthesis"),
    ("who invented the internet?",                               "history internet"),
    ("when was the world wide web created?",                     "history internet"),
    ("history of how the internet started",                      "history internet"),
    # history: person/explorer questions — keep person + event keywords
    ("who is credited with discovering the americas in 1492?",   "americas discovery history"),
    ("who led the spanish expedition that landed in the americas in 1492?", "americas discovery history"),
    ("name the explorer who sailed the ocean blue in 1492",      "americas discovery history"),
    # history: space — keep space + first person keywords
    ("who was the first human being to travel into space?",      "first history person space"),
    ("name the first astronaut/cosmonaut in outer space",        "first history person space"),
    ("who achieved the milestone of being the first person in space?", "first history person space"),

    # ── create (ALL code — including "how to use", "example", "command") ─────
    ("write a python function to reverse a linked list",         "create function linked list python reverse"),
    ("can you write me a python function for reversing a linked list", "create function linked list python reverse"),
    ("python function that reverses a linked list",              "create function linked list python reverse"),
    ("write a golang goroutine example",                         "create go goroutine"),
    ("how to use concurrency in go",                             "create go goroutine"),
    ("go language channel and goroutine code",                   "create go goroutine"),
    ("write a javascript fetch request",                         "create fetch javascript"),
    ("how to use fetch api in js",                               "create fetch javascript"),
    ("example of fetch api in javascript",                       "create fetch javascript"),
    # create: SQL — "what is the command" = create not explain
    ("how do I query all columns from a table in sql?",          "create select sql"),
    ("write a sql statement to retrieve every record from a table", "create select sql"),
    ("what is the sql command to select everything from a table?", "create select sql"),
    # create: react hooks
    ("how do you use the usestate hook in a react component?",   "create react usestate"),
    ("write a simple react component demonstrating usestate",    "create react usestate"),
    ("show me how to declare and update state in react using hooks", "create react usestate"),

    # ── howto (non-code physical/life tasks) ─────────────────────────────────
    ("how to set up a redis cluster",                            "cluster howto redis"),
    ("steps to configure redis replication",                     "cluster howto redis"),
    ("how do I set up redis clustering",                         "cluster howto redis"),
    ("how to tie a tie",                                         "howto tie"),
    ("steps to tie a necktie",                                   "howto tie"),
    ("what is the best way to tie a tie?",                       "howto tie"),
    ("how to bake a chocolate cake",                             "bake cake howto"),
    ("recipe for baking a chocolate cake",                       "bake cake howto"),
    ("steps to make a chocolate cake from scratch",              "bake cake howto"),
    # howto: synonym canonicalization (cut ← dice/chop/slice)
    ("what is the most efficient way to dice an onion?",         "cut howto onion"),
    ("how should I cut an onion for cooking?",                   "cut howto onion"),
    ("tell me the proper technique for chopping onions",         "cut howto onion"),
    # howto: sew canonicalization (sew ← reattach/stitch)
    ("how do I sew a fallen button back onto my shirt?",         "button howto sew"),
    ("what are the steps to reattach a button with a needle and thread?", "button howto sew"),
    ("teach me how to sew on a button",                          "button howto sew"),
    # howto: cpr canonicalization (cpr ← cardiopulmonary resuscitation)
    ("how do you perform cpr on an adult?",                      "cpr howto"),
    ("what are the steps for administering cardiopulmonary resuscitation?", "cpr howto"),
    ("guide me through the process of doing cpr",                "cpr howto"),
    # howto: drop incidental modifiers
    ("what is the proper way to plant a tree?",                  "howto plant tree"),
    ("how do I go about planting a tree in my yard?",            "howto plant tree"),
    ("give me a step-by-step guide to planting a tree",          "howto plant tree"),

    # ── compare (neutral — includes "how does X differ from Y") ──────────────
    ("rust vs go for systems programming",                       "compare go rust"),
    ("what's the difference between rust and go",                "compare go rust"),
    ("how does rust compare to go for systems software?",        "compare go rust"),
    ("sql vs nosql databases",                                   "compare nosql sql"),
    ("what's the difference between sql and nosql?",             "compare nosql sql"),
    ("how do nosql and sql databases differ?",                   "compare nosql sql"),
    # compare: tcp/udp with abbreviation canonicalization
    ("what are the technical differences between tcp and udp protocols?", "compare tcp udp"),
    ("compare the transmission control protocol with the user datagram protocol", "compare tcp udp"),
    ("how do udp and tcp differ in networking?",                 "compare tcp udp"),
    # compare: non-renewable canonicalization (fossil fuels → non-renewable)
    ("what is the difference between renewable and non-renewable energy sources?", "compare energy non-renewable renewable"),
    ("compare fossil fuels with renewable energy",               "compare energy non-renewable renewable"),
    ("how do renewable resources differ from non-renewable ones?", "compare energy non-renewable renewable"),
    # compare: "how does X differ" → compare not explain
    ("what is the difference between renting and buying a home?", "compare buying home renting"),
    ("compare homeownership to renting",                         "compare buying home renting"),
    ("how does renting a property differ from owning one?",      "compare buying home renting"),
    # compare: cardio vs weightlifting
    ("what is the difference between cardiovascular exercise and strength training?", "compare cardio workout"),
    ("compare weightlifting to cardio workouts",                 "compare cardio workout"),
    ("how does aerobic exercise differ from lifting weights?",   "compare cardio workout"),
    # compare: personality types — sub-topic stays under parent concept
    ("introvert vs extrovert personality types",                 "compare extrovert introvert personality"),
    ("what's the difference between an introvert and an extrovert?", "compare extrovert introvert personality"),
    ("can someone be an ambivert?",                              "compare extrovert introvert personality"),

    # ── best (opinion / preference) ──────────────────────────────────────────
    ("what's the best programming language for machine learning", "best language ml"),
    ("which programming language should I use for ml",           "best language ml"),
    ("best language for machine learning projects",              "best language ml"),
    ("what is the best app for productivity?",                   "best app productivity"),
    ("which productivity tool is the absolute best?",            "best app productivity"),
    ("what is your top recommendation for a task management app?", "best app productivity"),
    ("what would be the best superpower to have?",               "best superpower"),
    ("what is arguably the greatest superhuman ability to have?", "best superpower"),
    ("which superpower is the ultimate one to possess?",         "best superpower"),
    ("what is the best pet to own?",                             "best pet"),
    ("are dogs better pets than cats?",                          "best pet"),
    ("best animals for apartment living",                        "best pet"),
    # best: workout → best (goal-oriented), NOT howto (not a task)
    ("what is the optimal exercise routine for overall health?", "best workout"),
    ("which workout plan do you recommend as the best?",         "best workout"),
    ("what is the greatest overall fitness regimen to follow?",  "best workout"),
    # best: investment
    ("what is the greatest approach to investing your money?",   "best invest"),
    ("which investment strategy do you recommend above all others?", "best invest"),
    ("what is the absolute best way to invest for the future?",  "best invest"),
    # best: time to wake up — keep core topic words
    ("what is the most ideal time of day to wake up in the morning?", "best time wake"),
    ("when is the absolute best time to set your alarm for?",    "best time wake"),
    ("what wake-up time is most highly recommended for a good day?", "best time wake"),
]

CONFIG = {
    "name": "v7_comprehensive_gemma_e2b",
    "description": "Comprehensive synonym canonicalization + intent disambiguation + topic preservation, Gemma 4 E2B",
    "enabled": False,
    "loader": {
        "repo_id": "unsloth/gemma-4-E2B-it-GGUF",
        "filename": "gemma-4-E2B-it-Q4_K_M.gguf",
        "n_ctx": 8192,
    },
    "inference": {
        "max_tokens": 48,
        "temperature": 0.0,
    },
    "system_prompt": _SYSTEM_PROMPT,
    "few_shots": _FEW_SHOTS,
}
