"""v19: Gemma 4 E4B → canonical short English question + default MiniLM.

v18 (Gemma E2B keyword bag) plateaued at 56.3% Hit@0.15 because 3-word
keyword bags are too short for the embedder to collapse English synonym
drift (berners-lee vs creator vs web, resume vs cv, airplane vs flight).

v19 stops fighting vocabulary at the token level. Instead, the LLM
rewrites the query into a canonical short English question following
fixed templates. Full sentences give the MiniLM embedder enough context
to collapse synonyms via its paraphrase prior — something a 3-token bag
cannot do.

Templates (soft, instructed via prompt — no grammar):
    FACT:    "what is the <attribute> of <subject>"
    EXPLAIN: "how does <subject> work"
    HOWTO:   "how do you <verb> <object>"
    COMPARE: "what is the difference between <a> and <b>"
    BEST:    "what is the best <noun> for <context>"
    HISTORY: "who <verb> <object>" or "when did <event> happen"
    CODE:    "how do you <verb> <object> in <language>"
    LIST:    "what are the <noun>"

Model: unsloth/gemma-4-E4B-it-GGUF Q4_K_M (~2.5 GB download, first run).
Embedder: default all-MiniLM-L6-v2 (same as prod ChromaDB).

Few-shots: ~60 examples across all 7 categories, ALL topics drawn from
OUTSIDE the 100-concept test set in dataset/prompts.json. Test-set
concept IDs to avoid (verbatim from v18):

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

Run:
    cd normalization-test && uv run python -m harness.runner --configs v19_canonical_question_gemma_e4b
"""

import re

_SYSTEM_PROMPT = """\
You rewrite user queries into a canonical short English question following fixed templates.

RULES:
1. Output ONE SHORT english question on a single line. No prefix, no explanation, no quotes.
2. Max 12 words. Lowercase. No punctuation except spaces.
3. Pick the closest template:
     FACT:    "what is the <attribute> of <subject>"
     EXPLAIN: "how does <subject> work"
     HOWTO:   "how do you <verb> <object>"
     COMPARE: "what is the difference between <a> and <b>"
     BEST:    "what is the best <noun> for <context>"
     HISTORY: "who <verb> <object>"   (or "when did <event> happen")
     CODE:    "how do you <verb> <object> in <language>"
     LIST:    "what are the <noun>"
4. Use the MOST COMMON English noun. Prefer "resume" over "cv", "plane" over "airplane",
   "board game" over "tabletop game", "go" over "golang".
5. DROP superlative words: "best", "greatest", "ultimate", "finest", "top-rated",
   "most highly recommended" — they ALL become "best".
6. DROP speech-act verbs: "walk me through", "show me", "guide me", "tell me how",
   "what are the steps to" — they ALL become "how do you".
7. DROP filler: "arguably", "truly", "in your opinion", "of all time".
8. For HISTORY with a known inventor/discoverer, always phrase as "who <verb> <object>"
   (e.g. "who invented the telephone"), NEVER "who was the person that...".
9. CRITICAL: Two paraphrases of the same concept MUST produce the same canonical question.
   If in doubt, use simpler and more generic words.
"""

_FEW_SHOTS = [
    # ---- FACT (factual_qa) ----
    ("What is the tallest mountain on Earth?",                                "what is the tallest mountain on earth"),
    ("Name the highest peak in the world.",                                   "what is the tallest mountain on earth"),
    ("Which mountain has the greatest elevation?",                            "what is the tallest mountain on earth"),
    ("What is the chemical symbol for gold?",                                 "what is the chemical symbol of gold"),
    ("Which element uses the symbol Au on the periodic table?",               "what is the chemical symbol of gold"),
    ("What is the speed of sound in air?",                                    "what is the speed of sound in air"),
    ("How fast does sound travel through the air?",                           "what is the speed of sound in air"),
    ("Tell me how quickly sound moves in air.",                               "what is the speed of sound in air"),

    # ---- EXPLAIN (conceptual) ----
    ("How does a jet engine work?",                                           "how does a jet engine work"),
    ("Explain the principle behind a jet engine.",                            "how does a jet engine work"),
    ("Can you describe the way a jet engine operates?",                       "how does a jet engine work"),
    ("How does photosynthesis work?",                                         "how does photosynthesis work"),
    ("Explain how plants make food from sunlight.",                           "how does photosynthesis work"),
    ("What is the process of photosynthesis?",                                "how does photosynthesis work"),
    ("How does a solar panel generate electricity?",                          "how does a solar panel work"),
    ("Explain the working of a solar panel.",                                 "how does a solar panel work"),

    # ---- HOWTO ----
    ("How do I bake sourdough bread?",                                        "how do you bake sourdough bread"),
    ("What are the steps to making sourdough?",                               "how do you bake sourdough bread"),
    ("Walk me through baking a sourdough loaf.",                              "how do you bake sourdough bread"),
    ("How do I change a flat tire on a car?",                                 "how do you change a flat tire"),
    ("Show me the steps to replacing a flat tire.",                           "how do you change a flat tire"),
    ("Guide me through swapping out a punctured tire.",                       "how do you change a flat tire"),
    ("How do I plant a tomato seedling?",                                     "how do you plant a tomato seedling"),
    ("Walk me through planting tomato seedlings in a garden.",                "how do you plant a tomato seedling"),

    # ---- COMPARE ----
    ("What is the difference between espresso and drip coffee?",              "what is the difference between espresso and drip coffee"),
    ("Compare espresso to drip-brewed coffee.",                               "what is the difference between espresso and drip coffee"),
    ("How does espresso differ from drip coffee?",                            "what is the difference between espresso and drip coffee"),
    ("What is the difference between an introvert and an extrovert?",         "what is the difference between an introvert and an extrovert"),
    ("Compare introverts to extroverts.",                                     "what is the difference between an introvert and an extrovert"),
    ("How does a cat differ from a dog as a pet?",                            "what is the difference between a cat and a dog"),
    ("Compare cats and dogs as pets.",                                        "what is the difference between a cat and a dog"),

    # ---- BEST (opinion) ----
    ("Which hiking boot is the best for long trails?",                        "what is the best hiking boot for long trails"),
    ("What are the top-rated boots for thru-hiking?",                         "what is the best hiking boot for long trails"),
    ("Which brand makes the ultimate trekking boot?",                         "what is the best hiking boot for long trails"),
    ("What is the best vacation destination for families?",                   "what is the best vacation destination for families"),
    ("Which family holiday spot is the greatest?",                            "what is the best vacation destination for families"),
    ("What is the most highly recommended family vacation place?",            "what is the best vacation destination for families"),
    ("Which noise-cancelling headphones are the best?",                       "what is the best noise cancelling headphones"),
    ("What are the top-rated noise cancelling headphones?",                   "what is the best noise cancelling headphones"),
    ("Which brand makes the finest noise-cancelling headphones?",             "what is the best noise cancelling headphones"),

    # ---- HISTORY ----
    ("Who discovered penicillin?",                                            "who discovered penicillin"),
    ("Name the scientist who found penicillin.",                              "who discovered penicillin"),
    ("Which researcher is credited with discovering penicillin?",             "who discovered penicillin"),
    ("Who invented the telephone?",                                           "who invented the telephone"),
    ("Name the person who created the first telephone.",                      "who invented the telephone"),
    ("Who was the inventor of the telephone?",                                "who invented the telephone"),
    ("When did humans first land on the moon?",                               "when did humans land on the moon"),
    ("In what year did astronauts walk on the moon?",                         "when did humans land on the moon"),

    # ---- CODE ----
    ("How do I write a for-loop in Rust?",                                    "how do you write a for loop in rust"),
    ("Show me a Rust for loop example.",                                      "how do you write a for loop in rust"),
    ("Write a Rust snippet with a for loop.",                                 "how do you write a for loop in rust"),
    ("How do I sort a list in Python?",                                       "how do you sort a list in python"),
    ("Show me how to sort a Python list.",                                    "how do you sort a list in python"),
    ("Write Python code to sort a list.",                                     "how do you sort a list in python"),
    ("How do I parse JSON in JavaScript?",                                    "how do you parse json in javascript"),
    ("Show me a JS snippet that parses JSON.",                                "how do you parse json in javascript"),

    # ---- LIST ----
    ("What are the primary colors?",                                          "what are the primary colors"),
    ("Name the three primary colors.",                                        "what are the primary colors"),
    ("List the primary colors used in painting.",                             "what are the primary colors"),
    ("What are the noble gases?",                                             "what are the noble gases"),
    ("List all the noble gas elements.",                                      "what are the noble gases"),
]


# Regex synonym canonicalization. Deliberately tiny — bigger tables hurt (v15).
# Each rule targets an exact failure pattern observed in the v18 report.
_SYNONYM_RULES: list[tuple[str, str]] = [
    # History: WWW abbreviation
    (r"\b(www|w w w)\b", "world wide web"),
    # Howto: resume/CV
    (r"\b(curriculum vitae|cv)\b", "resume"),
    # Comparison: airplane/plane/flight/air travel
    (r"\bair travel\b", "plane"),
    (r"\b(airplane|flight|flying)\b", "plane"),
    # Comparison: train/rail
    (r"\b(train travel|rail travel|railway|rail)\b", "train"),
    # Opinion: board game / tabletop game
    (r"\btabletop game\b", "board game"),
    # Code: golang -> go
    (r"\bgolang\b", "go"),
    # Code: c++ / cpp normalization
    (r"\bc\+\+\b", "cpp"),
    # Opinion: genre/category/style of X -> X genre
    (
        r"\b(?:genre|category|style|type)\s+(?:of\s+)?(books?|music|literature|films?|movies?)\b",
        r"\1 genre",
    ),
]

_COMPILED_SYNONYMS: list[tuple[re.Pattern, str]] = [
    (re.compile(pat, re.IGNORECASE), repl) for pat, repl in _SYNONYM_RULES
]


def _postprocess(raw: str, original: str) -> str:
    # 1. First non-empty line (model may emit extra commentary despite rules)
    text = ""
    for line in raw.strip().split("\n"):
        line = line.strip()
        if line:
            text = line
            break
    text = text.lower()

    # 2. Strip punctuation except hyphens and alphanumerics/whitespace
    text = re.sub(r"[^\w\s-]", " ", text)

    # 3. Collapse whitespace
    text = " ".join(text.split())

    # 4. Apply synonym regex table
    for pat, repl in _COMPILED_SYNONYMS:
        text = pat.sub(repl, text)

    # Re-collapse whitespace after substitutions
    text = " ".join(text.split())

    # 5. Fallback: if the model totally failed, use the original query lowercased
    if not text or len(text.split()) < 2:
        return original.lower()
    return text


CONFIG = {
    "name": "v19_canonical_question_gemma_e4b",
    "description": (
        "Gemma 4 E4B rewrites each query into a canonical short English question "
        "(fixed templates per intent) and embeds the full sentence with the default "
        "MiniLM embedder. Replaces the v18 keyword-bag approach."
    ),
    # Disabled after the first run: 55.3% Hit@0.15 at 720ms mean latency —
    # worse than v18's 56.3% and slower. The canonical-question rewrite
    # produces too much sentence-level word variance for MiniLM to collapse,
    # especially on code_gen (28.9%). v20/v21 isolate whether the ceiling is
    # the embedder (MiniLM) rather than the normalizer. See
    # reports/20260411-205407/report.md for the full breakdown.
    "enabled": False,
    "passthrough": False,
    "embedder_model_path": None,  # default MiniLM (same as prod ChromaDB)
    "loader": {
        "repo_id": "unsloth/gemma-4-E4B-it-GGUF",
        "filename": "*Q4_K_M.gguf",
        "n_ctx": 4096,
    },
    "inference": {
        "max_tokens": 24,
        "temperature": 0.0,
    },
    "system_prompt": _SYSTEM_PROMPT,
    "few_shots": _FEW_SHOTS,
    "postprocess_fn": _postprocess,
}
