# model-backends Specification

## Purpose
Define how DejaQ local completion services choose, invoke, and validate model backends across in-process and Ollama-backed deployments.

## Requirements

### Requirement: Local completion services SHALL use a shared model backend interface
The system SHALL provide a shared async model backend interface for local completion-style pipeline steps. The interface SHALL expose one completion operation that accepts a logical model name and prompt payload and returns generated text. `ContextEnricherService`, `NormalizerService`, `LLMRouterService` local generation, and `ContextAdjusterService` SHALL invoke local models through this interface instead of directly calling backend-specific model objects.

#### Scenario: Enricher uses backend interface
- **WHEN** `ContextEnricherService` needs to rewrite a follow-up question
- **THEN** it sends the configured model name and prompt payload to the shared backend interface
- **THEN** it receives generated text without directly calling `llama-cpp-python`

#### Scenario: Router local generation uses backend interface
- **WHEN** `LLMRouterService` generates a local answer for an easy query
- **THEN** it obtains the completion through the shared backend interface
- **THEN** response text and service-level behavior remain unchanged apart from the invocation path

### Requirement: Backend selection SHALL be configurable per service role
The system SHALL allow each local completion service role to select its backend via configuration. Supported backend types SHALL include `in_process` and `ollama`. Changing a service role from one supported backend to another SHALL not require code changes in the pipeline service itself.

#### Scenario: Development keeps in-process backend
- **WHEN** backend config for all service roles is set to `in_process`
- **THEN** local completion services use the in-process implementation
- **THEN** DejaQ preserves current development behavior

#### Scenario: One service switches to Ollama by config
- **WHEN** backend config for a service role is changed from `in_process` to `ollama`
- **THEN** that service role sends its completion requests to the Ollama implementation
- **THEN** no pipeline service code changes are required

### Requirement: In-process backend SHALL preserve current llama-cpp behavior
The system SHALL provide an `InProcessBackend` that preserves current local GGUF execution through `llama-cpp-python` and existing model-loading behavior. Backend-specific loading and reuse SHALL be encapsulated behind the backend implementation rather than the pipeline services. Blocking local completion work SHALL execute off the main async event loop so simultaneous requests do not serialize the entire FastAPI process behind one model call.

#### Scenario: Existing model loader remains internal
- **WHEN** `InProcessBackend` serves a request for a logical model name
- **THEN** it resolves and reuses the corresponding in-process model loader internally
- **THEN** pipeline services do not import or call `ModelManager` directly

#### Scenario: Concurrent in-process requests do not block the event loop
- **WHEN** multiple requests invoke local completion through `InProcessBackend` at the same time
- **THEN** the blocking model execution runs outside the main async event loop
- **THEN** unrelated requests and other awaiting coroutines can continue making progress while local inference is running

### Requirement: Ollama backend SHALL support equivalent completion requests
The system SHALL provide an `OllamaBackend` that sends async HTTP completion requests to a configured Ollama server and returns generated text in the same interface contract expected by pipeline services. The backend SHALL allow configuration of the Ollama base URL and request timeout. Simultaneous Ollama completions SHALL be issued as independent async HTTP requests rather than being serialized inside the DejaQ process.

#### Scenario: Ollama backend completes a prompt
- **WHEN** a service role configured for `ollama` requests a completion
- **THEN** the backend sends the request to the configured Ollama server using the mapped model identifier
- **THEN** it returns the generated text to the caller through the shared interface

#### Scenario: Concurrent Ollama requests stay async on the DejaQ side
- **WHEN** multiple requests invoke `OllamaBackend` concurrently
- **THEN** DejaQ issues those completions as async HTTP requests without blocking the main event loop
- **THEN** request concurrency is limited by Ollama/model capacity rather than by in-process serialization inside DejaQ

### Requirement: Backend refactor SHALL not change external DejaQ behavior
The system SHALL preserve existing pipeline outputs, request handling flow, and public API contracts when switching local completion services from direct `llama-cpp-python` calls to the backend interface. This refactor SHALL be internal-only from the client perspective.

#### Scenario: Chat API contract remains unchanged
- **WHEN** the backend abstraction is enabled with default in-process configuration
- **THEN** `/v1/chat/completions` request and response structure remains unchanged
- **THEN** callers do not need to change their integration

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
