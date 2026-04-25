## Why

The backend abstraction (`DEJAQ_*_BACKEND` env vars) and concurrency benchmark work landed, but CLAUDE.md still describes only one undifferentiated way to run DejaQ. Operators picking up the project cannot tell which combination of env vars matches their situation (laptop demo vs. on-prem prod vs. cloud GPU), so they default to `in_process` everywhere and hit serialized throughput in production. Documenting the three intended deployment modes turns the abstraction into a usable product decision.

## What Changes

- Add a "Deployment Modes" top-level section to CLAUDE.md with three subsections: `in-process` (dev), `self-hosted` (prod, FastAPI on one host + Ollama over LAN), `cloud` (Ollama on cloud GPU instance).
- Each subsection documents: prerequisites, exact env var values for all five `DEJAQ_*_BACKEND` vars + `DEJAQ_OLLAMA_URL`, bring-up commands, and expected performance characteristics (single-user vs. concurrent throughput).
- Provide a per-mode `.env.example` snippet (or equivalent) developers can copy.
- Verify `server/demo.sh` runs unchanged in all three modes; document any per-mode preconditions inside the demo section, not the script itself.
- Move `server/start.sh` into `server/scripts/` alongside the existing helper scripts and update CLAUDE.md / `server/README.md` references to point at the new path.
- Extend the start script with interactive mode selection: prompt for `in-process` / `self-hosted` / `cloud`, export the corresponding env block, and bring the server up — matching the documented mode contracts.
- Update the existing "Backend Concurrency" section in CLAUDE.md to cross-reference the new mode sections instead of duplicating guidance.

## Capabilities

### New Capabilities
- `deployment-modes`: Documented and validated set of three supported deployment topologies (in-process / self-hosted / cloud) for DejaQ, including env var contract and demo-script compatibility requirement.

### Modified Capabilities
- `model-backends`: Existing backend selection capability gains a requirement that each documented deployment mode is a valid, tested configuration of the backend env vars and that `server/demo.sh` succeeds against each.

## Impact

- **Docs:** CLAUDE.md gets a new "Deployment Modes" section; "Backend Concurrency" section trimmed to point at it.
- **Code:** No application code changes expected. `server/demo.sh` may need small tweaks only if it hard-codes assumptions that break under `ollama` backend (e.g., model warmup, health checks).
- **Config:** Optional `.env.example` files (or a single annotated example) per mode under `server/` or repo root.
- **Validation:** Demo script must be executed once per mode as acceptance.
- **No breaking changes** to existing env var names or defaults; `in_process` remains the default for backward compatibility.
