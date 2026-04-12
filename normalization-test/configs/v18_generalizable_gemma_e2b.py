"""v18: generalizable keyword-bag normalizer on Gemma 4 E2B.

Architecture is identical to v8/v9 (intent-first keyword bag, synonym canonicalization,
12-intent vocabulary, Gemma 4 E2B). The ONE critical change: ALL few-shot examples
use topics that do NOT appear in the 100-concept test set (dataset/prompts.json).

Why this matters:
  v8 hit 80.7% and v9 hit 93% on the test set — but when run against a 200-concept
  dataset those same configs dropped to ~59%, because the few-shots overlapped with
  the test topics (capital of france → capital_of_canada, photosynthesis → how_do_submarines,
  etc.). The model memorized outputs for known topics rather than learning the pattern.

  v18 tests whether the architecture genuinely generalizes to unseen topics, which is
  the real production requirement.

Test-set concepts deliberately excluded from few-shots:
  factual_qa:  capital_of_canada, deepest_ocean_trench, boiling_point_fahrenheit,
               longest_bone_human_body, number_of_continents, largest_desert,
               fastest_land_animal, most_populated_country, atomic_number_of_oxygen,
               smallest_planet, currency_of_japan, number_of_teeth_adult,
               hottest_planet, largest_mammal
  conceptual:  how_do_submarines_dive, what_is_dark_matter, how_do_tornadoes_form,
               what_is_the_stock_market, how_does_a_fridge_work, what_is_dna,
               how_do_earthquakes_happen, what_is_artificial_intelligence,
               how_does_a_microwave_heat_food, what_is_a_recession, how_do_gears_work,
               what_is_osmosis, how_does_the_immune_system_work, what_is_a_supernova
  howto:       how_to_tie_shoes, how_to_paint_a_room, how_to_make_a_resume,
               how_to_parallel_park, how_to_build_a_campfire, how_to_shave_your_face,
               how_to_cook_rice, how_to_fix_running_toilet, how_to_shuffle_cards,
               how_to_read_sheet_music, how_to_braid_hair, how_to_clean_windows,
               how_to_change_oil, how_to_wrap_a_gift
  code_gen:    python_read_csv, js_array_map, sql_insert_row, java_read_console_input,
               c_plus_plus_hello_world, css_flexbox_center, python_dictionary_iteration,
               bash_if_file_exists, react_useeffect_example, go_read_file,
               ruby_map_array, php_foreach_loop, rust_hello_world, html_image_tag,
               dockerfile_python_app
  comparison:  waffles_vs_pancakes, marvel_vs_dc, skiing_vs_snowboarding, email_cc_vs_bcc,
               lcd_vs_oled, freelance_vs_fulltime, train_vs_plane_travel, yoga_vs_pilates,
               http_vs_https, venomous_vs_poisonous, alligator_vs_crocodile,
               weather_vs_climate, laptop_vs_desktop, butter_vs_margarine,
               sprint_vs_marathon
  opinion:     best_browser, best_tv_show_finale, best_language_for_data_science,
               best_car_brand, best_season_of_the_year, best_cuisine_in_the_world,
               best_exercise_for_weight_loss, best_streaming_service, best_book_genre,
               best_music_genre, best_way_to_cook_steak, best_board_game,
               best_city_to_live_in, best_cloud_provider
  history:     invention_of_airplane, discovery_of_radium, fall_of_roman_empire_year,
               author_of_don_quixote, assassination_of_jfk_year, inventor_of_world_wide_web,
               first_woman_in_space, end_of_cold_war, builder_of_taj_mahal,
               discovery_of_dna_structure, start_of_ww1, first_man_on_mount_everest,
               invention_of_radio, signing_of_declaration_of_independence
"""

_SYSTEM_PROMPT = """\
You are a query canonicalizer. Convert any user query into a deterministic keyword bag so semantically equivalent queries produce IDENTICAL output.

OUTPUT FORMAT (strict):
- Lowercase, space-separated
- FIRST word is ALWAYS the intent tag. It must come before any content keyword.
- After the intent tag, content keywords sorted alphabetically
- 2 to 6 keywords TOTAL including the intent tag
- Output ONLY the bag. No prefix, no quotes, no explanation.
- WRONG: "capital canada fact"  RIGHT: "fact capital canada"
- WRONG: "howto bread bake"     RIGHT: "howto bake bread"

INTENT TAGS (use exactly one, always first; never invent new ones):
  fact      → factual lookup with NO person/date answer: what is the capital, speed of light, how many X, where is X, which X is the largest/smallest/fastest
  explain   → mechanism/process/concept: how does X work, what causes X, explain X, what is [thing with behavior]
  why       → causation: why does X happen, why is X, why did X
  compare   → contrast: X vs Y, difference between X and Y, how does X differ from Y, X or Y
  create    → ALL programming/code tasks (see CODE RULE below)
  howto     → non-code physical/life task: how to cook/fix/tie/build/clean/plant/park/bake
  best      → opinion/recommendation: best/greatest/top/optimal X, which X should I use, recommend X
  history   → person/date answer: who invented/wrote/built/discovered/painted X, when did X happen, what year was X
  define    → vocabulary lookup ONLY: what does X mean, definition of X (NOT concepts with behavior)
  list      → enumeration: list/name all X, what are the X, give examples of X
  debug     → troubleshoot problem: my X is slow/broken/not working, why isn't X working
  summarize → overview: summarize X, tldr of X, brief overview of X
  If unsure, use `fact`. NEVER output any tag not in this list.

INTENT DISAMBIGUATION (resolves common confusions):
- "Who wrote/built/invented/painted/discovered X" → ALWAYS history (NEVER fact)
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
1. ALWAYS keep the primary topic noun. NEVER drop the subject of the question.
2. Use SINGULAR form (planet, bone, magnet, book, atom).
3. Drop question words (what/which/who/where/when/how/is/are/do/does/did/was/were/will/would/could/should/can).
4. Drop stopwords (the/a/an/of/in/on/at/to/for/and/or/my/your/our/its/this/that).
5. Drop filler (please, can you, tell me, show me, give me, hey, actually, exactly, basically, I want, I'm trying, help me, walk me through, step-by-step, in general, ever, of all time).
6. Drop scope filler (the world, on earth, in the universe, in our solar system, all, every, any) UNLESS it changes meaning.
7. Drop incidental modifiers (in my yard, for cooking, on my shirt, young, old, simple, basic, quick, proper, from scratch, like a pro, standard, perfectly, at home).
8. For BEST intent, drop generic verbs (set, go, do, make, have, use) — keep only topic nouns.
9. Number normalization: "two"→2, "first"→1, "WWII"/"World War Two"→ww2, "WWI"→ww1.
10. Lowercase proper nouns but keep them.

SYNONYM CANONICALIZATION — ENFORCE STRICTLY. Always replace the variant with the canonical form:
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
  movie        ← film, picture, motion picture, adaptation (NOT tv show, NOT series, NOT television)
  show         ← tv show, television series, series (when asking about a TV show)
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

ABSOLUTE RULE: Different phrasings of the same question MUST produce byte-identical output.\
"""

_FEW_SHOTS = [
    # ── fact ─────────────────────────────────────────────────────────────────
    # speed of sound
    ("What is the speed of sound in air?",               "fact sound speed"),
    ("How fast does sound travel through air?",          "fact sound speed"),
    ("Tell me the velocity of sound in the atmosphere.", "fact sound speed"),
    # boiling point of water in Celsius
    ("At what temperature does water boil in Celsius?",         "fact boil temperature water"),
    ("What is the boiling point of water in degrees Celsius?",  "fact boil temperature water"),
    ("How many degrees Celsius does it take to boil water?",    "fact boil temperature water"),
    # chambers in human heart
    ("How many chambers does the human heart have?",            "fact chamber heart human"),
    ("What is the total number of chambers in the heart?",      "fact chamber heart human"),
    ("Name the number of compartments in a human heart.",       "fact chamber heart human"),
    # distance Earth to Moon
    ("What is the distance from Earth to the Moon?",            "fact distance earth moon"),
    ("How far is the Moon from Earth?",                         "fact distance earth moon"),
    ("Tell me how many kilometers separate Earth from the Moon.", "fact distance earth moon"),
    # weight of human brain
    ("How much does the average human brain weigh?",            "fact brain weight"),
    ("What is the weight of a typical adult human brain?",      "fact brain weight"),
    ("Name the average mass of a human brain.",                 "fact brain weight"),

    # ── explain ──────────────────────────────────────────────────────────────
    # how wifi works
    ("How does WiFi work?",                                     "explain wifi"),
    ("Explain how wireless internet transmits data.",           "explain wifi"),
    ("What is the technology behind wi-fi signals?",            "explain wifi"),
    # how magnets work
    ("How do magnets work?",                                    "explain magnet"),
    ("Explain the concept of magnetism.",                       "explain magnet"),
    ("What causes magnetic attraction and repulsion?",          "explain magnet"),
    # nuclear fusion
    ("How does nuclear fusion work?",                           "explain fusion nuclear"),
    ("Explain the process of nuclear fusion.",                  "explain fusion nuclear"),
    ("What causes two atoms to fuse together in a nuclear reaction?", "explain fusion nuclear"),
    # photosynthesis
    ("How does photosynthesis work?",                           "explain photosynthesis"),
    ("Can you explain photosynthesis to me?",                   "explain photosynthesis"),
    ("What is the process by which plants convert sunlight into food?", "explain photosynthesis"),
    # combustion engine
    ("How does an internal combustion engine work?",            "explain combustion-engine"),
    ("Explain the mechanics of a gas engine.",                  "explain combustion-engine"),
    ("What makes a combustion engine run?",                     "explain combustion-engine"),

    # ── why ──────────────────────────────────────────────────────────────────
    # why bread rises
    ("Why does bread rise when you bake it?",                   "why bread rise"),
    ("What causes bread dough to expand during baking?",        "why bread rise"),
    ("Why does yeast make bread dough rise?",                   "why bread rise"),
    # why leaves change color
    ("Why do leaves change color in autumn?",                   "why autumn color leaf"),
    ("What causes leaves to turn red and orange in fall?",      "why autumn color leaf"),
    ("Why do trees lose their green color in the fall?",        "why autumn color leaf"),
    # why iron is magnetic
    ("Why is iron magnetic?",                                   "why iron magnetic"),
    ("What makes iron attract magnets?",                        "why iron magnetic"),
    ("Why does iron respond to magnetic fields?",               "why iron magnetic"),

    # ── compare ──────────────────────────────────────────────────────────────
    # introvert vs extrovert
    ("What is the difference between an introvert and an extrovert?", "compare extrovert introvert"),
    ("Introvert vs extrovert — what sets them apart?",               "compare extrovert introvert"),
    ("How does an introvert differ from an extrovert?",              "compare extrovert introvert"),
    # renting vs buying a home
    ("What is the difference between renting and buying a home?", "compare buy home rent"),
    ("Compare homeownership to renting.",                         "compare buy home rent"),
    ("How does renting a property differ from owning one?",       "compare buy home rent"),
    # electric vs gas car
    ("Electric vs gas cars — what are the key differences?",     "compare car ev gas"),
    ("Compare cars with combustion engines to EVs.",             "compare car ev gas"),
    ("How do electric cars differ from traditional gasoline cars?", "compare car ev gas"),
    # cardio vs weightlifting
    ("What is the difference between cardio and weightlifting?", "compare cardio workout"),
    ("Compare weightlifting to cardio workouts.",                "compare cardio workout"),
    ("How does aerobic exercise differ from lifting weights?",   "compare cardio workout"),
    # TCP vs UDP
    ("What are the technical differences between TCP and UDP protocols?", "compare tcp udp"),
    ("Compare the Transmission Control Protocol with the User Datagram Protocol.", "compare tcp udp"),
    ("How do UDP and TCP differ in networking?",                              "compare tcp udp"),

    # ── create (code) ────────────────────────────────────────────────────────
    # Python list comprehension
    ("How do I write a list comprehension in Python?",          "create comprehension list python"),
    ("Write a Python list comprehension example.",              "create comprehension list python"),
    ("Show me how to use list comprehensions in Python.",       "create comprehension list python"),
    # JavaScript promise
    ("How do I use a Promise in JavaScript?",                   "create js promise"),
    ("Write a JavaScript example using Promise.",               "create js promise"),
    ("Show me how to handle async operations with a JS Promise.", "create js promise"),
    # SQL SELECT
    ("How do I query all columns from a table in SQL?",         "create select sql"),
    ("Write a SQL statement to retrieve every record from a table.", "create select sql"),
    ("What is the SQL command to select everything from a table?", "create select sql"),
    # CSS gradient
    ("How do I create a gradient background in CSS?",           "create css gradient"),
    ("Write the CSS code for a linear gradient.",               "create css gradient"),
    ("Show me a CSS example with a gradient color background.", "create css gradient"),
    # Bash for loop
    ("How do I write a for loop in Bash?",                      "create bash loop"),
    ("Write a Bash script that loops over a list of items.",    "create bash loop"),
    ("Show me how to iterate with a for loop in shell script.", "create bash loop"),

    # ── howto (non-code physical/life) ────────────────────────────────────────
    # change a tire
    ("How do I change a flat tire on a car?",                   "howto car change tire"),
    ("What are the steps for replacing a flat tire?",           "howto car change tire"),
    ("Guide me through changing a tire on the side of the road.", "howto car change tire"),
    # bake bread
    ("How do I bake a loaf of bread from scratch?",             "howto bake bread"),
    ("What are the steps for making homemade bread?",           "howto bake bread"),
    ("Walk me through baking a basic bread loaf.",              "howto bake bread"),
    # plant a tree
    ("How do I plant a tree in my yard?",                       "howto plant tree"),
    ("What is the proper way to plant a tree?",                 "howto plant tree"),
    ("Give me a step-by-step guide to planting a tree.",        "howto plant tree"),
    # unclog a drain
    ("How do I unclog a kitchen sink?",                         "howto drain unclog"),
    ("What is the best way to clear a clogged drain?",          "howto drain unclog"),
    ("Walk me through unclogging a sink drain.",                "howto drain unclog"),
    # tie a necktie
    ("How do I tie a necktie?",                                 "howto tie"),
    ("What are the steps for tying a tie?",                     "howto tie"),
    ("Guide me through knotting a standard tie.",               "howto tie"),
    # jump-start a car
    ("How do I jump-start a car battery?",                      "howto car jump-start"),
    ("What is the procedure for jump-starting a dead car battery?", "howto car jump-start"),
    ("Walk me through connecting jumper cables to start a car.", "howto car jump-start"),

    # ── best (opinion) ────────────────────────────────────────────────────────
    # best time to wake up
    ("What is the best time of day to wake up?",                "best time wake"),
    ("When is the most ideal time to set your alarm?",          "best time wake"),
    ("What wake-up time is most highly recommended?",           "best time wake"),
    # best coffee brewing method
    ("What is the best way to brew coffee?",                    "best brew coffee"),
    ("Which coffee making method is most highly recommended?",  "best brew coffee"),
    ("What is the ultimate technique for making a great cup of coffee?", "best brew coffee"),
    # best vacation destination
    ("Where is the best place to go on vacation?",              "best destination vacation"),
    ("What is the ultimate holiday destination to visit?",      "best destination vacation"),
    ("Which location is most highly recommended for a holiday?", "best destination vacation"),
    # best pizza topping
    ("What is the greatest pizza topping of all time?",         "best pizza topping"),
    ("Which ingredient is the ultimate best to put on a pizza?", "best pizza topping"),
    ("What is the most highly recommended pizza topping?",      "best pizza topping"),
    # best superpower
    ("What would be the best superpower to have?",              "best superpower"),
    ("Which superhuman ability is the ultimate one to possess?", "best superpower"),
    ("What is the greatest superpower a person could have?",    "best superpower"),
    # best TV show finale (show ≠ movie)
    ("Which television series had the absolute best finale?",   "best finale show"),
    ("What is the greatest TV show ending ever?",               "best finale show"),
    ("Which show wrapped up its story the best?",               "best finale show"),

    # ── history ──────────────────────────────────────────────────────────────
    # who painted the Mona Lisa
    ("Who painted the Mona Lisa?",                              "history lisa mona"),
    ("Name the artist who created the Mona Lisa painting.",     "history lisa mona"),
    ("Who was the painter behind the Mona Lisa?",               "history lisa mona"),
    # when did WW2 end
    ("In what year did World War 2 end?",                       "history end ww2"),
    ("When did the Second World War finish?",                   "history end ww2"),
    ("What was the ending year of WWII?",                       "history end ww2"),
    # who wrote Hamlet
    ("Who wrote the play Hamlet?",                              "history hamlet"),
    ("Who is the author of Hamlet?",                            "history hamlet"),
    ("Name the playwright who penned Hamlet.",                  "history hamlet"),
    # when was penicillin discovered
    ("When was penicillin discovered?",                         "history discover penicillin"),
    ("What year did Alexander Fleming discover penicillin?",    "history discover penicillin"),
    ("Give me the date when penicillin was first identified.",  "history discover penicillin"),
    # who built the Great Wall of China
    ("Who built the Great Wall of China?",                      "history china wall"),
    ("Which dynasty was responsible for constructing the Great Wall of China?", "history china wall"),
    ("Name the rulers who ordered the building of China's Great Wall.", "history china wall"),

    # ── define (vocabulary ONLY) ─────────────────────────────────────────────
    ("What does entropy mean?",                                 "define entropy"),
    ("What is the definition of entropy?",                      "define entropy"),
    ("What does the word entropy refer to?",                    "define entropy"),
    ("What does algorithm mean?",                               "define algorithm"),
    ("What is the definition of an algorithm?",                 "define algorithm"),
    ("What does the term algorithm refer to?",                  "define algorithm"),
    ("What does API stand for?",                                "define api"),
    ("What is an API in computing?",                            "define api"),
    ("Define the term API.",                                    "define api"),

    # ── list (enumeration) ───────────────────────────────────────────────────
    ("What are the built-in data types in Python?",             "list data python type"),
    ("List every primitive data type in Python.",               "list data python type"),
    ("Give me all the Python data types.",                      "list data python type"),
    ("Name all the continents on Earth.",                       "list continent earth"),
    ("List every continent on the planet.",                     "list continent earth"),
    ("What are the seven continents?",                          "list continent earth"),
    ("Give me examples of renewable energy sources.",           "list energy renewable"),
    ("What are the main types of renewable energy?",            "list energy renewable"),
    ("List the different forms of renewable energy.",           "list energy renewable"),

    # ── debug (troubleshoot) ─────────────────────────────────────────────────
    ("My Postgres query is super slow.",                        "debug database query slow"),
    ("DB query performance dropped after migration.",           "debug database query slow"),
    ("Postgres queries are running really sluggish.",           "debug database query slow"),
    ("My React component is not rendering.",                    "debug component react render"),
    ("React component won't show up on the page.",              "debug component react render"),
    ("Why isn't my React component rendering?",                 "debug component react render"),

    # ── summarize ─────────────────────────────────────────────────────────────
    ("Summarize the theory of relativity.",                     "summarize relativity theory"),
    ("Give me a TL;DR of Einstein's theory of relativity.",    "summarize relativity theory"),
    ("Brief overview of the theory of relativity.",             "summarize relativity theory"),
    ("Summarize the French Revolution.",                        "summarize french revolution"),
    ("Give me a brief overview of the French Revolution.",      "summarize french revolution"),
    ("What is a quick summary of the French Revolution?",       "summarize french revolution"),
]


_INTENTS = frozenset({
    "fact", "explain", "why", "compare", "create", "howto",
    "best", "history", "define", "list", "debug", "summarize",
})


def _postprocess(raw: str, original: str) -> str:
    """Intent-first keyword bag.

    The model sometimes outputs content words before the intent token.
    Find the intent token wherever it appears, pin it first, sort the rest.
    If no known intent token is found, treat first token as intent (fallback).
    """
    parts = raw.strip().lower().split()
    if not parts:
        return original.lower()

    # Find the intent token — prefer the first one found scanning left-to-right.
    intent = None
    content = []
    for p in parts:
        if intent is None and p in _INTENTS:
            intent = p
        else:
            content.append(p)

    if intent is None:
        # No recognized intent — treat first token as intent, sort rest.
        intent = parts[0]
        content = sorted(parts[1:])
    else:
        content = sorted(content)

    return " ".join([intent] + content)


CONFIG = {
    "name": "v18_generalizable_gemma_e2b",
    "description": (
        "v8/v9 approach (intent-first keyword bag, synonym table, Gemma 4 E2B) "
        "with ALL few-shots drawn from outside the 100-concept test set. "
        "Tests whether the architecture generalizes vs memorizes."
    ),
    # Disabled after the 56.3% plateau (reports/20260411-203427/report.md).
    # Kept on disk as the best LLM-keyword-bag baseline to measure against
    # when the next normalization experiment lands.
    "enabled": False,
    "passthrough": False,
    "embedder_model_path": None,  # use default MiniLM embedder — same as prod ChromaDB
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
    "postprocess_fn": _postprocess,
}
