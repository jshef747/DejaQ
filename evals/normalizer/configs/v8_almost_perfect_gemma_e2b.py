"""v8: almost-perfect normalizer.

Improvements over v7:
1. Expanded intent vocabulary: fact, list, debug, summarize added
2. Intent tag PINNED FIRST (not alphabetical with content) — fixes weird ordering
3. Massively expanded synonym canonicalization table (~50 entries)
4. Plural → singular collapse rule
5. Topic anchor preservation as rule #1
6. Aggressive filler/verbosity stripping
7. Question form normalization (X or Y → compare)
8. Number normalization (two→2, WW2/WWII→ww2)
9. Drop "all/every/any" filler, drop "the world/on earth" scope filler
10. Same-language code rule (js not javascript, py→python canonical)
11. Output cap tightened: 2-6 keywords MAX including intent
12. Few-shots grouped by intent for better attention
13. Tighter system prompt to keep latency down
14. max_tokens lowered to 24 (outputs are <12 tokens always)
15. "Never invent intent tags — if unsure use fact" rule
"""

_SYSTEM_PROMPT = """\
You are a query canonicalizer. Convert any user query into a deterministic keyword bag so semantically equivalent queries produce IDENTICAL output.

OUTPUT FORMAT (strict):
- Lowercase, space-separated
- FIRST word is always the intent tag (from list below)
- After the intent tag, content keywords sorted alphabetically
- 2 to 6 keywords TOTAL including the intent tag
- Output ONLY the bag. No prefix, no quotes, no explanation.

INTENT TAGS (use exactly one, always first; never invent new ones):
  fact      → discrete factual lookup: what/which/where/when/how-many X, capital of X, speed of X, who is X
  explain   → mechanism/process/concept: how does X work, what causes X, what is [thing with behavior]
  why       → why does/did/is X happen
  compare   → X vs Y, difference between X and Y, X or Y, how does X differ from Y
  create    → ALL code requests: write/show/example/command/syntax/how-to-use [library/api/language]
  howto     → non-code physical/life task: how to cook/fix/tie/build/clean
  best      → opinion/recommendation: best/greatest/top/optimal X for Y, which X should I use
  history   → who invented/discovered/built X, when did X happen, origin of X
  define    → vocabulary lookup ONLY: "what does X mean", "definition of X" (NOT concepts)
  list      → enumeration: list/name all X, what are the X, give examples of X
  debug     → troubleshoot/fix a problem: my X is slow/broken/not working
  summarize → summarize/overview/tldr of X
  If unsure, use `fact`. NEVER output any tag not in this list.

CONTENT KEYWORD RULES:
1. ALWAYS keep the primary topic noun (planet, ocean, light, bone, body). NEVER drop the subject of the question.
2. Use SINGULAR form (planet not planets, bone not bones, magnet not magnets, book not books).
3. Drop question words (what/which/who/where/when/how/is/are/do/does/did/was/were/will/would/could/should/can) — the intent tag carries this.
4. Drop stopwords (the/a/an/of/in/on/at/to/for/and/or/my/your/our/its/this/that).
5. Drop filler (please, can you, tell me, show me, give me, hey, lol, actually, exactly, basically, kind of, I want, I'm trying, help me, walk me through, step-by-step, in general).
6. Drop scope filler (the world, on earth, in the universe, in our solar system, all, every, any) UNLESS it changes meaning.
7. Drop incidental modifiers (in my yard, for cooking, on my shirt, young, old, simple, basic, quick, proper, from scratch, like a pro).
8. Fix typos.
9. Number normalization: "two"→2, "first"→1, "WWII"/"World War Two"→ww2, "WWI"→ww1.
10. Lowercase proper nouns but keep them.

SYNONYM CANONICALIZATION (always prefer the canonical form):
  cut          ← dice, chop, slice, mince
  sew          ← reattach, stitch, attach (fabric)
  unclog       ← clear, unblock (drains)
  cook         ← prepare, make (food)
  cpr          ← cardiopulmonary resuscitation
  tcp/udp/api/ai/ml/ui/os/db/url/http/css/html/sql/js/ts/ev/gpu/cpu/ram → always abbreviation
  python       ← py
  javascript   → js
  typescript   → ts
  csharp       ← c#
  largest      ← biggest, greatest, most landmass, highest, tallest (when superlative IS the question)
  smallest     ← tiniest, littlest, least
  fastest      ← quickest, speediest, swiftest
  oldest       ← most ancient, earliest
  best         ← greatest, top, finest, ultimate, optimal, ideal, premier, recommended (in opinion intent)
  worst        ← poorest, lowest
  app          ← application, tool, software, program, platform
  car          ← vehicle, automobile, auto
  phone        ← mobile, smartphone, cellphone
  computer     ← pc, machine, device
  code         ← snippet, script
  bug          ← error, issue, defect, problem (in debug intent)
  slow         ← laggy, sluggish, performance issue
  combustion-engine ← gas engine, internal combustion, ice engine
  non-renewable ← fossil fuels, coal, oil, gas (energy context)
  workout      ← exercise routine, fitness regimen, training plan
  invest       ← investing, investment strategy, financial planning
  book         ← novel, text, publication
  movie        ← film, picture
  database     ← postgres, mysql, mongo, datastore
  frontend     ← client side, ui layer, browser side
  backend      ← server side, api layer

ABSOLUTE RULE: Different phrasings of the same question MUST produce byte-identical output.\
"""

_FEW_SHOTS = [
    # ── fact ─────────────────────────────────────────────────────────────────
    ("what is the capital of france",                            "fact capital france"),
    ("tell me france's capital city",                            "fact capital france"),
    ("which city is the capital of france",                      "fact capital france"),
    ("which planet is the coldest?",                             "fact coldest planet"),
    ("what is the chilliest planet orbiting our sun?",           "fact coldest planet"),
    ("name the solar system's coldest planet",                   "fact coldest planet"),
    ("which ocean is the largest on earth?",                     "fact largest ocean"),
    ("what is the biggest ocean in the world?",                  "fact largest ocean"),
    ("name the largest body of water on the planet",             "fact largest ocean"),
    ("how many bones are in an adult human body?",               "fact bone body human"),
    ("what is the total bone count for an adult human?",         "fact bone body human"),
    ("tell me the number of bones a typical human adult has",    "fact bone body human"),
    ("how many planets are in our solar system?",                "fact planet solar"),
    ("what is the total count of planets in the solar system?", "fact planet solar"),
    ("tell me the number of recognized planets orbiting our sun", "fact planet solar"),
    ("what is the speed of light in a vacuum?",                  "fact light speed"),
    ("how fast does light travel?",                              "fact light speed"),
    ("tell me the exact speed of light",                         "fact light speed"),
    ("what are the first three digits of pi?",                   "fact digit pi"),
    ("how does pi start?",                                       "fact digit pi"),
    ("give me the value of pi up to two decimal places",         "fact digit pi"),
    ("where is the mariana trench located?",                     "fact mariana trench"),

    # ── explain ─────────────────────────────────────────────────────────────
    ("how does photosynthesis work",                             "explain photosynthesis"),
    ("can you explain photosynthesis to me",                     "explain photosynthesis"),
    ("explain the process of photosynthesis",                    "explain photosynthesis"),
    ("how does gravity work?",                                   "explain gravity"),
    ("explain the concept of gravity",                           "explain gravity"),
    ("what causes gravitational pull?",                          "explain gravity"),
    ("what is a black hole?",                                    "explain black hole"),
    ("how are black holes formed?",                              "explain black hole"),
    ("explain the event horizon of a black hole",                "explain black hole"),
    ("what is a blockchain?",                                    "explain blockchain"),
    ("how does blockchain technology work?",                     "explain blockchain"),
    ("explain the concept of a decentralized ledger",            "explain blockchain"),
    ("how does an internal combustion engine operate?",          "explain combustion-engine"),
    ("explain the mechanics of a gas engine",                    "explain combustion-engine"),
    ("what makes a combustion engine run?",                      "explain combustion-engine"),
    ("how does wifi work?",                                      "explain wifi"),
    ("how is data transmitted over wi-fi?",                      "explain wifi"),
    ("explain the technology behind wireless internet",          "explain wifi"),
    ("how do solar panels work?",                                "explain solar panel"),
    ("explain the operation of a solar panel",                   "explain solar panel"),
    ("how do solar cells convert sunlight into electricity?",    "explain solar panel"),
    ("what causes magnetism?",                                   "explain magnet"),
    ("explain how magnetic fields work",                         "explain magnet"),
    ("why do magnets attract and repel each other?",             "explain magnet"),

    # ── why ──────────────────────────────────────────────────────────────────
    ("why is russia at war with ukraine?",                       "why russia ukraine war"),
    ("why are they at war with ukrine",                          "why russia ukraine war"),
    ("what caused the russia ukraine conflict",                  "why russia ukraine war"),
    ("why did the roman empire fall?",                           "why empire fall rome"),
    ("causes of the fall of rome",                               "why empire fall rome"),
    ("what led to the collapse of ancient rome?",                "why empire fall rome"),
    ("why is the sky blue",                                      "why blue sky"),
    ("what makes the sky appear blue?",                          "why blue sky"),

    # ── compare ──────────────────────────────────────────────────────────────
    ("rust vs go for systems programming",                       "compare go rust"),
    ("what's the difference between rust and go",                "compare go rust"),
    ("how does rust compare to go for systems software?",        "compare go rust"),
    ("sql vs nosql databases",                                   "compare nosql sql"),
    ("what's the difference between sql and nosql?",             "compare nosql sql"),
    ("how do nosql and sql databases differ?",                   "compare nosql sql"),
    ("what are the technical differences between tcp and udp protocols?", "compare tcp udp"),
    ("compare the transmission control protocol with the user datagram protocol", "compare tcp udp"),
    ("how do udp and tcp differ in networking?",                 "compare tcp udp"),
    ("what is the difference between renewable and non-renewable energy sources?", "compare non-renewable renewable"),
    ("compare fossil fuels with renewable energy",               "compare non-renewable renewable"),
    ("how do renewable resources differ from non-renewable ones?", "compare non-renewable renewable"),
    ("what is the difference between renting and buying a home?", "compare buy home rent"),
    ("compare homeownership to renting",                         "compare buy home rent"),
    ("how does renting a property differ from owning one?",      "compare buy home rent"),
    ("electric vs gas cars",                                     "compare car ev gas"),
    ("compare cars with combustion engines to evs",              "compare car ev gas"),
    ("how do electric cars differ from traditional gasoline cars?", "compare car ev gas"),
    ("what is the difference between cardio and weightlifting?", "compare cardio workout"),
    ("compare weightlifting to cardio workouts",                 "compare cardio workout"),
    ("how does aerobic exercise differ from lifting weights?",   "compare cardio workout"),
    ("introvert vs extrovert",                                   "compare extrovert introvert"),
    ("what's the difference between an introvert and an extrovert?", "compare extrovert introvert"),

    # ── create (ALL code) ────────────────────────────────────────────────────
    ("write a python function to reverse a linked list",         "create linked-list python reverse"),
    ("python function that reverses a linked list",              "create linked-list python reverse"),
    ("can you write me a python function for reversing a linked list", "create linked-list python reverse"),
    ("write a golang goroutine example",                         "create go goroutine"),
    ("how to use concurrency in go",                             "create go goroutine"),
    ("write a js fetch request",                                 "create fetch js"),
    ("how to use fetch api in javascript",                       "create fetch js"),
    ("example of fetch api in javascript",                       "create fetch js"),
    ("how do I query all columns from a table in sql?",          "create select sql"),
    ("write a sql statement to retrieve every record from a table", "create select sql"),
    ("what is the sql command to select everything from a table?", "create select sql"),
    ("how do you use the usestate hook in a react component?",   "create react usestate"),
    ("write a simple react component demonstrating usestate",    "create react usestate"),
    ("show me how to declare and update state in react using hooks", "create react usestate"),
    ("how do you create a simple table in html?",                "create html table"),
    ("write the html markup for a table",                        "create html table"),
    ("show me an example of an html table",                      "create html table"),
    ("how do I write a bash script to iterate over files in a directory?", "create bash file loop"),
    ("show me a bash loop that processes every file in a folder", "create bash file loop"),
    ("write a shell script snippet to loop through files",       "create bash file loop"),

    # ── howto (non-code physical/life tasks) ─────────────────────────────────
    ("how to set up a redis cluster",                            "howto cluster redis"),
    ("steps to configure redis replication",                     "howto cluster redis"),
    ("how to tie a tie",                                         "howto tie"),
    ("steps to tie a necktie",                                   "howto tie"),
    ("what is the best way to tie a tie?",                       "howto tie"),
    ("how to bake a chocolate cake",                             "howto bake cake chocolate"),
    ("recipe for baking a chocolate cake",                       "howto bake cake chocolate"),
    ("steps to make a chocolate cake from scratch",              "howto bake cake chocolate"),
    ("what is the most efficient way to dice an onion?",         "howto cut onion"),
    ("how should I cut an onion for cooking?",                   "howto cut onion"),
    ("tell me the proper technique for chopping onions",         "howto cut onion"),
    ("how do I sew a fallen button back onto my shirt?",         "howto button sew"),
    ("what are the steps to reattach a button with a needle and thread?", "howto button sew"),
    ("teach me how to sew on a button",                          "howto button sew"),
    ("how do you perform cpr on an adult?",                      "howto cpr"),
    ("what are the steps for administering cardiopulmonary resuscitation?", "howto cpr"),
    ("guide me through the process of doing cpr",                "howto cpr"),
    ("what is the proper way to plant a tree?",                  "howto plant tree"),
    ("how do I plant a tree in my yard?",                        "howto plant tree"),
    ("give me a step-by-step guide to planting a tree",          "howto plant tree"),
    ("how to unclog a sink",                                     "howto drain unclog"),
    ("what is the best way to clear a clogged drain?",           "howto drain unclog"),
    ("walk me through unclogging a drain",                       "howto drain unclog"),
    ("how do I jump start a car?",                               "howto car jump-start"),
    ("what is the procedure for jump-starting a vehicle?",       "howto car jump-start"),
    ("tell me how to jump a car battery",                        "howto car jump-start"),

    # ── best (opinion) ───────────────────────────────────────────────────────
    ("what's the best programming language for machine learning", "best language ml"),
    ("which programming language should I use for ml",           "best language ml"),
    ("best language for machine learning projects",              "best language ml"),
    ("what is the best app for productivity?",                   "best app productivity"),
    ("which productivity tool is the absolute best?",            "best app productivity"),
    ("what is your top recommendation for a task management app?", "best app productivity"),
    ("what would be the best superpower to have?",               "best superpower"),
    ("what is the greatest superhuman ability to have?",         "best superpower"),
    ("which superpower is the ultimate one to possess?",         "best superpower"),
    ("which fictional world is the best one ever created?",      "best fictional universe"),
    ("what is the greatest sci-fi or fantasy universe of all time?", "best fictional universe"),
    ("which fictional setting is considered the absolute best?", "best fictional universe"),
    ("what is the optimal exercise routine for overall health?", "best workout"),
    ("which workout plan do you recommend as the best?",         "best workout"),
    ("what is the greatest fitness regimen to follow?",          "best workout"),
    ("what is the greatest approach to investing your money?",   "best invest"),
    ("which investment strategy do you recommend?",              "best invest"),
    ("what is the absolute best way to invest for the future?",  "best invest"),
    ("which coding language is the best for beginners?",         "best beginner language"),
    ("what is your top recommendation for a first programming language to learn?", "best beginner language"),
    ("which language should an absolute beginner learn first?",  "best beginner language"),
    ("which gaming console is the best to buy?",                 "best console game"),
    ("what is the top-tier video game system?",                  "best console game"),
    ("which console do you highly recommend for gamers?",        "best console game"),

    # ── history ──────────────────────────────────────────────────────────────
    ("who invented the internet?",                               "history internet"),
    ("when was the world wide web created?",                     "history internet"),
    ("history of how the internet started",                      "history internet"),
    ("who is credited with discovering the americas in 1492?",   "history america discover"),
    ("who led the spanish expedition that landed in the americas in 1492?", "history america discover"),
    ("name the explorer who sailed the ocean blue in 1492",      "history america discover"),
    ("who was the first human being to travel into space?",      "history first space"),
    ("name the first cosmonaut in outer space",                  "history first space"),
    ("who was the first person in space?",                       "history first space"),
    ("which pharaoh built the great pyramid of giza?",           "history giza pharaoh pyramid"),
    ("who built the great pyramid at giza?",                     "history giza pharaoh pyramid"),
    ("name the egyptian pharaoh buried in the great pyramid",    "history giza pharaoh pyramid"),
    ("in what year did world war 2 end?",                        "history end ww2"),
    ("when did the second world war finish?",                    "history end ww2"),
    ("what was the ending year of wwii?",                        "history end ww2"),

    # ── define (vocabulary ONLY) ─────────────────────────────────────────────
    ("what does entropy mean",                                   "define entropy"),
    ("what is the definition of entropy",                        "define entropy"),
    ("what does the word algorithm mean?",                       "define algorithm"),
    ("what does api stand for?",                                 "define api"),
    ("definition of recursion",                                  "define recursion"),

    # ── list (enumeration) ───────────────────────────────────────────────────
    ("list all the planets in our solar system",                 "list planet solar"),
    ("name every planet orbiting the sun",                       "list planet solar"),
    ("what are the planets in the solar system?",                "list planet solar"),
    ("give me all python data types",                            "list data python type"),
    ("what are the built-in types in python?",                   "list data python type"),
    ("list every primitive data type in python",                 "list data python type"),

    # ── debug (troubleshoot) ─────────────────────────────────────────────────
    ("my postgres query is super slow",                          "debug database query slow"),
    ("db query performance dropped after migration",             "debug database query slow"),
    ("postgres queries are running really sluggish",             "debug database query slow"),
    ("my react component is not rendering",                      "debug component react render"),
    ("react component won't show up on the page",                "debug component react render"),
    ("why isn't my react component rendering?",                  "debug component react render"),

    # ── summarize ────────────────────────────────────────────────────────────
    ("summarize the theory of relativity",                       "summarize relativity theory"),
    ("give me a tldr of einstein's theory of relativity",        "summarize relativity theory"),
    ("brief overview of the theory of relativity",               "summarize relativity theory"),
]

CONFIG = {
    "name": "v8_almost_perfect_gemma_e2b",
    "description": "Expanded intent vocab (fact/list/debug/summarize), pinned intent-first, big synonym table, singular/plural collapse, Gemma 4 E2B",
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
    "system_prompt": _SYSTEM_PROMPT,
    "few_shots": _FEW_SHOTS,
}
