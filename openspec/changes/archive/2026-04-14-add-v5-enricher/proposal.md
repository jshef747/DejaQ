## Why

The v5 enricher (Qwen 2.5-1.5B-Instruct) outperforms the current production enricher (v4_gate_fix/Qwen 0.5B) by +5.4pp @0.15 and +3.3pp @0.20 fidelity across all five test datasets, with the largest gain on practical queries (+10.2pp). v4 is already deployed; v5 was validated in the enricher-test harness and is ready to ship.

## What Changes

- Replace `ModelManager.load_qwen()` (0.5B) as the enricher model with `ModelManager.load_qwen_1_5b()` (1.5B) inside `context_enricher.py`
- Update the enricher config/prompt to match the `v5_qwen_1_5b` harness config (improved few-shots + regex gate)
- Keep the regex gate (passthrough optimization from v2) — it remains effective and cuts latency on standalone queries
- Update `CLAUDE.md` model table to reflect the new enricher model
- No API contract changes — enricher is an internal service step

## Capabilities

### New Capabilities

- `v5-enricher`: Context enricher powered by Qwen 2.5-1.5B with improved few-shot prompts and regex passthrough gate

### Modified Capabilities

<!-- No spec-level behavior changes — enricher input/output contract is unchanged -->

## Impact

- `app/services/context_enricher.py` — swap model loader call and update prompt/few-shots
- `app/services/model_loader.py` — `load_qwen_1_5b()` already exists; verify it's used correctly
- Memory footprint increases (1.5B vs 0.5B GGUF Q4_K_M: ~0.9 GB → ~1.0 GB delta, manageable)
- Mean latency increases ~65–115ms on context-dependent queries; passthrough queries unchanged (regex gate fires)
- `CLAUDE.md` model table row for Normalizer/Enricher roles
