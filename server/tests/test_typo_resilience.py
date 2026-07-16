"""10,000-pair deterministic typo resilience evaluation.

Generates 7,000 typo pairs + 3,000 sibling pairs (seed=42) and runs them
through lexical_match.align(). No server, no model, no network - pure
stdlib string math.

Realistic typo intensity (based on average typing speed):
  ~60% with 1-2 typos   (normal typing)
  ~25% with 3-4 typos   (fast typing)
  ~15% with 5+ typos    (edge stress test)

Expanded templates across 8 domains + very long queries (25-40 words).

Run:
    cd server && uv run pytest tests/test_typo_resilience.py -v
    cd server && uv run python tests/test_typo_resilience.py   # writes report

Report: docs/typo-resilience-report.md
"""

from __future__ import annotations

import random
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

import pytest

from app.services.lexical_match import align

pytestmark = pytest.mark.no_model


# ---------------------------------------------------------------------------
# Templates: 8 domains + very long queries
# ---------------------------------------------------------------------------


TEMPLATES = [
    # --- factual / geography (12) ---
    ("what is the capital of {x}?",
     ["france", "germany", "spain", "japan", "brazil", "canada", "egypt", "kenya",
      "norway", "mexico", "turkey", "poland", "switzerland", "portugal", "greece"]),
    ("what is the population of {x}?",
     ["france", "germany", "brazil", "canada", "egypt", "norway", "mexico", "turkey",
      "india", "nigeria", "south africa", "argentina", "colombia", "chile"]),
    ("what is the currency of {x}?",
     ["japan", "brazil", "canada", "egypt", "norway", "mexico", "turkey", "poland",
      "switzerland", "portugal", "greece", "thailand", "vietnam", "indonesia"]),
    ("what language is spoken in {x}?",
     ["brazil", "egypt", "kenya", "norway", "austria", "morocco", "portugal",
      "switzerland", "belgium", "cuba", "peru", "venezuela", "guatemala"]),
    ("what is the largest city in {x}?",
     ["france", "germany", "japan", "brazil", "canada", "egypt", "mexico", "turkey",
      "australia", "sweden", "finland", "denmark", "ireland", "scotland"]),
    ("what is the official language of {x}?",
     ["brazil", "egypt", "kenya", "norway", "austria", "switzerland", "portugal",
      "greece", "thailand", "vietnam", "india", "malaysia", "philippines"]),
    ("what is the time zone in {x}?",
     ["california", "new york", "london", "tokyo", "sydney", "dubai", "singapore",
      "mumbai", "berlin", "paris", "toronto", "mexico city", "bangkok", "seoul"]),
    ("how big is {x} in square kilometers?",
     ["france", "japan", "brazil", "canada", "egypt", "mexico", "india", "australia",
      "argentina", "kazakhstan", "algeria", "sweden", "norway", "finland"]),
    ("what is the national dish of {x}?",
     ["japan", "mexico", "italy", "india", "thailand", "france", "china", "peru",
      "morocco", "lebanon", "turkey", "greece", "spain", "ethiopia"]),
    ("what is the highest mountain in {x}?",
     ["switzerland", "nepal", "peru", "new zealand", "colombia", "iceland", "ghana",
      "jamaica", "cuba", "ireland", "norway", "nigeria", "philippines"]),
    ("what is the longest river in {x}?",
     ["brazil", "egypt", "india", "canada", "japan", "kenya", "mexico", "australia",
      "france", "germany", "spain", "argentina", "chile", "south africa"]),
    ("what is the climate like in {x}?",
     ["iceland", "sahara", "amazon", "tibet", "hawaii", "greenland", "maldives",
      "siberia", "patagonia", "himalayas", "antarctica", "arctic", "serengeti", "amazon"]),

    # --- science (10) ---
    ("how does {x} work?",
     ["photosynthesis", "fermentation", "osmosis", "digestion", "evaporation",
      "condensation", "mitosis", "meiosis", "respiration", "transpiration"]),
    ("explain {x} in simple terms",
     ["quantum entanglement", "general relativity", "brownian motion", "natural selection",
      "entropy", "superconductivity", "dark matter", "black holes", "gene editing",
      "CRISPR", "RNA splicing", "protein folding", "neural networks", "blockchain"]),
    ("what causes {x} in humans?",
     ["insomnia", "migraines", "hiccups", "allergies", "dehydration", "anemia",
      "osteoporosis", "diabetes", "asthma", "arthritis", "eczema", "acne",
      "hypertension", "cholesterol"]),
    ("what is the function of the {x} in the human body?",
     ["liver", "pancreas", "kidneys", "thyroid", "spleen", "heart", "lungs",
      "brain", "stomach", "intestines", "bladder", "gallbladder", "appendix"]),
    ("what is the boiling point of {x}?",
     ["water", "ethanol", "mercury", "nitrogen", "oxygen", "hydrogen", "carbon dioxide",
      "iron", "gold", "aluminum", "silver", "copper", "lead", "zinc"]),
    ("what is the chemical formula for {x}?",
     ["water", "carbon dioxide", "salt", "sugar", "methane", "ammonia", "sulfuric acid",
      "hydrochloric acid", "acetic acid", "citric acid", "glucose", "aspirin",
      "caffeine", "nicotine"]),
    ("how many chromosomes do {x} have?",
     ["humans", "dogs", "cats", "fruit flies", "peas", "bacteria", "ferns",
      "wheat", "chimpanzees", "orangutans", "horses", "cows", "pigs", "sheep"]),
    ("what is the speed of {x}?",
     ["light", "sound", "gravity", "earth", "moon", "sun", "stars", "comets",
      "asteroids", "meteors", "planets", "galaxies", "nebulas", "black holes"]),
    ("what element has the atomic number {x}?",
     ["11", "12", "17", "26", "29", "47", "79", "82", "92", "54", "64", "100", "256", "512"]),
    ("what is the half life of {x}?",
     ["carbon 14", "uranium 238", "radon 222", "iodine 131", "cesium 137",
      "plutonium 239", "tritium", "cobalt 60", "strontium 90", "polonium 210",
      "americium 241", "neptunium 237", "curium 244", "berkelium 249"]),

    # --- coding / tech (10) ---
    ("how do i reverse a {x} in python?",
     ["string", "list", "tuple", "dictionary", "set", "array", "stack", "queue",
      "linked list", "binary tree", "hash map", "graph"]),
    ("how do i install {x} on ubuntu?",
     ["docker", "kubernetes", "postgresql", "nginx", "redis", "terraform", "ansible",
      "grafana", "prometheus", "elasticsearch", "mongodb", "rabbitmq", "consul"]),
    ("what does the {x} command do in linux?",
     ["grep", "chmod", "rsync", "curl", "awk", "sed", "find", "tar", "git",
      "ssh", "scp", "wget", "systemctl", "journalctl"]),
    ("how do i center a div using {x}?",
     ["flexbox", "grid", "margins", "position absolute", "text align center",
      "auto margins", "vertical align", "transform translate"]),
    ("what is the difference between {x} in javascript?",
     ["let and var", "map and foreach", "null and undefined", "promises and callbacks",
      "async and await", "class and prototype", "shallow and deep copy",
      "call and apply", "bind and curry", "== and ===", "var and const",
      "switch and if else"]),
    ("how do i undo the last commit in {x}?",
     ["git", "mercurial", "subversion", "bzr", "perforce", "tfs"]),
    ("what is the time complexity of {x}?",
     ["binary search", "quick sort", "merge sort", "bubble sort", "hash lookup",
      "tree traversal", "dijkstra algorithm", "binary search tree insert",
      "linked list append", "heap sort", "radix sort", "counting sort"]),
    ("how do i write a {x} in rust?",
     ["struct", "enum", "trait", "closure", "iterator", "async function",
      "generic function", "macro", "module", "error type", "borrow checker rule"]),
    ("what is the difference between {x} in go?",
     ["channels and mutexes", "slices and arrays", "interfaces and structs",
      "defer and finally", "goroutines and threads", "map and hashmap",
      "nil and zero value", "make and new", "package and module"]),
    ("how do i optimize a {x} in sql?",
     ["query", "index", "join", "subquery", "aggregate", "window function",
      "cte", "stored procedure", "trigger", "view", "partition", "full text search"]),

    # --- practical / daily life (8) ---
    ("how long should i cook {x} in the oven?",
     ["chicken", "salmon", "lasagna", "potatoes", "meatloaf", "bread", "cake",
      "pasta", "steak", "rice", "beans", "tofu", "vegetables", "fish"]),
    ("what is the best way to remove {x} stains from clothes?",
     ["coffee", "wine", "grass", "ink", "grease", "blood", "mud", "makeup",
      "paint", "oil", "rust", "glue", "marker", "sauce"]),
    ("how much water should i drink during {x}?",
     ["exercise", "pregnancy", "fasting", "winter", "summer", "illness",
      "diet change", "travel", "hiking", "yoga", "running", "swimming"]),
    ("what are the health benefits of {x}?",
     ["walking", "meditation", "sleep", "yoga", "running", "swimming",
      "cycling", "intermittent fasting", "protein", "fiber", "omega 3",
      "vitamin d", "probiotics", "antioxidants"]),
    ("how do i {x} in the kitchen?",
     ["peel garlic", "dice onions", "boil eggs", "make pasta", "knead dough",
      "sear meat", "fillet fish", "sharpen a knife", "make broth", "clean mushrooms",
      "grate cheese", "whip cream", "fold batter", "proof yeast"]),
    ("what is the best {x} for beginners?",
     ["laptop", "phone", "camera", "guitar", "piano", "bike", "watch",
      "keyboard", "monitor", "printer", "router", "tablet", "speakers"]),
    ("how do i save money on {x}?",
     ["groceries", "electricity", "gas", "insurance", "rent", "travel",
      "internet", "phone", "education", "healthcare", "banking", "taxes"]),
    ("what should i pack for a trip to {x}?",
     ["japan", "egypt", "brazil", "iceland", "morocco", "thailand", "peru",
      "norway", "kenya", "mexico", "greece", "turkey", "australia", "india"]),

    # --- culture / history (8) ---
    ("who wrote {x}?",
     ["hamlet", "macbeth", "othello", "frankenstein", "dracula", "ulysses",
      "pride and prejudice", "the great gatsby", "1984", "to kill a mockingbird",
      "the odyssey", "the iliad", "don quixote", "war and peace"]),
    ("when did the {x} war end?",
     ["korean", "vietnam", "crimean", "peloponnesian", "world war one",
      "world war two", "civil war", "french revolution", "boer war",
      "punic war", "thirty years", "hundred years", "golden", "cold"]),
    ("what was the {x} civilization known for?",
     ["roman", "egyptian", "greek", "mayan", "aztec", "persian", "chinese",
      "indus", "mesopotamian", "mongol", "inca", "phoenician", "babylonian"]),
    ("who painted {x}?",
     ["starry night", "mona lisa", "guernica", "the scream", "water lilies",
      "the last supper", "birth of venus", "the persistence of memory",
      "american gothic", "the kiss", "impression sunrise", "noahs ark",
      "the thinker", "the garden of earthly delights"]),
    ("what is the significance of {x} in history?",
     ["magna carta", "french revolution", "fall of rome", "industrial revolution",
      "renaissance", "cold war", "print press", "steam engine", "internet",
      "moon landing", "declaration of independence", "treaty of versailles",
      "black death", "reformation"]),
    ("what genre is the {x} movie?",
     ["inception", "pulp fiction", "interstellar", "the godfather", "dark knight",
      "fight club", "forrest gump", "schindlers list", "gladiator", "braveheart",
      "the matrix", "star wars", "jurassic park", "the shawshank redemption"]),
    ("what instrument does {x} play?",
     ["jimi hendrix", "johann sebastian bach", "ludwig van beethoven", "miles davis",
      "frederic chopin", "wolfgang amadeus mozart", "niccolo paganini", "franz liszt",
      "claude debussy", "edvard griev", "antonin dvorak", "george frideric handel"]),
    ("what city is famous for {x}?",
     ["paris", "rome", "tokyo", "new york", "london", "barcelona", "vienna",
      "prague", "venice", "moscow", "cairo", "beijing", "istanbul", "mumbai"]),

    # --- finance / business (6) ---
    ("what is the {x} interest rate?",
     ["federal reserve", "european central bank", "bank of england", "bank of japan",
      "reserve bank of india", "bank of canada", "australian reserve bank",
      "swiss national bank", "bank of china", "north american bank"]),
    ("how does {x} work in investing?",
     ["compound interest", "dollar cost averaging", "index funds", "etfs",
      "dividend reinvestment", "portfolio rebalancing", "asset allocation",
      "value investing", "growth investing", "options trading"]),
    ("what is the {x} stock market index?",
     ["s and p 500", "dow jones", "nasdaq", "ftse 100", "dax", "nikkei 225",
      "hang seng", "shanghai composite", "tsx composite", "bos30",
      "cac 40", "asx 200", "kos 100", "bovespa"]),
    ("what is the {x} inflation rate?",
     ["united states", "united kingdom", "japan", "germany", "brazil",
      "india", "canada", "australia", "france", "mexico", "turkey",
      "argentina", "south africa", "chile"]),
    ("how do i file taxes for {x}?",
     ["w2 income", "freelance work", "rental property", "stock gains",
      "cryptocurrency", "foreign income", "small business", "self employment",
      "capital gains", "dividend income", "royalty income", "estate"]),
    ("what is the {x} exchange rate?",
     ["usd to euro", "usd to yen", "usd to pound", "usd to yuan",
      "usd to rupee", "usd to dollar", "euro to pound", "pound to yen",
      "bitcoin to usd", "gold to usd", "oil to usd", "silver to usd"]),

    # --- very long queries (12) ---
    ("can you explain the difference between a process and a thread in operating systems "
     "and when i should use {x} instead of multithreading in python?",
     ["multiprocessing", "asyncio", "subinterpreters", "concurrent futures",
      "thread pool executor", "process pool executor"]),
    ("how do i configure {x} as a reverse proxy for a fastapi application running behind "
     "gunicorn with multiple workers?",
     ["nginx", "apache", "caddy", "haproxy", "traefik", "envoy"]),
    ("what is the best way to handle database {x} in a production environment without "
     "causing downtime for users?",
     ["migrations", "backups", "replication", "failover", "schema changes",
      "data migration", "index optimization", "query optimization"]),
    ("explain how the immune system responds to a {x} infection and what role antibodies "
     "play in long term immunity",
     ["viral", "bacterial", "fungal", "parasitic", "autoimmune", "allergic"]),
    ("what were the main causes of the {x} revolution and how did economic inequality "
     "contribute to the uprising?",
     ["french", "russian", "american", "industrial", "htsari", "prussian",
      "latin american", "indian", "egyptian", "turkish"]),
    ("can you walk me through how to set up continuous integration for a {x} project "
     "including automated tests and deployment to a staging environment?",
     ["python", "javascript", "rust", "golang", "typescript",
      "csharp", "ruby", "php", "swift", "kotlin", "scala"]),
    ("what are the long term health effects of {x} and what does current research say "
     "about safe levels of consumption?",
     ["caffeine", "alcohol", "sugar", "sodium", "fat", "protein", "fiber",
      "vitamin d", "iron", "zinc", "magnesium", "omega 3"]),
    ("how do i set up a {x} in my home network and what are the security best practices "
     "for protecting it from external threats?",
     ["vpn", "firewall", "dns server", "web server", "mail server",
      "file server", "backup server", "monitoring system", "load balancer",
      "proxy server", "container orchestration", "ci/cd pipeline"]),
    ("what is the most efficient algorithm for {x} and how does its time complexity "
     "compare to alternative approaches in real world scenarios?",
     ["sorting", "searching", "path finding", "graph traversal", "string matching",
      "matrix multiplication", "factorization", "encryption", "compression",
      "hashing", "clustering", "regression"]),
    ("can you compare the performance and memory usage of {x} when processing large "
     "datasets in a production environment?",
     ["pandas", "polars", "spark", "duckdb", "sqlite", "postgresql",
      "mysql", "mongodb", "redis", "cassandra", "elasticsearch", "kafka"]),
    ("what are the pros and cons of using {x} for building a scalable web application "
     "and what deployment strategies work best?",
     ["microservices", "serverless", "monolith", "edge computing", "containerization",
      "server side rendering", "static site generation", "jamstack",
      "graphql", "rest api", "grpc", "websocket"]),
    ("how do i troubleshoot and resolve {x} when it occurs in a distributed system "
     "running across multiple cloud providers?",
     ["network latency", "memory leak", "deadlock", "race condition",
      "cache invalidation", "data inconsistency", "service outage",
      "dns resolution", "ssl certificate error", "cors issue",
      "rate limiting", "connection pool exhaustion"]),
]




# ---------------------------------------------------------------------------
# QWERTY-aware typo mutations (same as test_lexical_match.py)
# ---------------------------------------------------------------------------

_QWERTY = {
    "a": "qws", "b": "vgn", "c": "xdv", "d": "sfe", "e": "wrd", "f": "dgr",
    "g": "fht", "h": "gjy", "i": "uok", "j": "hkn", "k": "jli", "l": "kp",
    "m": "nj", "n": "bmh", "o": "ipl", "p": "ol", "q": "wa", "r": "etf",
    "s": "adw", "t": "ryg", "u": "yij", "v": "cbf", "w": "qes", "x": "zcs",
    "y": "tuh", "z": "xa",
}

_OPS = ["transpose", "delete", "insert", "substitute", "double"]


def _mutate_word(word: str, rng: random.Random) -> tuple[str, str]:
    """Apply one realistic typo operation; returns (changed_word, op_name)."""
    for _ in range(10):
        op = rng.choice(_OPS)
        i = rng.randrange(len(word))
        if op == "transpose" and len(word) >= 4:
            j = min(i, len(word) - 2)
            out = word[:j] + word[j + 1] + word[j] + word[j + 2:]
        elif op == "delete" and len(word) >= 4:
            out = word[:i] + word[i + 1:]
        elif op == "insert":
            ch = rng.choice(_QWERTY.get(word[i], "e"))
            out = word[:i] + ch + word[i:]
        elif op == "substitute":
            ch = rng.choice(_QWERTY.get(word[i], "e"))
            out = word[:i] + ch + word[i + 1:]
        elif op == "double":
            out = word[:i + 1] + word[i] + word[i + 1:]
        else:
            continue
        if out != word:
            return out, op
    return word + word[-1], "double"


def _mutate_query(query: str, rng: random.Random, n_typos: int | None = None) -> tuple[str, list[str]]:
    """Mutate a query with a given number of typos; returns (variant, ops).

    If n_typos is None, the number is drawn from a realistic distribution:
    60% with 1-2 typos, 25% with 3-4 typos, 15% with 5+ typos.
    """
    words = query.split()
    ops: list[str] = []

    mutable = [i for i, w in enumerate(words) if len(w.strip("?!.,-")) >= 3]
    if not mutable:
        return query, ops

    if n_typos is None:
        # Realistic distribution
        roll = rng.random()
        if roll < 0.60:
            n_typos = rng.randint(1, 2)
        elif roll < 0.85:
            n_typos = rng.randint(3, 4)
        else:
            n_typos = min(rng.randint(5, 8), len(mutable))
    else:
        n_typos = min(n_typos, len(mutable))

    # Final safety cap
    n_typos = min(n_typos, len(mutable))
    if n_typos <= 0:
        return query, ops

    for idx in rng.sample(mutable, n_typos):
        raw = words[idx]
        core = raw.strip("?!.,-")
        suffix = raw[len(core):]
        mutated, op = _mutate_word(core, rng)
        words[idx] = mutated + suffix
        ops.append(op)

    return " ".join(words), ops


# ---------------------------------------------------------------------------
# Pair generation: 7,000 typos + 3,000 siblings
# ---------------------------------------------------------------------------

_EXTRA_FACT_SUFFIXES = [
    " and when", " and why", " and give an example", " compared to java",
    " vs c++", " vs rust", " vs go", " vs python", " vs node",
    " vs php", " vs ruby", " vs swift", " vs kotlin",
    " for beginners", " for production", " for large scale",
    " with examples", " with benchmarks", " with diagrams",
]


def _is_letter_similar_swap(x: str, y: str) -> bool:
    """True when two words are themselves letter-similar (grass/grease class)."""
    return SequenceMatcher(None, x, y).ratio() >= 0.72


def generate_pairs(n_typos: int = 7000, n_siblings: int = 3000, seed: int = 42) -> list[dict]:
    """Deterministically generate dicts: {kind, base, variant, info}."""
    rng = random.Random(seed)
    typos, siblings = [], []

    ti = 0
    while len(typos) < n_typos:
        template, slots = TEMPLATES[ti % len(TEMPLATES)]
        ti += 1
        base = template.format(x=rng.choice(slots))
        variant, ops = _mutate_query(base, rng)
        if variant != base:
            typos.append({
                "kind": "typo",
                "base": base,
                "variant": variant,
                "info": "+".join(sorted(set(ops))),
                "n_ops": len(ops),
                "base_len": len(base.split()),
            })

    si = 0
    while len(siblings) < n_siblings:
        template, slots = TEMPLATES[si % len(TEMPLATES)]
        si += 1
        if len(slots) >= 2 and rng.random() > 0.15:
            x1, x2 = rng.sample(slots, 2)
            siblings.append({
                "kind": "sibling",
                "base": template.format(x=x1),
                "variant": template.format(x=x2),
                "info": "entity-swap",
                "swap": (x1, x2),
                "base_len": len(template.format(x=x1).split()),
                "n_ops": 0,
            })
        else:
            base = template.format(x=rng.choice(slots))
            base_words = set(base.rstrip("?.,-").lower().split())
            usable = [
                s for s in _EXTRA_FACT_SUFFIXES
                if not (set(s.split()) - {"and", "an", "to", "a"}) & base_words
            ]
            if not usable:
                continue
            suffix = rng.choice(usable)
            siblings.append({
                "kind": "sibling",
                "base": base,
                "variant": base.rstrip("?.,-") + suffix + "?",
                "info": "extra-fact",
                "swap": None,
                "base_len": len(base.split()),
                "n_ops": 0,
            })

    return typos + siblings


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def _evaluate(pairs: list[dict]) -> dict:
    typo_fail, sibling_fail = [], []
    for p in pairs:
        result = align(p["variant"], p["base"])
        if p["kind"] == "typo" and not result.aligned:
            typo_fail.append({**p, "mismatches": result.mismatches})
        elif p["kind"] == "sibling" and result.aligned:
            sibling_fail.append(p)
    return {"typo_fail": typo_fail, "sibling_fail": sibling_fail}


# ---------------------------------------------------------------------------
# Markdown report writer
# ---------------------------------------------------------------------------

def _pct(good: int, total: int) -> str:
    return f"{good/total:.1%} ({good}/{total})" if total else "n/a"


def write_report() -> Path:
    pairs = generate_pairs()
    eval_result = _evaluate(pairs)
    typo_fail, sibling_fail = eval_result["typo_fail"], eval_result["sibling_fail"]
    typos = [p for p in pairs if p["kind"] == "typo"]
    siblings = [p for p in pairs if p["kind"] == "sibling"]
    fail_set = {(p["base"], p["variant"]) for p in typo_fail}

    lines: list[str] = []
    lines.append("# Typo Resilience Evaluation -- 10,000-pair report")
    lines.append("")
    lines.append("Algorithm: `server/app/services/lexical_match.py::align()` -- word-level fuzzy")
    lines.append("alignment. Typos change *letters*, different questions change *words*: exact")
    lines.append("words cancel first (multiset), every leftover token on both sides must")
    lines.append("fuzzy-match a leftover on the other side, question words never satisfy each")
    lines.append("other. Pure stdlib string math -- no model, no dictionary, never rewrites input.")
    lines.append("")
    lines.append("Dataset: deterministic (seed 42), 38 question templates across 8 domains")
    lines.append("(factual, science, coding, practical, culture, finance, very long).")
    lines.append("Realistic typo intensity: ~60% with 1-2 typos, ~25% with 3-4, ~15% with 5+.")
    lines.append("")

    # --- Headline ---
    n_typos = len(typos)
    n_siblings = len(siblings)
    typo_recall = 1 - len(typo_fail) / n_typos
    sib_reject = 1 - len(sibling_fail) / n_siblings

    lines.append("## Headline results")
    lines.append("")
    lines.append("| Property | Requirement | Result |")
    lines.append("|---|---|---|")
    lines.append(f"| Typo recall (typo'd query passes gate) | >= 95% | **{_pct(n_typos - len(typo_fail), n_typos)}** |")
    lines.append(f"| Sibling rejection (different question blocked) | 100% | **{_pct(n_siblings - len(sibling_fail), n_siblings)}** |")
    lines.append("")

    # --- Intensity breakdown ---
    lines.append("## Typo recall by intensity")
    lines.append("")
    lines.append("| Intensity | Recall |")
    lines.append("|---|---|")
    for label, pred in [("light (1-2 typos)", lambda p: p["n_ops"] <= 2),
                        ("medium (3-4 typos)", lambda p: 3 <= p["n_ops"] <= 4),
                        ("heavy (5-6 typos)", lambda p: 5 <= p["n_ops"] <= 6),
                        ("extreme (7+ typos)", lambda p: p["n_ops"] >= 7)]:
        grp = [p for p in typos if pred(p)]
        bad = [p for p in grp if (p["base"], p["variant"]) in fail_set]
        lines.append(f"| {label} | {_pct(len(grp) - len(bad), len(grp))} |")
    lines.append("")

    # --- Length breakdown ---
    lines.append("## Typo recall by query length")
    lines.append("")
    lines.append("| Length | Recall |")
    lines.append("|---|---|")
    for label, pred in [("short (<= 6 words)", lambda p: p["base_len"] <= 6),
                        ("medium (7-12 words)", lambda p: 7 <= p["base_len"] <= 12),
                        ("long (13-20 words)", lambda p: 13 <= p["base_len"] <= 20),
                        ("very long (> 20 words)", lambda p: p["base_len"] > 20)]:
        grp = [p for p in typos if pred(p)]
        bad = [p for p in grp if (p["base"], p["variant"]) in fail_set]
        lines.append(f"| {label} | {_pct(len(grp) - len(bad), len(grp))} |")
    lines.append("")

    # --- Heatmap: intensity x length ---
    lines.append("## Heatmap: intensity x length -> recall")
    lines.append("")
    lines.append("| | short | medium | long | very long |")
    lines.append("|---|---|---|---|---|")
    for intensity_label, intensity_pred in [("light", lambda p: p["n_ops"] <= 2),
                                              ("medium", lambda p: 3 <= p["n_ops"] <= 4),
                                              ("heavy", lambda p: 5 <= p["n_ops"] <= 6),
                                              ("extreme", lambda p: p["n_ops"] >= 7)]:
        row_vals = []
        for length_label, length_pred in [("short", lambda p: p["base_len"] <= 6),
                                           ("medium", lambda p: 7 <= p["base_len"] <= 12),
                                           ("long", lambda p: 13 <= p["base_len"] <= 20),
                                           ("very long", lambda p: p["base_len"] > 20)]:
            grp = [p for p in typos if intensity_pred(p) and length_pred(p)]
            bad = [p for p in grp if (p["base"], p["variant"]) in fail_set]
            row_vals.append(f"{_pct(len(grp) - len(bad), len(grp))}")
        lines.append(f"| {intensity_label} | {' | '.join(row_vals)} |")
    lines.append("")

    # --- Mutation type breakdown ---
    lines.append("## Typo recall by mutation type")
    lines.append("")
    lines.append("(a pair may combine several ops; counted under each)")
    lines.append("")
    lines.append("| Mutation | Recall |")
    lines.append("|---|---|")
    op_total: Counter = Counter()
    op_fail: Counter = Counter()
    for p in typos:
        for op in p["info"].split("+"):
            op_total[op] += 1
            if (p["base"], p["variant"]) in fail_set:
                op_fail[op] += 1
    for op in sorted(op_total):
        lines.append(f"| {op} | {_pct(op_total[op] - op_fail[op], op_total[op])} |")
    lines.append("")

    # --- Domain breakdown ---
    lines.append("## Typo recall by domain")
    lines.append("")
    lines.append("| Domain | Recall |")
    lines.append("|---|---|")
    domain_ranges = [
        ("factual", 0, 12),
        ("science", 12, 22),
        ("coding", 22, 32),
        ("practical", 32, 40),
        ("culture", 40, 48),
        ("finance", 48, 54),
        ("very_long", 54, len(TEMPLATES)),
    ]
    for domain, start, end in domain_ranges:
        domain_templates = TEMPLATES[start:end]
        grp = [p for p in typos if any(t[0] in p["base"] for t in domain_templates)]
        if not grp:
            continue
        bad = [p for p in grp if (p["base"], p["variant"]) in fail_set]
        lines.append(f"| {domain} | {_pct(len(grp) - len(bad), len(grp))} |")
    lines.append("")

    # --- Sibling breakdown ---
    lines.append("## Sibling rejection by trap type")
    lines.append("")
    lines.append("| Trap | Rejection |")
    lines.append("|---|---|")
    sib_fail_set = {(p["base"], p["variant"]) for p in sibling_fail}
    for info in ("entity-swap", "extra-fact"):
        grp = [p for p in siblings if p["info"] == info]
        bad = [p for p in grp if (p["base"], p["variant"]) in sib_fail_set]
        lines.append(f"| {info} | {_pct(len(grp) - len(bad), len(grp))} |")
    lines.append("")

    # --- Breaking point analysis ---
    lines.append("## Breaking point analysis")
    lines.append("")
    lines.append("At what intensity/length does recall drop below thresholds?")
    lines.append("")
    lines.append("| Recall threshold | Intensity cutoff | Length cutoff |")
    lines.append("|---|---|---|")
    for threshold in [0.99, 0.95, 0.90, 0.80]:
        intensity_cutoff = "none"
        for label, pred in [("light", lambda p: p["n_ops"] <= 2),
                            ("medium", lambda p: 3 <= p["n_ops"] <= 4),
                            ("heavy", lambda p: 5 <= p["n_ops"] <= 6),
                            ("extreme", lambda p: p["n_ops"] >= 7)]:
            grp = [p for p in typos if pred(p)]
            bad = [p for p in grp if (p["base"], p["variant"]) in fail_set]
            recall = (len(grp) - len(bad)) / len(grp) if grp else 1.0
            if recall < threshold:
                intensity_cutoff = label
                break
        length_cutoff = "none"
        for label, pred in [("short", lambda p: p["base_len"] <= 6),
                            ("medium", lambda p: 7 <= p["base_len"] <= 12),
                            ("long", lambda p: 13 <= p["base_len"] <= 20),
                            ("very long", lambda p: p["base_len"] > 20)]:
            grp = [p for p in typos if pred(p)]
            bad = [p for p in grp if (p["base"], p["variant"]) in fail_set]
            recall = (len(grp) - len(bad)) / len(grp) if grp else 1.0
            if recall < threshold:
                length_cutoff = label
                break
        lines.append(f"| < {threshold:.0%} | {intensity_cutoff} | {length_cutoff} |")
    lines.append("")

    # --- Failures ---
    lines.append("## Failures")
    lines.append("")
    hard_fail = [p for p in sibling_fail if not _is_letter_similar_swap(*p.get("swap", ("", "")))]
    soft_fail = [p for p in sibling_fail if _is_letter_similar_swap(*p.get("swap", ("", "")))]

    if hard_fail:
        lines.append("### Sibling pairs wrongly aligned (SAFETY violations -- would risk a wrong answer)")
        lines.append("")
        for p in hard_fail[:20]:
            lines.append(f"- `{p['base']}` ~ `{p['variant']}` ({p['info']})")
        if len(hard_fail) > 20:
            lines.append(f"- ... and {len(hard_fail) - 20} more")
        lines.append("")
    else:
        lines.append("**No hard safety violations** -- every normally-worded different-question pair was vetoed.")
        lines.append("")

    if soft_fail:
        lines.append("### Letter-similar word-pair passthroughs (validator's job, documented class)")
        lines.append("")
        lines.append("These swapped words are themselves within typo distance (grass/grease,")
        lines.append("trial/trail class) -- indistinguishable from a typo at the letter level by")
        lines.append("definition. The gate passes them to the **LLM validator**, which makes the")
        lines.append("final serve/reject decision. Gate leakage rate: "
                     f"**{len(soft_fail)}/{n_siblings} = {len(soft_fail)/n_siblings:.2%}**.")
        lines.append("")
        for p in soft_fail[:20]:
            swap_str = f"swap: {p['swap'][0]} / {p['swap'][1]}" if p.get("swap") else ""
            lines.append(f"- `{p['base']}` ~ `{p['variant']}` ({p['info']}) {swap_str}".strip())
        if len(soft_fail) > 20:
            lines.append(f"- ... and {len(soft_fail) - 20} more")
        lines.append("")

    if typo_fail:
        lines.append("### Typo pairs not aligned (safe direction -- lost cache hit, LLM answers)")
        lines.append("")
        lines.append("| Variant | Base | Mismatches | Ops |")
        lines.append("|---|---|---|---|")
        for p in typo_fail[:50]:
            mm = ", ".join(f"{a}<->{b}" for a, b in p["mismatches"])
            lines.append(f"| `{p['variant'][:50]}` | `{p['base'][:50]}` | {mm} | {p['info']} |")
        if len(typo_fail) > 50:
            lines.append(f"- ... and {len(typo_fail) - 50} more")
        lines.append("")
    else:
        lines.append("No typo pairs were rejected.")
        lines.append("")

    # --- Comparison to existing 1,500-pair test ---
    lines.append("## Comparison to existing 1,500-pair test")
    lines.append("")
    lines.append("| Metric | 1,500-pair test | 10,000-pair test |")
    lines.append("|---|---|---|")
    lines.append(f"| Typo recall | 99.1% (743/750) | **{_pct(n_typos - len(typo_fail), n_typos)}** |")
    lines.append(f"| Sibling rejection | 99.9% (749/750) | **{_pct(n_siblings - len(sibling_fail), n_siblings)}** |")
    lines.append(f"| Templates | 28 | {len(TEMPLATES)} |")
    lines.append(f"| Max typos per query | 3 | up to 8 |")
    lines.append(f"| Max query length | ~30 words | ~40 words |")
    lines.append("")

    lines.append(f"Total: **{len(pairs)}** generated pairs ({n_typos} typo + {n_siblings} sibling).")
    lines.append("")
    lines.append("Regenerate: `cd server && uv run --group test python tests/test_typo_resilience.py`")
    lines.append("")

    out_path = Path(__file__).resolve().parents[2] / "docs" / "typo-resilience-report.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# Pytest assertions
# ---------------------------------------------------------------------------

def test_10000_pairs_generated():
    pairs = generate_pairs()
    assert len(pairs) == 10000
    n_typos = sum(1 for p in pairs if p["kind"] == "typo")
    n_siblings = len(pairs) - n_typos
    assert n_typos == 7000
    assert n_siblings == 3000


def test_typo_recall_overall():
    pairs = generate_pairs()
    typos = [p for p in pairs if p["kind"] == "typo"]
    n = len(typos)
    failed = [p for p in typos if not align(p["variant"], p["base"]).aligned]
    recall = 1 - len(failed) / n
    assert recall >= 0.95, (
        f"typo recall {recall:.1%} below 95%. {len(failed)}/{n} failed. "
        + "; ".join(f"{p['variant']!r}" for p in failed[:5])
    )


def test_typo_recall_light_intensity():
    pairs = generate_pairs()
    typos = [p for p in pairs if p["kind"] == "typo" and p["n_ops"] <= 2]
    n = len(typos)
    failed = [p for p in typos if not align(p["variant"], p["base"]).aligned]
    recall = 1 - len(failed) / n
    assert recall >= 0.98, (
        f"light intensity recall {recall:.1%} below 98%. {len(failed)}/{n} failed."
    )


def test_typo_recall_medium_intensity():
    pairs = generate_pairs()
    typos = [p for p in pairs if p["kind"] == "typo" and 3 <= p["n_ops"] <= 4]
    n = len(typos)
    failed = [p for p in typos if not align(p["variant"], p["base"]).aligned]
    recall = 1 - len(failed) / n
    assert recall >= 0.90, (
        f"medium intensity recall {recall:.1%} below 90%. {len(failed)}/{n} failed."
    )


def test_typo_recall_heavy_intensity():
    pairs = generate_pairs()
    typos = [p for p in pairs if p["kind"] == "typo" and 5 <= p["n_ops"] <= 6]
    n = len(typos)
    if n == 0:
        return
    failed = [p for p in typos if not align(p["variant"], p["base"]).aligned]
    recall = 1 - len(failed) / n
    assert recall >= 0.80, (
        f"heavy intensity recall {recall:.1%} below 80%. {len(failed)}/{n} failed."
    )


def test_typo_recall_short_queries():
    pairs = generate_pairs()
    typos = [p for p in pairs if p["kind"] == "typo" and p["base_len"] <= 6]
    n = len(typos)
    failed = [p for p in typos if not align(p["variant"], p["base"]).aligned]
    recall = 1 - len(failed) / n
    assert recall >= 0.95, (
        f"short query recall {recall:.1%} below 95%. {len(failed)}/{n} failed."
    )


def test_typo_recall_medium_queries():
    pairs = generate_pairs()
    typos = [p for p in pairs if p["kind"] == "typo" and 7 <= p["base_len"] <= 12]
    n = len(typos)
    failed = [p for p in typos if not align(p["variant"], p["base"]).aligned]
    recall = 1 - len(failed) / n
    assert recall >= 0.93, (
        f"medium query recall {recall:.1%} below 93%. {len(failed)}/{n} failed."
    )


def test_typo_recall_long_queries():
    pairs = generate_pairs()
    typos = [p for p in pairs if p["kind"] == "typo" and 13 <= p["base_len"] <= 20]
    n = len(typos)
    failed = [p for p in typos if not align(p["variant"], p["base"]).aligned]
    recall = 1 - len(failed) / n
    assert recall >= 0.90, (
        f"long query recall {recall:.1%} below 90%. {len(failed)}/{n} failed."
    )


def test_typo_recall_very_long_queries():
    pairs = generate_pairs()
    typos = [p for p in pairs if p["kind"] == "typo" and p["base_len"] > 20]
    n = len(typos)
    if n == 0:
        return
    failed = [p for p in typos if not align(p["variant"], p["base"]).aligned]
    recall = 1 - len(failed) / n
    assert recall >= 0.85, (
        f"very long query recall {recall:.1%} below 85%. {len(failed)}/{n} failed."
    )


def test_sibling_rejection_hard_zero():
    pairs = generate_pairs()
    siblings = [p for p in pairs if p["kind"] == "sibling"]
    n = len(siblings)
    failed = [p for p in siblings if align(p["variant"], p["base"]).aligned]
    hard_fail = [p for p in failed if not _is_letter_similar_swap(*p.get("swap", ("", "")))]
    assert not hard_fail, (
        f"{len(hard_fail)} sibling pairs wrongly aligned (safety violation): "
        + "; ".join(f"{p['base']!r} ~ {p['variant']!r}" for p in hard_fail[:5])
    )


def test_sibling_rejection_overall():
    pairs = generate_pairs()
    siblings = [p for p in pairs if p["kind"] == "sibling"]
    n = len(siblings)
    failed = [p for p in siblings if align(p["variant"], p["base"]).aligned]
    assert len(failed) / n <= 0.01, (
        f"gate leakage {len(failed)}/{n} exceeds 1%: "
        + "; ".join(f"{p['base']!r} ~ {p['variant']!r}" for p in failed[:5])
    )


def test_typo_intensity_distribution():
    """Verify the generated typo pairs follow the realistic intensity distribution."""
    pairs = generate_pairs()
    typos = [p for p in pairs if p["kind"] == "typo"]
    n = len(typos)
    light = sum(1 for p in typos if p["n_ops"] <= 2)
    medium = sum(1 for p in typos if 3 <= p["n_ops"] <= 4)
    heavy = sum(1 for p in typos if p["n_ops"] >= 5)

    light_pct = light / n
    medium_pct = medium / n
    heavy_pct = heavy / n

    assert light_pct >= 0.50, f"light intensity {light_pct:.0%} below expected 60%"
    assert medium_pct >= 0.15, f"medium intensity {medium_pct:.0%} below expected 25%"
    assert heavy_pct >= 0.05, f"heavy intensity {heavy_pct:.0%} below expected 15%"


def test_query_length_distribution():
    """Verify the generated pairs cover a wide length range."""
    pairs = generate_pairs()
    typos = [p for p in pairs if p["kind"] == "typo"]

    short = sum(1 for p in typos if p["base_len"] <= 6)
    medium = sum(1 for p in typos if 7 <= p["base_len"] <= 12)
    long = sum(1 for p in typos if 13 <= p["base_len"] <= 20)
    very_long = sum(1 for p in typos if p["base_len"] > 20)
    total = len(typos)

    assert short / total >= 0.05, f"short queries too few: {short}/{total}"
    assert medium / total >= 0.30, f"medium queries too few: {medium}/{total}"
    assert long / total >= 0.10, f"long queries too few: {long}/{total}"
    assert very_long / total >= 0.05, f"very long queries too few: {very_long}/{total}"


if __name__ == "__main__":
    path = write_report()
    print(f"report written: {path}")
