## Why

DejaQ's CLI phase is complete — org management, API keys, caching, stats — but there's no single command that proves it all works end-to-end. We need a repeatable demo that validates the full flow, seeds realistic data for development, and serves as the "it works" gate before building the web dashboard.

## What Changes

- New `scripts/demo.sh` shell script (single command: `./scripts/demo.sh`)
- Narrated, step-by-step terminal output walking through the complete DejaQ flow
- Script is idempotent: tears down its own org/data on exit (or leaves data for dev seeding, controlled by a flag)
- Covers: org creation → department creation → API key generation → cache miss request → cache hit request → stats TUI

## Capabilities

### New Capabilities
- `e2e-demo`: A self-contained shell script that exercises the full DejaQ platform end-to-end from a single terminal command, with narrated output showing each pipeline stage

### Modified Capabilities
<!-- none — no existing spec-level behavior changes -->

## Impact

- New file: `scripts/demo.sh`
- Depends on: `dejaq-admin` CLI (org, dept, key, stats subcommands), `/v1/chat/completions` endpoint, `dejaq-admin stats` TUI
- Requires the server, Redis, and Celery to be running (script checks and fails fast if not)
- No code changes to existing services
