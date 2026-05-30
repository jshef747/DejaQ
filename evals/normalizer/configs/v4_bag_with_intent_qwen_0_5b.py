"""v4: sorted keyword bag + preserved intent words, Qwen 0.5B.

Problem with v2: stripping ALL stopwords and interrogatives loses the question
intent. "explain photosynthesis" vs "history of photosynthesis" vs "draw
photosynthesis" all collapse to just "photosynthesis", causing false cache hits
across semantically different answers.

Fix: preserve a small controlled vocabulary of intent words that determine
what KIND of answer is expected. These sort into the bag like any other keyword.

Intent vocabulary:
  explain  — how does X work, what is X, explain X, describe X
  why      — why did/is/are X
  create   — write/generate/build/make X
  compare  — X vs Y, difference between X and Y
  define   — definition of X, what does X mean
  history  — who invented X, history of X, origin of X
  best     — best X for Y, recommend X, which X should I use
  howto    — how to do X, steps to X, tutorial for X
  debug    — troubleshoot/diagnose/fix/solve problem with X
"""

CONFIG = {
    "name": "v4_bag_with_intent_qwen_0_5b",
    "description": "Sorted keyword bag + intent tags, Qwen 2.5 0.5B",
    "enabled": False,
    "loader": {
        "repo_id": "Qwen/Qwen2.5-0.5B-Instruct-GGUF",
        "filename": "*q4_k_m.gguf",
        "n_ctx": 4096,
    },
    "inference": {
        "max_tokens": 48,
        "temperature": 0.0,
    },
    "system_prompt": (
        "You are a query canonicalizer. Convert any user query into a deterministic "
        "keyword bag so semantically equivalent queries produce IDENTICAL output.\n"
        "\n"
        "OUTPUT FORMAT (strict):\n"
        "- Lowercase only\n"
        "- Space-separated keywords\n"
        "- Alphabetically sorted\n"
        "- Remove stopwords (the/a/an/of/in/on/at/to/for/and/or/is/are/do/does/did)\n"
        "- Remove filler (please, can you, I want, tell me, yo, hey, lol, actually)\n"
        "- Fix obvious typos and misspellings\n"
        "- 2 to 8 keywords maximum\n"
        "- Output ONLY the bag. No prefix, no explanation, no quotes.\n"
        "\n"
        "INTENT WORDS — always keep these when present, they distinguish different "
        "types of answers for the same topic:\n"
        "  explain  (how does X work / what is X / explain X / describe X)\n"
        "  why      (why did/is/are X)\n"
        "  create   (write/generate/build/make X)\n"
        "  compare  (X vs Y / difference between X and Y)\n"
        "  define   (definition of X / what does X mean)\n"
        "  history  (who invented X / history of X / origin of X)\n"
        "  best     (best X for Y / recommend X / which X should I use)\n"
        "  howto    (how to do X / steps to X / tutorial for X)\n"
        "  debug    (troubleshoot/diagnose/fix/solve a problem with X)\n"
        "\n"
        "RULES:\n"
        "1. Always include exactly one intent word from the list above.\n"
        "2. Resolve implicit subjects. \"why are they at war with ukraine\" — "
        "the subject is russia. Include it.\n"
        "3. Canonical vocabulary: prefer \"war\" over \"conflict/fighting/invasion\", "
        "\"database\" over \"postgres/mysql/db\", \"slow\" over \"laggy/sluggish\".\n"
        "4. Keep proper nouns (people, places, technologies) but lowercase them.\n"
        "5. Drop narrative framing. Keep only content words + one intent word.\n"
        "6. Different phrasings of the same question MUST produce byte-identical output."
    ),
    "few_shots": [
        # why — geopolitical
        ("why is russia at war with ukraine?",        "russia ukraine war why"),
        ("why are they at war with ukrine",           "russia ukraine war why"),
        ("what caused the russia ukraine conflict",   "russia ukraine war why"),
        # why — science
        ("why is the sky blue",                       "blue sky why"),
        # explain — conceptual
        ("can you explain quantum mechanics like I'm 5",          "explain mechanics quantum"),
        ("how does quantum mechanics actually work",              "explain mechanics quantum"),
        ("how does photosynthesis work",                          "explain photosynthesis"),
        ("can you explain photosynthesis to me",                  "explain photosynthesis"),
        ("explain the process of photosynthesis",                 "explain photosynthesis"),
        # explain — science
        ("how do black holes form",                              "black explain holes"),
        # define
        ("what does entropy mean",                               "define entropy"),
        ("what is a monad",                                      "define monad"),
        # factual_qa (no strong intent → use explain)
        ("what's the capital of france lol",                     "capital explain france"),
        ("tell me france's capital city please",                 "capital explain france"),
        # create — code
        ("write a python function to reverse a linked list",     "create function linked list python reverse"),
        ("can you write me a python function for reversing a linked list", "create function linked list python reverse"),
        # create — creative
        ("write a poem about autumn",                            "autumn create poem"),
        # compare
        ("rust vs go for systems programming",                   "compare go rust systems"),
        ("what's the difference between rust and go",            "compare go rust"),
        # best
        ("what's the best programming language for machine learning", "best language learning machine"),
        ("which framework should I use for ML",                  "best framework learning machine"),
        # debug
        ("my postgres query is super slow after migration",      "database debug migration query slow"),
        ("db query performance dropped after we moved data",     "database debug migration query slow"),
        # howto
        ("how to set up a redis cluster",                        "cluster howto redis setup"),
        ("steps to configure redis replication",                 "cluster howto redis setup"),
        # history
        ("who invented the internet",                            "history internet"),
        ("what is the origin of the internet",                   "history internet"),
    ],
}
