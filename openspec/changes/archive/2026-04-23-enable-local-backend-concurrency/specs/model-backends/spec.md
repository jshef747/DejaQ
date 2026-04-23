## MODIFIED Requirements

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
