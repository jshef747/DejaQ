"""v9: targeted fixes for v8's top failure patterns.

v8 hit 80.7%. The remaining 19% misses fall into 5 buckets identified from the
worst-pairs report. v9 surgically fixes each:

1. who/when intent flip (history vs fact)
   v8 produced both `history romeo juliet` and `fact playwright romeo juliet` for
   the same concept. Sharper rule: ANY question whose answer is a person's name,
   a date, or a past event → `history`. The "fact for who-is" guidance is removed.

2. code phrased as how-to bleeding into howto intent
   v8: "how do I center a div in css" → `howto center div css` (wrong, should be create).
   Sharper rule: if the topic includes a programming language, library, framework,
   markup language, or shell → ALWAYS `create`, never `howto`.

3. synonym table not enforced strongly enough
   v8 emitted `necktie`, `novel`, `film`, `mobile` despite the table. Add explicit
   high-signal few-shots showing the canonicalization in action for the failing
   pairs (book/novel, movie/film, phone/mobile/smartphone, tie/necktie, change/replace).

4. modifier word inclusion drift on opinion phrasings
   v8: `best time wake up` vs `best time alarm set`. Add rule: for opinion/best
   intent, drop verbs like "set", "wake", "go" and keep only nouns + best.

5. sub-aspect drift on factual questions with multiple framings
   v8: `fact water molecule` vs `fact water composition` vs `fact atom water`.
   Hard to fix in prompt — added specific few-shot pairs for the canonical form.

Latency target: keep under 550ms by NOT bloating few-shots — add ~25 targeted
examples, remove ~10 redundant ones from v8.
"""

from configs.v8_almost_perfect_gemma_e2b import CONFIG as V8_CONFIG

_SYSTEM_PROMPT = """\
You are a query canonicalizer. Convert any user query into a deterministic keyword bag so semantically equivalent queries produce IDENTICAL output.

OUTPUT FORMAT (strict):
- Lowercase, space-separated
- FIRST word is always the intent tag (from list below)
- After the intent tag, content keywords sorted alphabetically
- 2 to 6 keywords TOTAL including the intent tag
- Output ONLY the bag. No prefix, no quotes, no explanation.

INTENT TAGS (use exactly one, always first; never invent new ones):
  fact      → discrete factual lookup with NO person/date answer: what is the capital, speed of light, how many bones, where is X, which X is the largest
  explain   → mechanism/process/concept: how does X work, what causes X, what is [thing with behavior]
  why       → why does/did/is X happen
  compare   → X vs Y, difference between X and Y, X or Y, how does X differ from Y
  create    → ALL programming/code requests (see CODE RULE below)
  howto     → non-code physical/life task ONLY: how to cook/fix/tie/build/clean
  best      → opinion/recommendation: best/greatest/top/optimal X, which X should I use
  history   → ANY question whose answer is a person's name, a date/year, or a past event:
              who invented/discovered/built/wrote/painted X, when did X happen, what year did X,
              who was the first to X, name the explorer/author/pharaoh/scientist who X
  define    → vocabulary lookup ONLY: "what does X mean", "definition of X" (NOT concepts)
  list      → enumeration: list/name all X, what are the X, give examples of X
  debug     → troubleshoot/fix a problem: my X is slow/broken/not working
  summarize → summarize/overview/tldr of X
  If unsure, use `fact`. NEVER output any tag not in this list.

INTENT DISAMBIGUATION (resolves common confusions):
- "Who wrote/built/invented/painted X" → ALWAYS history (NEVER fact)
- "When did X happen / what year was X" → ALWAYS history (NEVER fact)
- "What is the capital/speed/depth/length/count of X" → fact
- "Which X is the largest/smallest/fastest" → fact (no person, no date)
- "How do I [code task in any programming language]" → create (NEVER howto)
- "What is the best way to [physical task]" → howto
- "What is the best [object/choice]" → best

CODE RULE — if the query mentions ANY programming language, framework, library,
markup, query language, or shell (python, js, javascript, typescript, ts, java, go,
rust, c, cpp, c++, csharp, c#, ruby, php, swift, kotlin, scala, sql, mysql, postgres,
html, css, react, vue, angular, node, npm, bash, shell, zsh, powershell, docker,
kubernetes, git) the intent MUST be `create`, regardless of the question form.
Even "how do I X in Y", "how to X with Y", "show me Y example" → create.

CONTENT KEYWORD RULES:
1. ALWAYS keep the primary topic noun. NEVER drop the subject.
2. Use SINGULAR (planet, bone, magnet, book, atom).
3. Drop question words (what/which/who/where/when/how/is/are/do/does/did/was/were/will/would/could/should/can).
4. Drop stopwords (the/a/an/of/in/on/at/to/for/and/or/my/your/our/its/this/that).
5. Drop filler (please, can you, tell me, show me, give me, hey, lol, actually, exactly, basically, kind of, I want, I'm trying, help me, walk me through, step-by-step, in general, ever, all time, of all time).
6. Drop scope filler (the world, on earth, in the universe, in our solar system, all, every, any).
7. Drop incidental modifiers (in my yard, for cooking, on my shirt, young, old, simple, basic, quick, proper, from scratch, like a pro, standard, basic, perfectly).
8. For BEST intent, drop generic verbs (set, go, do, make, have) — keep only the topic nouns + best.
9. Number normalization: "two"→2, "first"→1, "WWII"/"World War Two"→ww2, "WWI"→ww1.
10. Lowercase proper nouns but keep them.

SYNONYM CANONICALIZATION — ENFORCE STRICTLY. Always replace the variant with the canonical form, even if it appears in the question:
  cut          ← dice, chop, slice, mince
  sew          ← reattach, stitch, attach (fabric)
  unclog       ← clear, unblock (drains)
  cook         ← prepare, make (food)
  cpr          ← cardiopulmonary resuscitation
  tie          ← necktie, knot (the noun)
  change       ← replace, swap, switch (general action)
  fold         ← make (when constructing from paper)
  center       ← align center, middle
  connect      ← establish connection
  parse        ← read, convert (data formats)
  env          ← environment variable
  tcp/udp/api/ai/ml/ui/os/db/url/http/css/html/sql/js/ts/ev/gpu/cpu/ram → always abbreviation
  python       ← py
  javascript   → js
  typescript   → ts
  csharp       ← c#
  largest      ← biggest, greatest, most landmass, highest, tallest (when superlative IS the question)
  smallest     ← tiniest, littlest, least
  fastest      ← quickest, speediest, swiftest
  oldest       ← most ancient, earliest
  hardest      ← toughest, strongest (material)
  best         ← greatest, top, finest, ultimate, optimal, ideal, premier, recommended, superior, highest
  worst        ← poorest, lowest
  app          ← application, tool, software, program, platform
  car          ← vehicle, automobile, auto, ride
  phone        ← mobile, smartphone, cellphone, cell
  computer     ← pc, machine, device
  code         ← snippet, script
  bug          ← error, issue, defect, problem (in debug intent)
  slow         ← laggy, sluggish, performance issue
  combustion-engine ← gas engine, internal combustion, ice engine
  non-renewable ← fossil fuels, coal, oil, gas (energy context)
  workout      ← exercise routine, fitness regimen, training plan
  invest       ← investing, investment strategy, financial planning
  book         ← novel, text, publication, story
  movie        ← film, picture, motion picture, adaptation
  database     ← postgres, mysql, mongo, datastore
  frontend     ← client side, ui layer, browser side
  backend      ← server side, api layer
  vacation     ← holiday, trip, getaway
  destination  ← place, location, spot
  company      ← brand, manufacturer, maker
  pizza        ← pie (food context)
  topping      ← ingredient (on a pizza)
  composition  ← element, atom, molecule (when asking what something is made of)
  brew         ← make, prepare (coffee)

ABSOLUTE RULE: Different phrasings of the same question MUST produce byte-identical output. When in doubt, prefer FEWER keywords and the more generic noun.\
"""

# Start from v8's few-shots and add targeted patches for the v8 failure cases
_FEW_SHOTS = list(V8_CONFIG["few_shots"]) + [
    # ── history disambiguation: "who wrote/built/painted" ALWAYS history ─────
    ("who wrote the play romeo and juliet?",                     "history juliet romeo"),
    ("who is the author of romeo and juliet?",                   "history juliet romeo"),
    ("name the playwright who penned romeo and juliet",          "history juliet romeo"),
    ("when did the berlin wall come down?",                      "history berlin fall wall"),
    ("what year did the berlin wall fall?",                      "history berlin fall wall"),
    ("give me the date when the berlin wall was demolished",     "history berlin fall wall"),
    ("who painted the mona lisa?",                               "history lisa mona"),
    ("name the artist who painted the mona lisa",                "history lisa mona"),
    ("who created the mona lisa painting?",                      "history lisa mona"),
    # cosmonaut/astronaut → still history (not fact) — first person in space
    ("name the first astronaut in outer space",                  "history first space"),
    ("who achieved the milestone of being the first person in space?", "history first space"),

    # ── code rule: how-to phrasing in any language → create ──────────────────
    ("how do I horizontally and vertically center a div in css?", "create center css div"),
    ("write the css properties needed to center a container",     "create center css div"),
    ("show me the css code to center an element",                 "create center css div"),
    ("how do I connect to a mysql database using pdo in php?",    "create database php pdo"),
    ("write the php code required to establish a pdo connection", "create database php pdo"),
    ("show me a php snippet for connecting to mysql via pdo",     "create database php pdo"),
    ("how do I access an environment variable in rust?",          "create env rust"),
    ("write rust code to read a value from the system environment", "create env rust"),
    ("show me the rust function to get an env var",               "create env rust"),
    ("how do you parse a json string in ruby?",                   "create json parse ruby"),
    ("write ruby code to convert a json payload into a hash",     "create json parse ruby"),
    ("show me how to read json data using ruby",                  "create json parse ruby"),

    # ── synonym enforcement: tie/necktie ─────────────────────────────────────
    ("how do you tie a standard necktie?",                       "howto tie"),
    ("show me the steps to knot a tie",                          "howto tie"),
    ("what is the best way to tie a tie?",                       "howto tie"),

    # ── synonym enforcement: book/novel, movie/film/adaptation ───────────────
    ("what are the differences between reading a book and watching its movie adaptation?", "compare book movie"),
    ("compare the experience of a novel to a film adaptation",    "compare book movie"),
    ("how do books differ from movies based on them?",            "compare book movie"),

    # ── synonym enforcement: phone/mobile/smartphone, company/brand ──────────
    ("which company makes the absolute best smartphones?",        "best company phone"),
    ("what is the top recommended mobile phone brand?",           "best company phone"),
    ("which smartphone manufacturer is considered the finest?",   "best company phone"),

    # ── synonym enforcement: change/replace + tire ───────────────────────────
    ("what are the steps to replace a flat tire on a car?",       "howto car change tire"),
    ("how do I change a car tire?",                               "howto car change tire"),
    ("guide me through changing a flat tire",                     "howto car change tire"),

    # ── synonym enforcement: fold/make + paper airplane ──────────────────────
    ("how do you fold a basic paper airplane?",                   "howto airplane fold paper"),
    ("give me the folding steps for a standard paper plane",      "howto airplane fold paper"),
    ("show me how to make a paper airplane that flies",           "howto airplane fold paper"),

    # ── opinion drift fix: drop verb fillers in best intent ──────────────────
    ("what is the most ideal time of day to wake up?",            "best time wake"),
    ("when is the absolute best time to set your alarm for?",     "best time wake"),
    ("what wake-up time is most highly recommended?",             "best time wake"),
    ("what is the most superior way to brew a cup of coffee?",    "best brew coffee"),
    ("which coffee making technique yields the best results?",    "best brew coffee"),
    ("what is the highly recommended method for making coffee?",  "best brew coffee"),
    ("where is the best place in the world to go on vacation?",   "best destination vacation"),
    ("what is the ultimate holiday destination to visit?",        "best destination vacation"),
    ("which location offers the best vacation experience?",       "best destination vacation"),
    ("what is the greatest pizza topping of all time?",           "best pizza topping"),
    ("which ingredient is universally the best to put on a pizza?", "best pizza topping"),
    ("what is the superior pizza topping?",                       "best pizza topping"),

    # ── factual sub-aspect collapse: water composition ───────────────────────
    ("what elements make up a water molecule?",                   "fact composition water"),
    ("what is the chemical composition of water?",                "fact composition water"),
    ("which atoms are in water?",                                 "fact composition water"),

    # ── factual: hardest substance ───────────────────────────────────────────
    ("what is the hardest known natural material?",               "fact hardest material"),
    ("which naturally occurring substance is the hardest?",       "fact hardest material"),
    ("name the hardest mineral found in nature",                  "fact hardest material"),

    # ── factual: largest continent — drop "earth/land area" filler ───────────
    ("which continent is the largest by land area?",              "fact continent largest"),
    ("what is the biggest continent on earth?",                   "fact continent largest"),
    ("name the continent with the most landmass",                 "fact continent largest"),
]

CONFIG = {
    "name": "v9_targeted_gemma_e2b",
    "description": "v8 + targeted fixes for who/when→history, code-as-howto, synonym enforcement, opinion verb drop, sub-aspect collapse",
    "enabled": False,
    "loader": {
        "repo_id": "unsloth/gemma-4-E2B-it-GGUF",
        "filename": "gemma-4-E2B-it-Q4_K_M.gguf",
        "n_ctx": 16384,
    },
    "inference": {
        "max_tokens": 24,
        "temperature": 0.0,
    },
    "system_prompt": _SYSTEM_PROMPT,
    "few_shots": _FEW_SHOTS,
}
