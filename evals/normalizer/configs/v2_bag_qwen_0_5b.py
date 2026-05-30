"""v2: sorted keyword bag prompt on the same Qwen 0.5B model.

Hypothesis: the baseline's failures are driven by the prompt (technical-bias
few-shots, no canonicalization rule on word order), not the model. A sorted
keyword bag forces deterministic output and spells out implicit-subject
resolution, typo fixing, and canonical vocabulary as hard rules.
"""

CONFIG = {
    "name": "v2_bag_qwen_0_5b",
    "description": "Sorted keyword bag prompt, Qwen 2.5 0.5B",
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
        "- No punctuation, no stopwords, no interrogatives "
        "(why/how/what/who/when/where/is/are/the/a/an/of/in/on/at/to/for/and/or)\n"
        "- No filler (please, can you, I want, tell me, explain, yo, hey, lol)\n"
        "- Fix obvious typos and misspellings\n"
        "- 2 to 8 keywords maximum\n"
        "- Output ONLY the bag. No prefix, no explanation, no quotes.\n"
        "\n"
        "RULES:\n"
        "1. Resolve implicit subjects. \"why are they at war with ukraine\" — the "
        "subject is russia. Include it.\n"
        "2. Use canonical vocabulary: prefer \"war\" over \"conflict/fighting/invasion\", "
        "\"debug\" over \"troubleshoot/diagnose/fix\", \"database\" over \"postgres/mysql/db\", "
        "\"slow\" over \"laggy/sluggish\".\n"
        "3. Keep proper nouns (people, places, technologies) but lowercase them.\n"
        "4. Drop tone, politeness, and narrative framing. Keep only content words.\n"
        "5. Different phrasings of the same question MUST produce byte-identical output."
    ),
    "few_shots": [
        # Geopolitical / implicit subject resolution (the failure mode we're fixing)
        ("why is russia at war with ukraine?", "russia ukraine war"),
        ("why are they at war with ukrine", "russia ukraine war"),
        ("what caused the russia ukraine conflict", "russia ukraine war"),
        # Factual QA
        ("what's the capital of france lol", "capital france"),
        ("tell me france's capital city please", "capital france"),
        # Conceptual
        ("can you explain quantum mechanics like I'm 5", "mechanics quantum"),
        ("how does photosynthesis actually work", "photosynthesis"),
        # Technical debug with canonical vocab
        ("my postgres query is super slow after migration", "database debug migration query slow"),
        ("db query performance dropped after we moved data", "database debug migration query slow"),
        # Code gen
        ("write a python function to reverse a linked list", "function linked list python reverse"),
        # Creative
        ("write a poem about autumn", "autumn poem"),
        # Opinion / comparison
        ("what's the best programming language for machine learning", "best language learning machine programming"),
        # Distinct topics must stay distinct
        ("why is the sky blue", "blue sky"),
        ("how do black holes form", "black formation holes"),
    ],
}
