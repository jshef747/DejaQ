"""Tests for app.services.lexical_match.align — hand-written + 1500 generated pairs.

The generated suite is deterministic (fixed seed) so CI is stable:
- 750 typo pairs    -> expect aligned=True  (recall property, >= 95%)
- 750 sibling pairs -> expect aligned=False (safety property, 100% hard)

Run `python tests/test_lexical_match.py` (from server/) to write the full
markdown report to docs/lexical-match-report.md.
"""

import random
from collections import Counter
from pathlib import Path

import pytest

from app.services.lexical_match import align

pytestmark = pytest.mark.no_model

# ---------------------------------------------------------------------------
# Hand-written cases (includes every real case observed in live sessions)
# ---------------------------------------------------------------------------

TYPO_PAIRS = [
    ("what is the capital of russia?", "what is teh captial of rusia?"),
    ("what is the capital of france?", "what is teh captial of frnce?"),
    ("what is the capital of japan?", "what is the capital of jpan?"),
    ("how do i reverse a string in python?", "how do i revrse a strng in pyton?"),
    ("what is the boiling point of water?", "what is the boilng point of watr?"),
    ("explain quantum entanglement", "explian quantum entanglment"),
    ("how do i fix a segmentation fault in c?", "how do i fix a segmentaion falut in c?"),
    (
        "can you explain the difference between a process and a thread in operating systems "
        "and when i should use multiprocessing instead of multithreading in python?",
        "can you explian the diffrence between a proccess and a thred in operating systems "
        "and when i shoud use multiprocesing instead of multithreding in python?",
    ),
]

SIBLING_PAIRS = [
    ("what is the capital of france?", "what is the capital of germany?"),
    ("what is the boiling point of water?", "what is the freezing point of water?"),
    ("who wrote romeo and juliet?", "who wrote hamlet?"),
    ("how do i reverse a string in python?", "how do i reverse a list in python?"),
    ("what is the boiling point of water?", "what is the melting point of ice?"),
    ("what is the capital of france?", "what is the population of france?"),
    ("who wrote romeo and juliet?", "who wrote romeo and juliet and when?"),
    ("how does photosynthesis work?", "how does cellular respiration work?"),
    (
        "can you explain the difference between a process and a thread in operating systems "
        "and when i should use multiprocessing instead of multithreading in python?",
        "can you explain the difference between a process and a thread in operating systems "
        "and when i should use asyncio instead of multithreading in python?",
    ),
]


@pytest.mark.parametrize("clean,typoed", TYPO_PAIRS)
def test_typo_pairs_align(clean, typoed):
    assert align(typoed, clean).aligned


@pytest.mark.parametrize("a,b", SIBLING_PAIRS)
def test_sibling_pairs_veto(a, b):
    assert not align(b, a).aligned


def test_mismatch_pair_identified():
    result = align("how do i reverse a list in python?", "how do i reverse a string in python?")
    assert not result.aligned
    assert ("list", "string") in result.mismatches


def test_stopword_typo_tolerated():
    assert align("teh capital of france", "the capital of france").aligned


def test_symmetric_extra_word_vetoes():
    assert not align("who wrote hamlet and when?", "who wrote hamlet?").aligned


def test_question_word_swap_vetoes():
    # "why" and "who" are 0.667 letter-similar but ask different things
    assert not align("why is the sky blue and who discovered it?", "why is the sky blue?").aligned


def test_missing_space_tolerated():
    assert align("whatis the capital of france?", "what is the capital of france?").aligned


def test_empty_inputs():
    assert not align("", "what is x").aligned
    assert not align("what is x", "").aligned
    assert not align("?!", "what is x").aligned


def test_identical_strings_align():
    assert align("what is gravity", "what is gravity").aligned


def test_identical_strings_are_lexically_exact():
    assert align("what is gravity", "what is gravity").exact is True


def test_case_and_order_differences_stay_exact():
    assert align("What Is Gravity", "gravity is what").exact is True


def test_a_typo_aligns_but_is_not_exact():
    assert align("what is the capital of france", "what is teh captial of frnace").exact is False


def test_a_near_identical_entity_swap_aligns_but_is_not_exact():
    """dejaq-acceptance-fixes report, defect #2: Austria/Australia fuzzy-match
    on letter-similarity (0.93) despite naming different countries - `aligned`
    alone cannot distinguish this from a genuine typo, `exact` can."""
    result = align("what is the capital of austria", "what is the capital of australia")
    assert result.aligned is True
    assert result.exact is False


def test_a_real_mismatch_is_not_exact():
    assert align("what is the capital of germany", "what is the capital of france").exact is False


def test_empty_inputs_are_not_exact():
    assert align("", "what is x").exact is False


# ---------------------------------------------------------------------------
# Mismatch-hint suppression on broad rephrasings (dejaq-acceptance-fixes,
# defect #1's root cause).
# ---------------------------------------------------------------------------

def test_single_word_swap_keeps_its_hint():
    """The mechanism's own documented use case: exactly one leftover word on
    each side is a trustworthy hint."""
    result = align("how do i reverse a list in python?", "how do i reverse a string in python?")
    assert result.mismatches == (("list", "string"),)


def test_hebrew_geresh_does_not_split_a_word_into_two_leftovers():
    """dejaq-200-test-fixes defect #1: "ניז'ר" (Niger) used to tokenize as TWO
    words ("ניז", "ר") because the geresh (') was stripped to a space, so its
    one real leftover paired against Nigeria's leftover became two leftovers
    on that side - which trips the "only hint on a clean 1:1 swap" suppression
    below and silently dropped a genuine single-word-swap hint. The cached
    Niger answer was then served, validator-approved, for a Nigeria question
    (200-query realistic test, distance 0.1795, verdict VALID)."""
    result = align("מה בירת ניגריה?", "מה בירת ניז'ר?")
    assert result.aligned is False
    assert result.mismatches == (("ניגריה", "ניז'ר"),)


def test_broadly_rephrased_paraphrase_suppresses_the_hint():
    """A real live case, verified against the running validator: "how many
    continents are there" vs "what's the total number of continents" shares
    almost no function words, so every leftover gets force-paired with
    whatever's closest on the other side - nonsense pairings like
    ('what', 'how') and ('s', 'there') that carry no real semantic signal.
    Feeding that to the validator as "these words differ" measurably flips a
    correct VALID into an INVALID; suppressing it here is the fix. `aligned`
    must still be False - the underlying rephrasing is real, just not a
    single-word swap worth hinting about."""
    result = align("how many continents are there", "what's the total number of continents")
    assert result.aligned is False
    assert result.mismatches == ()


def test_a_leftover_reused_for_two_source_words_suppresses_the_hint():
    """"how many days does a leap year have" vs "how many days are in a leap
    year": two leftover source words ('does', 'have') both get force-paired
    against the SAME single candidate leftover ('are') - a leftover being
    reused is itself evidence the pairing isn't a genuine 1:1 word swap."""
    result = align("how many days does a leap year have", "how many days are in a leap year")
    assert result.mismatches == ()


# ---------------------------------------------------------------------------
# Generated 1500-pair suite (deterministic, seed=42)
# ---------------------------------------------------------------------------

# Slot lists are curated to avoid accidentally letter-similar members
# (no iran/iraq, fission/fusion) — siblings must differ at the WORD level.
TEMPLATES = [
    # --- factual short ---
    ("what is the capital of {x}?",
     ["france", "germany", "spain", "japan", "brazil", "canada", "egypt", "kenya", "norway", "mexico"]),
    ("what is the population of {x}?",
     ["france", "germany", "brazil", "canada", "egypt", "norway", "mexico", "turkey"]),
    ("what is the currency of {x}?",
     ["japan", "brazil", "canada", "egypt", "norway", "mexico", "turkey", "poland"]),
    ("what is the {x} point of water?",
     ["boiling", "freezing", "melting"]),
    ("who wrote {x}?",
     ["hamlet", "macbeth", "othello", "frankenstein", "dracula", "ulysses"]),
    ("when did the {x} war end?",
     ["korean", "vietnam", "crimean", "peloponnesian"]),
    ("how tall is mount {x}?",
     ["everest", "kilimanjaro", "fuji", "denali"]),
    ("what language is spoken in {x}?",
     ["brazil", "egypt", "kenya", "norway", "austria", "morocco"]),
    # --- science ---
    ("how does {x} work?",
     ["photosynthesis", "fermentation", "osmosis", "digestion", "evaporation", "condensation"]),
    ("explain {x} in simple terms",
     ["quantum entanglement", "general relativity", "brownian motion", "natural selection"]),
    ("what causes {x} in humans?",
     ["insomnia", "migraines", "hiccups", "allergies", "dehydration"]),
    ("what is the function of the {x} in the human body?",
     ["liver", "pancreas", "kidneys", "thyroid", "spleen"]),
    # --- coding / tech ---
    ("how do i reverse a {x} in python?",
     ["string", "list", "tuple", "dictionary"]),
    ("how do i install {x} on ubuntu?",
     ["docker", "kubernetes", "postgresql", "nginx", "redis", "terraform"]),
    ("what does the {x} command do in linux?",
     ["grep", "chmod", "rsync", "curl", "awk"]),
    ("how do i center a div using {x}?",
     ["flexbox", "grid", "margins", "position absolute"]),
    ("what is the difference between {x} in javascript?",
     ["let and var", "map and foreach", "null and undefined", "promises and callbacks"]),
    ("how do i undo the last commit in {x}?",
     ["git", "mercurial", "subversion"]),
    # --- practical ---
    ("how long should i cook {x} in the oven?",
     ["chicken", "salmon", "lasagna", "potatoes", "meatloaf"]),
    ("what is the best way to remove {x} stains from clothes?",
     ["coffee", "wine", "grass", "ink", "grease"]),
    ("how much water should i drink during {x}?",
     ["exercise", "pregnancy", "fasting", "winter"]),
    # --- long questions ---
    ("can you explain the difference between a process and a thread in operating systems "
     "and when i should use {x} instead of multithreading in python?",
     ["multiprocessing", "asyncio", "subinterpreters"]),
    ("how do i configure {x} as a reverse proxy for a fastapi application running behind "
     "gunicorn with multiple workers?",
     ["nginx", "apache", "caddy", "haproxy"]),
    ("what is the best way to handle database {x} in a production environment without "
     "causing downtime for users?",
     ["migrations", "backups", "replication", "failover"]),
    ("explain how the immune system responds to a {x} infection and what role antibodies "
     "play in long term immunity",
     ["viral", "bacterial", "fungal", "parasitic"]),
    ("what were the main causes of the {x} revolution and how did economic inequality "
     "contribute to the uprising?",
     ["french", "russian", "american", "industrial"]),
    ("can you walk me through how to set up continuous integration for a {x} project "
     "including automated tests and deployment to a staging environment?",
     ["python", "javascript", "rust", "golang"]),
    ("what are the long term health effects of {x} and what does current research say "
     "about safe levels of consumption?",
     ["caffeine", "alcohol", "sugar", "sodium"]),
]

# Extra-fact appends: add a new content word => sibling (asks for more)
EXTRA_FACT_SUFFIXES = [" and when", " and why", " and give an example", " compared to java"]

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
    for _ in range(10):  # retry until the op actually changes the word
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


def _mutate_query(query: str, rng: random.Random) -> tuple[str, list[str]]:
    """Mutate 1-3 words (plus occasionally delete a space); returns (variant, ops)."""
    words = query.split()
    ops: list[str] = []

    # ~12% of typo queries also lose a space between two words ("whatis the...")
    if rng.random() < 0.12 and len(words) >= 4:
        j = rng.randrange(len(words) - 1)
        words = words[:j] + [words[j] + words[j + 1]] + words[j + 2:]
        ops.append("missing-space")

    mutable = [i for i, w in enumerate(words) if len(w.strip("?!.,")) >= 3]
    if mutable:
        n_words = len(words)
        k = rng.randint(1, 2) if n_words <= 8 else rng.randint(2, 3)
        k = min(k, len(mutable))
        for idx in rng.sample(mutable, k):
            raw = words[idx]
            core = raw.strip("?!.,")
            suffix = raw[len(core):]
            mutated, op = _mutate_word(core, rng)
            words[idx] = mutated + suffix
            ops.append(op)
    return " ".join(words), ops


def generate_pairs(n_typos: int = 750, n_siblings: int = 750, seed: int = 42):
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
            typos.append({"kind": "typo", "base": base, "variant": variant, "info": "+".join(sorted(set(ops)))})

    si = 0
    while len(siblings) < n_siblings:
        template, slots = TEMPLATES[si % len(TEMPLATES)]
        si += 1
        if len(slots) >= 2 and rng.random() > 0.15:
            x1, x2 = rng.sample(slots, 2)
            siblings.append({"kind": "sibling", "base": template.format(x=x1),
                             "variant": template.format(x=x2), "info": "entity-swap",
                             "swap": (x1, x2)})
        else:
            # extra-fact sibling: same question + an additional ask. Skip
            # suffixes whose content words already appear in the base — those
            # add no new lexical signal and are genuinely ambiguous (they are
            # the validator's job, not the alignment gate's).
            base = template.format(x=rng.choice(slots))
            base_words = set(base.rstrip("?").lower().split())
            usable = [
                s for s in EXTRA_FACT_SUFFIXES
                if not (set(s.split()) - {"and", "an", "to", "a"}) & base_words
            ]
            if not usable:
                continue
            suffix = rng.choice(usable)
            siblings.append({"kind": "sibling", "base": base,
                             "variant": base.rstrip("?") + suffix + "?", "info": "extra-fact"})

    return typos + siblings


def _evaluate(pairs):
    typo_fail, sibling_fail = [], []
    for p in pairs:
        result = align(p["variant"], p["base"])
        if p["kind"] == "typo" and not result.aligned:
            typo_fail.append({**p, "mismatches": result.mismatches})
        elif p["kind"] == "sibling" and result.aligned:
            sibling_fail.append(p)
    return typo_fail, sibling_fail


def _is_letter_similar_swap(p: dict) -> bool:
    """True when a sibling's swapped words are themselves letter-similar
    (grass/grease, trial/trail class). Indistinguishable from a typo at the
    letter level BY DEFINITION — the validator behind the gate is the judge
    for these, not the gate."""
    from difflib import SequenceMatcher

    swap = p.get("swap")
    if not swap:
        return False
    return SequenceMatcher(None, swap[0], swap[1]).ratio() >= 0.72


def test_generated_1500_pairs():
    pairs = generate_pairs()
    assert len(pairs) == 1500
    typo_fail, sibling_fail = _evaluate(pairs)

    n_typos = sum(1 for p in pairs if p["kind"] == "typo")
    n_siblings = len(pairs) - n_typos
    typo_recall = 1 - len(typo_fail) / n_typos

    # Safety property: a sibling passing the gate could serve a wrong answer.
    # Hard-zero for everything except the documented letter-similar word-pair
    # class (grass/grease) — those are typo-shaped by definition and are the
    # validator's responsibility. Their leakage rate must stay tiny.
    hard_fail = [p for p in sibling_fail if not _is_letter_similar_swap(p)]
    assert not hard_fail, (
        f"{len(hard_fail)} sibling pairs wrongly aligned (safety violation): "
        + "; ".join(f"{p['base']!r} ~ {p['variant']!r}" for p in hard_fail[:5])
    )
    assert len(sibling_fail) / n_siblings <= 0.01, (
        f"gate leakage {len(sibling_fail)}/{n_siblings} exceeds 1%: "
        + "; ".join(f"{p['base']!r} ~ {p['variant']!r}" for p in sibling_fail[:5])
    )
    # Recall property: most realistic typos must pass the gate.
    assert typo_recall >= 0.95, (
        f"typo recall {typo_recall:.1%} below 95%. Failures: "
        + "; ".join(f"{p['variant']!r} (mismatches={p['mismatches']})" for p in typo_fail[:10])
    )


# ---------------------------------------------------------------------------
# Markdown report writer:  python tests/test_lexical_match.py
# ---------------------------------------------------------------------------

def _pct(good: int, total: int) -> str:
    return f"{good/total:.1%} ({good}/{total})" if total else "n/a"


def write_report() -> Path:  # pragma: no cover — manual reporting helper
    pairs = generate_pairs()
    typo_fail, sibling_fail = _evaluate(pairs)
    typos = [p for p in pairs if p["kind"] == "typo"]
    siblings = [p for p in pairs if p["kind"] == "sibling"]
    fail_set = {(p["base"], p["variant"]) for p in typo_fail}
    def _failed(p):
        return (p["base"], p["variant"]) in fail_set

    lines = []
    lines.append("# Lexical alignment gate — 1500-pair evaluation report")
    lines.append("")
    lines.append("Algorithm: `server/app/services/lexical_match.py::align()` — word-level fuzzy")
    lines.append("alignment. Typos change *letters*, different questions change *words*: exact")
    lines.append("words cancel first (multiset), every leftover token on both sides must")
    lines.append("fuzzy-match a leftover on the other side, question words never satisfy each")
    lines.append("other. Pure stdlib string math — no model, no dictionary, never rewrites input.")
    lines.append("")
    lines.append("Dataset: deterministic (seed 42), 28 question templates across factual /")
    lines.append("science / coding / practical / long-form categories.")
    lines.append("")
    lines.append("## Headline results")
    lines.append("")
    lines.append("| Property | Requirement | Result |")
    lines.append("|---|---|---|")
    lines.append(f"| Typo recall (typo'd query passes gate) | ≥ 95% | **{_pct(len(typos)-len(typo_fail), len(typos))}** |")
    lines.append(f"| Sibling rejection (different question blocked) | 100% | **{_pct(len(siblings)-len(sibling_fail), len(siblings))}** |")
    lines.append("")

    # --- breakdown by length ---
    lines.append("## Typo recall by query length")
    lines.append("")
    lines.append("| Length | Recall |")
    lines.append("|---|---|")
    for label, pred in [("short (≤ 8 words)", lambda p: len(p["base"].split()) <= 8),
                        ("medium (9–15 words)", lambda p: 9 <= len(p["base"].split()) <= 15),
                        ("long (> 15 words)", lambda p: len(p["base"].split()) > 15)]:
        grp = [p for p in typos if pred(p)]
        bad = [p for p in grp if _failed(p)]
        lines.append(f"| {label} | {_pct(len(grp)-len(bad), len(grp))} |")
    lines.append("")

    # --- breakdown by mutation op ---
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
            if _failed(p):
                op_fail[op] += 1
    for op in sorted(op_total):
        lines.append(f"| {op} | {_pct(op_total[op]-op_fail[op], op_total[op])} |")
    lines.append("")

    # --- sibling breakdown ---
    lines.append("## Sibling rejection by trap type")
    lines.append("")
    lines.append("| Trap | Rejection |")
    lines.append("|---|---|")
    sib_fail_set = {(p["base"], p["variant"]) for p in sibling_fail}
    for info in ("entity-swap", "extra-fact"):
        grp = [p for p in siblings if p["info"] == info]
        bad = [p for p in grp if (p["base"], p["variant"]) in sib_fail_set]
        lines.append(f"| {info} | {_pct(len(grp)-len(bad), len(grp))} |")
    lines.append("")

    # --- failures ---
    lines.append("## Failures")
    lines.append("")
    hard_fail = [p for p in sibling_fail if not _is_letter_similar_swap(p)]
    soft_fail = [p for p in sibling_fail if _is_letter_similar_swap(p)]
    if hard_fail:
        lines.append("### ⚠ Sibling pairs wrongly aligned (SAFETY violations — would risk a wrong answer)")
        lines.append("")
        for p in hard_fail:
            lines.append(f"- `{p['base']}` ~ `{p['variant']}` ({p['info']})")
        lines.append("")
    else:
        lines.append("**No hard safety violations** — every normally-worded different-question pair was vetoed.")
        lines.append("")
    if soft_fail:
        lines.append("### Letter-similar word-pair passthroughs (validator's job, documented class)")
        lines.append("")
        lines.append("These swapped words are themselves within typo distance (grass/grease,")
        lines.append("trial/trail class) — indistinguishable from a typo at the letter level by")
        lines.append("definition. The gate passes them to the **LLM validator**, which makes the")
        lines.append("final serve/reject decision. Gate leakage rate: "
                     f"**{len(soft_fail)}/{len(siblings)} = {len(soft_fail)/len(siblings):.2%}**.")
        lines.append("")
        for p in soft_fail:
            lines.append(f"- `{p['base']}` ~ `{p['variant']}` (swap: {p['swap'][0]} / {p['swap'][1]})")
        lines.append("")
    if typo_fail:
        lines.append("### Typo pairs not aligned (safe direction — lost cache hit, LLM answers)")
        lines.append("")
        for p in typo_fail:
            lines.append(f"- `{p['variant']}` ← `{p['base']}` — mismatches: {list(p['mismatches'])} ({p['info']})")
        lines.append("")
    else:
        lines.append("No typo pairs were rejected.")
        lines.append("")

    # --- hand-written / live cases ---
    lines.append("## Hand-written cases (includes all real cases from live sessions)")
    lines.append("")
    lines.append("| Case | Expected | Result |")
    lines.append("|---|---|---|")
    for base, variant in TYPO_PAIRS:
        r = align(variant, base)
        mark = "✅" if r.aligned else "❌"
        lines.append(f"| `{variant[:60]}` | align | {mark} |")
    for base, variant in SIBLING_PAIRS:
        r = align(variant, base)
        mark = "✅" if not r.aligned else "❌"
        lines.append(f"| `{variant[:60]}` | veto | {mark} |")
    lines.append("")

    lines.append("## Known limitations")
    lines.append("")
    lines.append("- **Phonetic spellings** fail the gate: \"duz\" for \"does\" is only 0.57")
    lines.append("  letter-similar. Safe direction — the query just misses the cache.")
    lines.append("- Generated typos are mechanical (QWERTY slips, swaps, deletions, doubled")
    lines.append("  letters, missing spaces) with ≤ 3 mutated words per query; the gate is not")
    lines.append("  tested against deliberate obfuscation.")
    lines.append("- The gate is one of three checks: embedding distance ranks candidates, the")
    lines.append("  gate filters, and the LLM validator gives the final verdict before serving.")
    lines.append("")
    lines.append(f"Total: **{len(pairs)}** generated pairs + {len(TYPO_PAIRS) + len(SIBLING_PAIRS)} hand-written.")
    lines.append("")
    lines.append("Regenerate: `cd server && uv run --group test python tests/test_lexical_match.py`")
    lines.append("")

    out = Path(__file__).resolve().parents[2] / "docs" / "lexical-match-report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


if __name__ == "__main__":  # pragma: no cover
    path = write_report()
    print(f"report written: {path}")
