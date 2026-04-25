## Context

DejaQ already supports per-service-role backend selection through `DEJAQ_ENRICHER_BACKEND`, `DEJAQ_NORMALIZER_BACKEND`, `DEJAQ_LOCAL_LLM_BACKEND`, `DEJAQ_GENERALIZER_BACKEND`, and `DEJAQ_CONTEXT_ADJUSTER_BACKEND`, with `in_process` and `ollama` as the supported values. A concurrency benchmark script (`server/scripts/benchmark_backend_concurrency.py`) exists. The end-to-end demo script `server/demo.sh` is the canonical "does the whole pipeline work" check.

What's missing is a product-shaped story on top of these knobs. CLAUDE.md currently describes one bring-up sequence and a generic "Backend Concurrency" tradeoff paragraph. Operators read it and default to `in_process` because that's what the example commands show, and then are surprised when concurrent traffic serializes. The fix is documentation + light validation, not new code.

## Goals / Non-Goals

**Goals:**
- Three named modes (`in-process`, `self-hosted`, `cloud`) with copy-pasteable env blocks and bring-up commands in CLAUDE.md.
- `server/demo.sh` works unchanged in all three modes — proven by running it once per mode.
- Cross-link the existing "Backend Concurrency" section to the new mode sections so guidance lives in one place.

**Non-Goals:**
- No code changes to the backend abstraction or to `demo.sh` beyond fixing genuine assumptions that block the `ollama` backend.
- No new backend types beyond `in_process` and `ollama`. "Cloud mode" is `ollama` pointed at a remote URL, not a new backend.
- No deployment automation (Terraform, Ansible, k8s manifests). Documentation only.
- No managed-service mode (e.g., calling Anthropic / OpenAI / Together for the local roles). Out of scope for this change.

## Decisions

### Decision 1: "cloud" mode is `ollama` backend with a remote URL — not a new backend type
Treat `cloud` as a topology variant of `self-hosted` rather than a third backend implementation. The only DejaQ-side difference is the value of `DEJAQ_OLLAMA_URL`. Documentation makes the operational differences (network security, cost, cold-start) explicit, but the env var contract is the same.

**Alternative considered:** A dedicated `cloud` backend wrapping a managed inference provider. Rejected — that's a different change. Today's abstraction already covers "Ollama somewhere on the network."

### Decision 2: Env examples live as fenced blocks in CLAUDE.md, not as separate `.env.example.<mode>` files
Single source of truth, no risk of doc/file drift, easy to copy. If volume grows we can split later.

**Alternative considered:** Three `.env.example.*` files under `server/`. Rejected for now — adds files that need to be kept in sync with prose; the prose has to exist anyway.

### Decision 3: Demo-script validation is manual, recorded in tasks.md
Running `server/demo.sh` once per mode is the acceptance gate. No CI matrix added in this change — `self-hosted` and `cloud` need real Ollama hosts CI doesn't have, and `in_process` is already covered implicitly by existing dev usage.

**Alternative considered:** Add a CI job per mode. Rejected — infra work disproportionate to a docs change, and the modes that matter most (`self-hosted`, `cloud`) require external hosts CI doesn't own.

### Decision 4: "Backend Concurrency" section is trimmed, not deleted
Keep it as a short conceptual block (what `in_process` vs `ollama` means at the abstraction level) and link out to the mode sections for operator-facing guidance. Avoids forcing readers to read deployment docs to learn the concept.

## Risks / Trade-offs

- **Demo script may have hidden in-process assumptions** → run it under `ollama` first; fix any breakage as a small follow-up inside this change rather than punting it.
- **Documented Ollama model names may drift from what's actually pulled on the user's host** → call out the `ollama pull` step explicitly in `self-hosted` and `cloud` prereqs with the exact model identifiers DejaQ requests.
- **Cloud-mode network exposure** → CLAUDE.md cannot meaningfully prescribe a security posture. Note the requirement (private networking / auth proxy / VPN) without dictating an implementation.
- **Doc rot** → tie the env var table in the "Environment Variables" section and the per-mode env blocks together by referencing the same variable names; if a new `DEJAQ_*_BACKEND` variable is added later, it must appear in all three mode blocks. Add a one-line reminder near the env var table.

## Migration Plan

Documentation-only. No rollback needed beyond `git revert` on the CLAUDE.md edit. Default env var behavior (`in_process`) is unchanged, so existing deployments keep working without any action.

## Open Questions

- Should the `self-hosted` example pin specific Ollama model tags (e.g., `qwen2.5:1.5b-instruct-q4_K_M`) or leave them as variables? Current lean: pin them, since drift here silently degrades quality. Confirm during implementation by checking what `OllamaBackend` actually requests.
- Does `server/demo.sh` currently assume Redis is up? If so, document that Redis is a shared prereq across all three modes (or note the `DEJAQ_USE_CELERY=false` escape hatch per mode). Resolve while running the demo validation.
