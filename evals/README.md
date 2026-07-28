# Offline eval harnesses

Each harness runs from its own directory with `uv`. Generated `reports/` are gitignored.

| Harness | Purpose | Best config |
|---|---|---|
| `enricher/` | Context enricher fidelity | `v3_improved_fewshots` |
| `normalizer/` | Normalizer cache-key quality | `v22` — 81% Hit@0.20 |
| `adjuster/` | Context adjuster tone (LLM judge) | `baseline_qwen_1_5b` |
| `validator/` | Cache-answer validator | — (image mode: `scripts/image_intent_check.py`) |
| `image_similarity/` | Image fingerprint gate | see `gate_eval.py` |

## enricher

```bash
cd evals/enricher
uv run python -m harness.runner --all-datasets                     # all configs, all 5 datasets
uv run python -m harness.runner --configs v2_regex_gate,v3_improved_fewshots --all-datasets
uv run python -m harness.runner --configs baseline_qwen_0_5b --dataset dataset/conversations.json
uv run python -m harness.runner --metrics-only --raw-from reports/20260413-111941/conversations
```

**Metric:** Fidelity — cosine distance between `embed(enriched)` and `embed(expected_standalone)`. Lower is better.
- `fidelity@0.15` = production cache similarity threshold
- `fidelity@0.20` = trusted entry threshold
- `passthrough rate` = % of `passthrough` rows where enriched ≈ original (dist < 0.05)

**Datasets** (`dataset/conversations*.json`): `conversations` (general, 60 scenarios), `conversations_coding` (54), `conversations_science` (51), `conversations_culture` (49), `conversations_practical` (49). Each scenario is 3 phrasings × 5 categories: `pronoun_resolution`, `topic_continuation`, `multi_reference`, `passthrough`, `deep_chain`.

**Configs:**

| Config | Description | Key result |
|--------|-------------|------------|
| `baseline_qwen_0_5b` | Production enricher, no gate | ~85% @0.20, 60% passthrough |
| `v2_regex_gate` | Regex gate skips LLM on standalone queries | ~92% @0.20, 100% passthrough, −30ms |
| `v3_improved_fewshots` | v2 gate + `\bones?\b` fix + 8 few-shots | +3pp coding, neutral elsewhere |

**Known ceiling:** Qwen 0.5B cannot inject subject nouns into bare "which" comparatives ("Which is cheaper?" from a gym-vs-home history) without domain-specific few-shots. Needs 1.5B or subject-extraction preprocessing.

## normalizer

```bash
cd evals/normalizer
uv run python -m harness.runner
```

## adjuster

```bash
cd evals/adjuster
uv run python -m harness.runner
uv run python -m harness.runner --configs baseline_qwen_1_5b
uv run python -m harness.runner --metrics-only
```

Uses an LLM judge — requires `ANTHROPIC_API_KEY`.

## validator

```bash
cd server
uv run python ../evals/validator/scripts/image_intent_check.py
```

`image_intent_check.py` measures the **image-anchored** validator mode (question vs question, answer never sent) on the real model. Each pair carries its BGE distance, so a false serve is only blocking when the pair is within cache reach (≤ `DEJAQ_CACHE_BAND_MAX_DISTANCE`); it exits non-zero in that case. Current: 9/9 paraphrases served, 15/16 siblings rejected, 0 reachable false serves, 577 ms median. Rationale: [docs/image-gate.md](../docs/image-gate.md).

## image_similarity

```bash
cd server
uv run python ../evals/image_similarity/gate_eval.py ../evals/image_similarity/dataset
```

`gate_eval.py` scores the shipped gate rule over **every** pair of a labeled set (generate data with `augment.py` first). Prefer it over the older band-sampling `phash_gate.py`, whose filtered pair selection hid a degenerate-hash failure. Evidence and threshold rationale: [docs/image-gate.md](../docs/image-gate.md).
