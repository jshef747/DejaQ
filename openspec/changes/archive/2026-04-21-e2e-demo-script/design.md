## Context

DejaQ's server, CLI, caching, and stats layers are all functional. The `start.sh` script starts all services, and `dejaq-admin` handles org/dept/key management. There's no single script that chains these together into a narrated demo flow — the closest thing is manual steps in the README. This script fills that gap.

The script lives at `scripts/demo.sh` and runs from the repo root. It assumes services are already up (via `start.sh`) or optionally starts them itself.

## Goals / Non-Goals

**Goals:**
- Single command (`./scripts/demo.sh`) runs the full demo in under 60 seconds
- Narrated terminal output: each step announces what it's doing and why
- Demonstrates: org create → dept create (×2) → key generate → cache miss → cache hit → stats TUI
- Idempotent: cleans up its own demo org on exit (with `--keep` flag to skip cleanup for dev seeding)
- Fails fast with a clear message if the server is not reachable

**Non-Goals:**
- Does not start/stop services (that's `start.sh`'s job)
- Does not test every API surface — focused on the happy path demo flow
- Not a substitute for automated tests
- Does not require an external LLM key — uses the local Llama model (easy-difficulty routing)

## Decisions

**Decision 1: Shell script (bash) over Python script**
Shell matches the existing `start.sh` idiom in the repo. The operations are all CLI invocations and `curl` calls — no logic that benefits from Python's type system. Keeps the demo zero-dependency from the user's perspective.

*Alternative considered:* Python script using `subprocess` + `httpx`. Rejected: adds friction (requires venv activated), and the shell idiom is already established in this repo.

**Decision 2: `dejaq-admin` CLI for org/dept/key setup, `curl` for HTTP requests**
`dejaq-admin` outputs Rich-formatted text — perfect for a narrated demo. `curl` is universally available and its output (with `-s -w`) is easy to parse for cache hit/miss detection via the `X-DejaQ-Response-Id` header.

*Alternative considered:* Use `httpx` or Python requests. Rejected: same friction as above, and `curl` output is more readable in a terminal demo.

**Decision 3: Parse `X-DejaQ-Response-Id` to confirm cache hit**
The header is present on cache hits and stores. The script fires the first request, waits for background generalization (2s sleep), fires the second identical request, and checks for the header to confirm the hit. This proves the full pipeline — not just "no error".

*Alternative considered:* Parse response body for a cache flag. Rejected: the OpenAI-compat response body has no cache field; the header is the canonical signal.

**Decision 4: `--keep` flag to skip cleanup**
Default behavior deletes the demo org on exit (idempotent, safe to run repeatedly). `--keep` leaves data in place so developers can use the seeded org/depts for local development without re-running the demo.

**Decision 5: Hardcoded demo query that routes to local LLM (no external key required)**
Use a simple factual question ("What is 2 + 2?") that the difficulty classifier routes as "easy" → Llama 3.2 1B local. This means the demo works with zero external API configuration.

**Decision 6: Stats TUI shown as final step, not inline**
`dejaq-admin stats` is a full-screen Rich TUI — it takes over the terminal. It's the natural climax of the demo. Script pauses and tells the user to press `q` to exit, then the script completes.

## Risks / Trade-offs

- **Background generalization timing** → The script sleeps 2–3 seconds between first and second request to let Celery store the response. If the system is slow (cold model load), the second request may still miss. Mitigation: print a warning if the second request also misses, suggest re-running.
- **Slug collision on repeated runs without cleanup** → If the user ran with `--keep` previously, a second run will fail on `org create`. Mitigation: demo uses a timestamped slug (`dejaq-demo-<epoch>`) or checks for existing org and reuses it.
- **`dejaq-admin` CLI output is Rich-formatted** → Not easily machine-parseable. The script uses a second `key list` call with `--org` to extract the raw token via `grep`/`awk`. This is fragile if the table format changes. Mitigation: add a `--plain` or `--json` flag to `key generate` in a follow-up; for now, use `awk` on the known column position.
- **Stats TUI is interactive** → Takes over the terminal. The script can't automatically exit it. Mitigation: print clear instructions before launching ("press q to exit stats, then the demo will complete").

## Migration Plan

No migration needed — this is a new file only. Steps to ship:
1. Create `scripts/` directory in repo root
2. Add `scripts/demo.sh` with executable bit (`chmod +x`)
3. Document in `README.md` under a "Demo" section

No rollback needed — deleting the file reverts the change completely.
