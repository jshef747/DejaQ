## ADDED Requirements

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
The system SHALL provide an `InProcessBackend` that preserves current local GGUF execution through `llama-cpp-python` and existing model-loading behavior. Backend-specific loading and reuse SHALL be encapsulated behind the backend implementation rather than the pipeline services.

#### Scenario: Existing model loader remains internal
- **WHEN** `InProcessBackend` serves a request for a logical model name
- **THEN** it resolves and reuses the corresponding in-process model loader internally
- **THEN** pipeline services do not import or call `ModelManager` directly

### Requirement: Ollama backend SHALL support equivalent completion requests
The system SHALL provide an `OllamaBackend` that sends async HTTP completion requests to a configured Ollama server and returns generated text in the same interface contract expected by pipeline services. The backend SHALL allow configuration of the Ollama base URL and request timeout.

#### Scenario: Ollama backend completes a prompt
- **WHEN** a service role configured for `ollama` requests a completion
- **THEN** the backend sends the request to the configured Ollama server using the mapped model identifier
- **THEN** it returns the generated text to the caller through the shared interface

### Requirement: Backend refactor SHALL not change external DejaQ behavior
The system SHALL preserve existing pipeline outputs, request handling flow, and public API contracts when switching local completion services from direct `llama-cpp-python` calls to the backend interface. This refactor SHALL be internal-only from the client perspective.

#### Scenario: Chat API contract remains unchanged
- **WHEN** the backend abstraction is enabled with default in-process configuration
- **THEN** `/v1/chat/completions` request and response structure remains unchanged
- **THEN** callers do not need to change their integration
