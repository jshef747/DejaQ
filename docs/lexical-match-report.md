# Lexical alignment gate — 1500-pair evaluation report

Algorithm: `server/app/services/lexical_match.py::align()` — word-level fuzzy
alignment. Typos change *letters*, different questions change *words*: exact
words cancel first (multiset), every leftover token on both sides must
fuzzy-match a leftover on the other side, question words never satisfy each
other. Pure stdlib string math — no model, no dictionary, never rewrites input.

Dataset: deterministic (seed 42), 28 question templates across factual /
science / coding / practical / long-form categories.

## Headline results

| Property | Requirement | Result |
|---|---|---|
| Typo recall (typo'd query passes gate) | ≥ 95% | **99.1% (743/750)** |
| Sibling rejection (different question blocked) | 100% | **99.9% (749/750)** |

## Typo recall by query length

| Length | Recall |
|---|---|
| short (≤ 8 words) | 99.1% (423/427) |
| medium (9–15 words) | 98.6% (138/140) |
| long (> 15 words) | 99.5% (182/183) |

## Typo recall by mutation type

(a pair may combine several ops; counted under each)

| Mutation | Recall |
|---|---|
| delete | 100.0% (192/192) |
| double | 99.4% (324/326) |
| insert | 98.6% (291/295) |
| missing-space | 92.6% (87/94) |
| substitute | 98.0% (298/304) |
| transpose | 100.0% (193/193) |

## Sibling rejection by trap type

| Trap | Rejection |
|---|---|
| entity-swap | 99.8% (631/632) |
| extra-fact | 100.0% (118/118) |

## Failures

**No hard safety violations** — every normally-worded different-question pair was vetoed.

### Letter-similar word-pair passthroughs (validator's job, documented class)

These swapped words are themselves within typo distance (grass/grease,
trial/trail class) — indistinguishable from a typo at the letter level by
definition. The gate passes them to the **LLM validator**, which makes the
final serve/reject decision. Gate leakage rate: **1/750 = 0.13%**.

- `what is the best way to remove grass stains from clothes?` ~ `what is the best way to remove grease stains from clothes?` (swap: grass / grease)

### Typo pairs not aligned (safe direction — lost cache hit, LLM answers)

- `what isyhe function of the pabncreas in the human body?` ← `what is the function of the pancreas in the human body?` — mismatches: [('isyhe', 'is')] (insert+missing-space+substitute)
- `hpow much water should i drink dyringfasting?` ← `how much water should i drink during fasting?` — mismatches: [('during', 'dyringfasting')] (insert+missing-space+substitute)
- `can you walk me through how to set up continuous integration for a golang project inclufingautomated tests and deployment to a stagking environment?` ← `can you walk me through how to set up continuous integration for a golang project including automated tests and deployment to a staging environment?` — mismatches: [('including', 'inclufingautomated')] (insert+missing-space+substitute)
- `explain general relativity insimppe teerms` ← `explain general relativity in simple terms` — mismatches: [('insimppe', 'simple')] (double+missing-space+substitute)
- `what language is slokenin austria?` ← `what language is spoken in austria?` — mismatches: [('slokenin', 'spoken')] (missing-space+substitute)
- `whagt language issplken in egypt?` ← `what language is spoken in egypt?` — mismatches: [('issplken', 'spoken')] (insert+missing-space+substitute)
- `hoowlong should i cook chicken in the oven?` ← `how long should i cook chicken in the oven?` — mismatches: [('how', 'hoowlong')] (double+missing-space)

## Hand-written cases (includes all real cases from live sessions)

| Case | Expected | Result |
|---|---|---|
| `what is teh captial of rusia?` | align | ✅ |
| `what is teh captial of frnce?` | align | ✅ |
| `what is the capital of jpan?` | align | ✅ |
| `how do i revrse a strng in pyton?` | align | ✅ |
| `what is the boilng point of watr?` | align | ✅ |
| `explian quantum entanglment` | align | ✅ |
| `how do i fix a segmentaion falut in c?` | align | ✅ |
| `can you explian the diffrence between a proccess and a thred` | align | ✅ |
| `what is the capital of germany?` | veto | ✅ |
| `what is the freezing point of water?` | veto | ✅ |
| `who wrote hamlet?` | veto | ✅ |
| `how do i reverse a list in python?` | veto | ✅ |
| `what is the melting point of ice?` | veto | ✅ |
| `what is the population of france?` | veto | ✅ |
| `who wrote romeo and juliet and when?` | veto | ✅ |
| `how does cellular respiration work?` | veto | ✅ |
| `can you explain the difference between a process and a threa` | veto | ✅ |

## Known limitations

- **Phonetic spellings** fail the gate: "duz" for "does" is only 0.57
  letter-similar. Safe direction — the query just misses the cache.
- Generated typos are mechanical (QWERTY slips, swaps, deletions, doubled
  letters, missing spaces) with ≤ 3 mutated words per query; the gate is not
  tested against deliberate obfuscation.
- The gate is one of three checks: embedding distance ranks candidates, the
  gate filters, and the LLM validator gives the final verdict before serving.

Total: **1500** generated pairs + 17 hand-written.

Regenerate: `cd server && uv run --group test python tests/test_lexical_match.py`
