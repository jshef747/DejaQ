## Context

The production enricher (`server/app/services/context_enricher.py`) currently:
- Loads Qwen 2.5-0.5B via `ModelManager.load_qwen()`
- Runs LLM inference on every request that has conversation history (no precondition gate)
- Uses 4 few-shot examples hardcoded inline

The enricher-test harness (run `20260413-182650`) compared v4_gate_fix (0.5B + regex gate) vs v5_qwen_1_5b (1.5B + same regex gate) across 5 datasets. v5 wins +5.4pp @0.15 / +3.3pp @0.20 with passthrough rate unchanged at 100%.

`ModelManager.load_qwen_1_5b()` already exists in `model_loader.py` — used by the context adjuster. No new model infrastructure needed.

## Goals / Non-Goals

**Goals:**
- Upgrade enricher model from 0.5B to 1.5B (one line change in `__init__`)
- Add regex precondition gate — skip LLM entirely for standalone queries (saves ~65–160ms per standalone call)
- Keep few-shots and system prompt identical to current production (v5 harness uses same 4 shots)
- No API or schema changes

**Non-Goals:**
- Fixing bare comparative failures ("Which came first?") — those require subject-extraction preprocessing, out of scope
- Adding new few-shots or prompt engineering beyond what v5 harness tested
- Changing the normalizer, cache filter, or any other pipeline step

## Decisions

**Decision: swap model in `__init__`, not via config**
The harness uses a CONFIG dict with a `loader` block; the production enricher directly calls `ModelManager.load_qwen()`. Introducing a config layer would be premature abstraction — one swapped method call is simpler and correct.

Alternative considered: extract a config dict into context_enricher.py mirroring the harness. Rejected — adds indirection with no benefit since configs aren't hot-swappable in production.

**Decision: inline the regex as a module-level constant**
Matches the harness pattern and avoids recompiling on every call. The regex is stable — it encodes a validated linguistic heuristic, not a tunable parameter.

**Decision: gate placement — before LLM, after history check**
Current flow: `if not history → return message`. New flow: `if not history OR not _CONTEXT_DEPENDENT.search(message) → return message`. This keeps the fast-path first and avoids the model being loaded until needed.

## Risks / Trade-offs

**Memory increase (~1GB)** → Acceptable. 1.5B Q4_K_M is ~0.9GB; 0.5B is ~0.4GB. The 1.5B model is already loaded by the context adjuster in the same process, so `ModelManager` singleton means no extra RAM in typical deployment — they share the loaded instance. Verify `load_qwen_1_5b()` in `model_loader.py` serves the right model.

**Latency increase on context-dependent queries (~65–115ms)** → Offset by regex gate eliminating LLM cost entirely on standalone queries (passthrough rate 100% in all datasets). Net latency across all traffic depends on the standalone query ratio.

**Regex false negatives (gate misses context-dependent queries)** → Gate has known misses on bare comparatives ("Which costs more?"). These now fall through to the LLM, which also fails them. No regression vs current behavior — current code also fails these without a gate.

**`load_qwen_1_5b()` shared with context adjuster** → If the adjuster and enricher race to load the model at startup, `ModelManager` singleton handles it (lazy load on first call, thread-safe if GIL-protected). Confirm no re-entrant load issue.

## Migration Plan

1. Deploy updated `context_enricher.py` (model swap + gate)
2. Smoke test via `POST /chat` with a multi-turn conversation — verify enrichment fires and logs show 1.5B latency
3. Monitor logs: `dejaq.services.context_enricher` — confirm gate is firing ("skipping enrichment") on standalone queries
4. Rollback: revert `load_qwen_1_5b()` → `load_qwen()` and remove gate block

## Open Questions

- Does `load_qwen_1_5b()` in production point to the correct GGUF file (`Qwen2.5-1.5B-Instruct-GGUF` Q4_K_M)? Confirm path matches harness `repo_id`.
- Is the 1.5B model already downloaded on the server, or does it need a `uv run` pull step on first startup?
