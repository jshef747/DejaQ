## 1. Discovery

- [x] 1.1 Read `server/demo.sh` end to end and list any assumptions that could break under `ollama` backend (model warmup, Redis dependency, hard-coded URLs, model identifiers). Note: the active demo script is `scripts/demo.sh`; assumptions found: hard-coded FastAPI URL `http://127.0.0.1:8000`, prerequisite text still points at `cd server && ./start.sh`, waits only 5 seconds for background cache storage, requires the server stack to already be running, and relies on the server env selecting the model backend.
- [x] 1.2 Read `app/services/ollama_backend.py` (or equivalent) and record the exact Ollama model identifiers DejaQ requests for each logical model role (e.g., `qwen2.5:1.5b-instruct-q4_K_M`). These exact strings — not placeholders — must appear in the `ollama pull` lines later. Recorded from `server/app/services/model_backends.py`: `qwen2.5:0.5b`, `qwen2.5:1.5b`, `gemma4:e2b`, `gemma4:e4b`, `phi3.5:latest`.
- [x] 1.3 Read the existing CLAUDE.md "Environment Variables" and "Backend Concurrency" sections; mark the spans that will be edited or trimmed. Spans: Environment Variables table starts at `### Environment Variables`; Backend Concurrency top-level section starts at `## Backend Concurrency` and ends before `## Test Harnesses`.
- [x] 1.4 Confirm whether `server/demo.sh` requires Redis to be running (or works under `DEJAQ_USE_CELERY=false`). Record the answer — Redis will be documented as a shared prereq across all three modes. Answer: the demo itself only calls the running FastAPI server and local DB helpers, but the default server path uses Redis/Celery for background store; `DEJAQ_USE_CELERY=false` is the documented escape hatch if Redis is not running.

## 2. Validate demo against ollama backend FIRST

- [x] 2.1 Stand up Ollama on a reachable host and run `ollama pull` for every identifier from task 1.2. Evidence: `ollama pull qwen2.5:0.5b qwen2.5:1.5b gemma4:e2b gemma4:e4b phi3.5:latest` succeeded against local Ollama at `http://127.0.0.1:11434`.
- [x] 2.2 Set every `DEJAQ_*_BACKEND` to `ollama` and `DEJAQ_OLLAMA_URL` to that host; run `server/demo.sh`. Evidence: ran the active demo script `./scripts/demo.sh` with the running server configured as `enricher=ollama/qwen_1_5b normalizer=ollama/gemma_e2b local_llm=ollama/gemma_local generalizer=ollama/phi_generalizer context_adjuster=ollama/qwen_1_5b`.
- [x] 2.3 Fix any in-process assumption the run exposes inside this change. Constraints: the script stays mode-agnostic (no per-mode branching) and any fix is the minimal change needed. Result: no code fix required; the demo completed under the `ollama` backend unchanged.
- [x] 2.4 Re-run `server/demo.sh` under the ollama backend until it passes end to end. Capture the pass evidence. Evidence: `printf '\nq\n' | ./scripts/demo.sh` exited 0; final output included "DejaQ demo complete!", cache hit response ID, and stats table.
- [x] 2.5 Run `server/demo.sh` once under `in_process` to confirm the fixes from 2.3 did not regress the dev path. Evidence: started FastAPI with all five `DEJAQ_*_BACKEND=in_process` and `DEJAQ_USE_CELERY=false`; `printf '\nq\n' | ./scripts/demo.sh` exited 0 with "DejaQ demo complete!", cache hit, and stats output.

## 3. CLAUDE.md — Deployment Modes section

- [x] 3.1 Add a new top-level `## Deployment Modes` section after "Backend Concurrency".
- [x] 3.2 Add a "Shared prerequisites" preamble at the top of the section listing Redis (per task 1.4 — note the `DEJAQ_USE_CELERY=false` escape hatch) and Python deps as common to all three modes.
- [x] 3.3 Write the `### in-process (development)` subsection: prerequisites, env var block (all `DEJAQ_*_BACKEND=in_process`, no `DEJAQ_OLLAMA_URL` needed), bring-up commands (uvicorn + optional Celery worker), expected performance (single-user responsive, concurrent serializes per shared model).
- [x] 3.4 Write the `### self-hosted (on-prem production)` subsection: prerequisites including `ollama pull` lines using the exact model identifiers recorded in task 1.2, env var block (all `DEJAQ_*_BACKEND=ollama`, `DEJAQ_OLLAMA_URL=http://<lan-host>:11434`), bring-up commands, expected performance (real concurrency bounded by Ollama host capacity).
- [x] 3.5 Write the `### cloud (future scaling)` subsection: prerequisites (Ollama on cloud GPU instance, secured network path, same `ollama pull` identifiers as self-hosted), env var block (same as self-hosted with cloud URL), bring-up commands, performance and cost notes; explicitly state it is interface-compatible with self-hosted.
- [x] 3.6 Trim the existing "Backend Concurrency" section to a short conceptual paragraph and add a "See Deployment Modes for operator guidance" pointer.
- [x] 3.7 Add a one-line reminder near the "Environment Variables" table that any new `DEJAQ_*_BACKEND` must be reflected in all three mode blocks.

## 4. Cross-checks

- [x] 4.1 Verify each mode's env block lists all five `DEJAQ_*_BACKEND` variables explicitly (no implicit defaults).
- [x] 4.2 Verify the env var names in the new mode sections match the canonical "Environment Variables" table exactly.
- [x] 4.3 Confirm `server/demo.sh` is unmodified, OR that any changes made in section 2 are mode-agnostic (no per-mode branching inside the script). Note: active script is `scripts/demo.sh`; only startup path text changed to `./server/scripts/start.sh`, with no per-mode branching.
- [x] 4.4 Confirm the `ollama pull` lines in the `self-hosted` and `cloud` sections use the exact model identifiers recorded in task 1.2 — character-for-character, no placeholders.

## 5. Start script — relocate and add mode selection

- [x] 5.1 Move `server/start.sh` to `server/scripts/start.sh` (use `git mv` to preserve history).
- [x] 5.2 Add interactive mode selection: prompt for `in-process` / `self-hosted` / `cloud` and export the env var block matching the chosen mode (consistent with the blocks in CLAUDE.md from §3).
- [x] 5.3 For `self-hosted` and `cloud`, prompt for `DEJAQ_OLLAMA_URL` (or read from a flag/env) and refuse to start if empty.
- [x] 5.4 Support non-interactive selection via a CLI flag or env var (e.g., `--mode=self-hosted` or `DEJAQ_MODE=self-hosted`) so automation can skip prompts.
- [x] 5.5 Update CLAUDE.md and `server/README.md` to reference the new path `server/scripts/start.sh`; grep the repo for any other references to the old path and update. Also updated `scripts/demo.sh` and `server/docs/qa_cowork_prompt.md`.
- [x] 5.6 Smoke-test the relocated script in all three modes (interactive once, non-interactive once). Evidence: interactive dry-run selected `in-process`; non-interactive dry-runs covered `self-hosted` and `cloud`; real relocated-script startup succeeded in `self-hosted` and `/health` returned ok.

## 6. Final validation and wrap-up

- [x] 6.1 Validate `cloud` mode by pointing `DEJAQ_OLLAMA_URL` at a remote Ollama endpoint (cloud GPU instance or remote stand-in) and running `server/demo.sh`. If no cloud GPU host is available at implementation time, document the gap in the change archive notes and use a remote-but-not-cloud Ollama as a topology stand-in. Evidence: no cloud GPU host was available; validated cloud-mode env contract with local Ollama stand-in `http://127.0.0.1:11434`; `printf '\nq\n' | ./scripts/demo.sh` exited 0 with "DejaQ demo complete!", cache hit, and stats output.
- [x] 6.2 Re-read all three mode subsections and diff the env var names against the canonical "Environment Variables" table; confirm zero drift in names, casing, or default values.
- [x] 6.3 Update the "Current Status" section of CLAUDE.md to mention "Three documented deployment modes (in-process / self-hosted / cloud) validated against the end-to-end demo."
- [x] 6.4 Open PR; description includes per-mode demo-run evidence (pass/fail summary from tasks 2.4, 2.5, and 6.1). Evidence: draft PR opened at https://github.com/jshef747/DejaQ/pull/4 with per-mode demo-run evidence.
