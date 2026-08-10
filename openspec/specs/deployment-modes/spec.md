# deployment-modes Specification

## Purpose
Document the supported DejaQ deployment modes and the operational contract for starting and validating each mode.

## Requirements

### Requirement: DejaQ SHALL document three supported deployment modes
The project SHALL document exactly three supported deployment modes in `CLAUDE.md`: `in-process`, `self-hosted`, and `cloud`. Each documented mode SHALL include prerequisites, the exact values for every `DEJAQ_*_BACKEND` environment variable plus `DEJAQ_OLLAMA_URL`, the bring-up commands required to start the system in that mode, and expected performance characteristics covering both single-user and concurrent request behavior.

#### Scenario: Reader picks a mode for a laptop demo
- **WHEN** a developer reads the Deployment Modes section of CLAUDE.md
- **THEN** they find an `in-process` subsection that lists no external service prerequisites beyond Redis (optional) and Python deps
- **THEN** they find a complete env var block they can copy without further interpretation
- **THEN** they find the exact `uv run uvicorn` command to start the server

#### Scenario: Reader picks a mode for an on-prem org deployment
- **WHEN** a developer reads the Deployment Modes section of CLAUDE.md
- **THEN** they find a `self-hosted` subsection that names Ollama on a LAN host as a prerequisite
- **THEN** the env var block sets every `DEJAQ_*_BACKEND` value to `ollama` and points `DEJAQ_OLLAMA_URL` at a LAN address
- **THEN** the performance section explains that concurrent throughput is bounded by the Ollama host, not by the FastAPI process

#### Scenario: Reader plans a future cloud GPU deployment
- **WHEN** a developer reads the `cloud` subsection
- **THEN** they find guidance on running Ollama on a cloud GPU instance and pointing `DEJAQ_OLLAMA_URL` at it over a secured network path
- **THEN** the section notes that the configuration is interface-compatible with `self-hosted` and differs only in network topology and cost characteristics

### Requirement: The end-to-end demo script SHALL succeed unchanged in every documented mode
The `server/demo.sh` script SHALL run to completion against any of the three documented deployment modes without modifications to the script itself. Mode selection SHALL be controlled exclusively through environment variables, not by editing the demo script. Any per-mode setup (e.g., starting Ollama, pulling models) SHALL be documented in the relevant CLAUDE.md mode section, not embedded in the script.

#### Scenario: Demo runs against in-process mode
- **WHEN** `DEJAQ_*_BACKEND` env vars are set to `in_process` per the documented in-process mode
- **THEN** `server/demo.sh` executes its full narrated flow and exits successfully

#### Scenario: Demo runs against self-hosted mode
- **WHEN** Ollama is running on a reachable LAN host with required models pulled
- **THEN** `DEJAQ_*_BACKEND` env vars are set to `ollama` and `DEJAQ_OLLAMA_URL` points at that host
- **THEN** `server/demo.sh` executes its full narrated flow and exits successfully without script changes

#### Scenario: Demo runs against cloud mode
- **WHEN** Ollama is running on a cloud GPU instance reachable from the FastAPI host
- **THEN** the same env var contract used in `self-hosted` mode (with a different `DEJAQ_OLLAMA_URL`) drives the demo
- **THEN** `server/demo.sh` executes its full narrated flow and exits successfully without script changes

### Requirement: The start script SHALL offer interactive mode selection
The repository SHALL provide a start script that prompts the operator to choose one of the three documented deployment modes (`in-process`, `self-hosted`, `cloud`), exports the env var block matching the chosen mode, and brings the server up. The script SHALL live under `server/scripts/` alongside other helper scripts. Documentation references in CLAUDE.md and `server/README.md` SHALL point at the new path. Mode selection SHALL also be available non-interactively (e.g., via a CLI argument or env var) so the script can be invoked from automation without prompts.

#### Scenario: Operator runs the start script interactively
- **WHEN** an operator runs the start script with no arguments
- **THEN** the script prompts for one of `in-process`, `self-hosted`, or `cloud`
- **THEN** on selection it exports the env var block matching that mode and starts the server

#### Scenario: Self-hosted and cloud selections require an Ollama URL
- **WHEN** the operator selects `self-hosted` or `cloud`
- **THEN** the script prompts for (or reads from a flag/env) `DEJAQ_OLLAMA_URL`
- **THEN** the script does not start the server until a non-empty URL is provided

#### Scenario: Script lives under server/scripts
- **WHEN** a developer looks for the start script
- **THEN** they find it at `server/scripts/` (not at `server/start.sh`)
- **THEN** CLAUDE.md and `server/README.md` reference the new path

### Requirement: Each documented mode SHALL ship a copyable env example
The repository SHALL provide a copyable environment example for each of the three deployment modes. The examples MAY take the form of separate `.env.example.<mode>` files, a single annotated example file with mode-labeled sections, or fenced code blocks inside CLAUDE.md, but the exact env var set for each mode SHALL be reproducible by the reader with copy-paste only.

#### Scenario: Developer copies an env block and starts the server
- **WHEN** a developer copies the env block for one of the three modes from the documented source
- **THEN** the resulting environment is sufficient (combined with the documented prerequisites) to start the server in that mode
- **THEN** no additional undocumented env var is required for the demo script to succeed
