## ADDED Requirements

### Requirement: Backend env var combinations SHALL map onto documented deployment modes
The set of `DEJAQ_*_BACKEND` environment variables SHALL admit at least three named, documented configurations corresponding to the `in-process`, `self-hosted`, and `cloud` deployment modes. Each named configuration SHALL be a valid, tested combination of backend env vars and `DEJAQ_OLLAMA_URL` such that the system starts and serves `/v1/chat/completions` requests successfully under it.

#### Scenario: in-process mode configuration is valid
- **WHEN** every `DEJAQ_*_BACKEND` variable is set to `in_process`
- **THEN** the system starts without requiring an external Ollama server
- **THEN** local completion services route through `InProcessBackend`

#### Scenario: self-hosted mode configuration is valid
- **WHEN** every `DEJAQ_*_BACKEND` variable is set to `ollama` and `DEJAQ_OLLAMA_URL` points at a reachable Ollama server with the required models pulled
- **THEN** the system starts and routes all local completion services through `OllamaBackend`
- **THEN** `/v1/chat/completions` returns successful responses

#### Scenario: cloud mode is interface-compatible with self-hosted
- **WHEN** the same `ollama` backend env var combination is used with `DEJAQ_OLLAMA_URL` pointing at a cloud-hosted Ollama endpoint
- **THEN** no additional DejaQ-side configuration beyond the URL is required to switch between self-hosted and cloud
- **THEN** the system behaves equivalently from the client perspective

### Requirement: Documented deployment modes SHALL be validated against the demo script
Each of the three documented deployment modes SHALL be validated by running `server/demo.sh` to completion against it. The acceptance evidence for adding or modifying a documented mode SHALL include a successful end-to-end demo run in that mode.

#### Scenario: Adding or changing a documented mode requires demo validation
- **WHEN** a deployment mode is added to or modified in CLAUDE.md
- **THEN** `server/demo.sh` is executed against that mode's env var configuration
- **THEN** the run completes successfully before the documentation change is considered done
