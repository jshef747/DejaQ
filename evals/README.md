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
cd evals/validator
# Text mode. Runs the SHIPPED ValidatorService against live Ollama, so the
# prompt and inference options are production's, not a copy. Needs the server
# venv (it imports the app package) and `ollama serve` running.
../../server/.venv/bin/python -m harness.runner \
    --configs granite4_1_3b,gemma_e2b,gemma_e4b --all-datasets

cd server
uv run python ../evals/validator/scripts/image_intent_check.py
```

**Datasets** (`dataset/pairs*.json`): the original 300-pair set (`pairs`,
`pairs_culture`, `pairs_history`, `pairs_science`, `pairs_tech`) plus
`pairs_follow_up_fragment` (112 pairs, 56 VALID / 56 INVALID). The follow-up
set covers **referential fragments** - "what's the difference?", "how so?",
"and the other one?" - which is what the validator actually receives, since
the pipeline passes the raw `user_query` and not the enriched question.

**Run both.** They rank models differently, and the 300-pair set on its own is
what let an unmeasured model ship (2026-08-21):

| config | 300-pair | follow_up_fragment | validate median |
|---|---|---|---|
| `granite4_1_3b` | 266/300 88.7% | 82/112 73.2% (FR 30/56, FA 0/56) | 179 ms |
| `gemma_e2b` (shipped) | 281/300 93.7% | 96/112 85.7% (FR 14/56, FA 2/56) | 400 ms |
| `gemma_e4b` | 300/300 100% | 82/112 73.2% (FR 28/56, FA 2/56) | 459 ms |

Measured 2026-08-26 on this harness; `gemma_e4b`'s perfect 300-pair score does
not transfer. `server/tests/test_validator_eval_coverage.py` fails if
`VALIDATOR_MODEL_NAME` names a model with no config here.

**Configs on the GGUF/llama-cpp path** (`qwen_1_5b`, `qwen_0_5b`,
`phi_3_5_mini`, `qwen_1_5b_prefilter`) are disabled: each carries its own copy
of a system prompt that drifted from the shipped one. New candidates use
`"ollama_model"` and inherit production's prompt automatically.

`image_intent_check.py` measures the **image-anchored** validator mode (question vs question, answer never sent) on the real model. Each pair carries its BGE distance, so a false serve is only blocking when the pair is within cache reach (≤ `DEJAQ_CACHE_BAND_MAX_DISTANCE`); it exits non-zero in that case. Current: 9/9 paraphrases served, 15/16 siblings rejected, 0 reachable false serves, 577 ms median. Rationale: [docs/image-gate.md](../docs/image-gate.md).

## image_similarity

```bash
cd server
uv run python ../evals/image_similarity/gate_eval.py ../evals/image_similarity/dataset
```

`gate_eval.py` scores the shipped gate rule over **every** pair of a labeled set (generate data with `augment.py` first). Prefer it over the older band-sampling `phash_gate.py`, whose filtered pair selection hid a degenerate-hash failure. Evidence and threshold rationale: [docs/image-gate.md](../docs/image-gate.md).
