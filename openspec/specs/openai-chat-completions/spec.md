### Requirement: Accept OpenAI chat completions request
The system SHALL expose a `POST /v1/chat/completions` endpoint that accepts a request body conforming to the OpenAI Chat Completions API schema. The endpoint SHALL accept at minimum: `model` (string), `messages` (array of `{role, content}` objects), and `stream` (boolean, default false). Unknown fields in the request SHALL be ignored without error.

#### Scenario: Valid non-streaming request accepted
- **WHEN** a client sends `POST /v1/chat/completions` with a valid `messages` array and `stream: false`
- **THEN** the system returns HTTP 200 with a JSON body containing `id`, `object: "chat.completion"`, `created`, `model`, `choices`, and `usage` fields

#### Scenario: Valid streaming request accepted
- **WHEN** a client sends `POST /v1/chat/completions` with `stream: true`
- **THEN** the system returns HTTP 200 with `Content-Type: text/event-stream` and a stream of `data: <json>\n\n` SSE chunks, terminated by `data: [DONE]\n\n`

#### Scenario: Missing messages field rejected
- **WHEN** a client sends `POST /v1/chat/completions` without a `messages` field
- **THEN** the system returns HTTP 422 with a validation error

### Requirement: Route request through full DejaQ pipeline
The system SHALL route every `/v1/chat/completions` request through the full existing pipeline: context enricher → normalizer → cache check → LLM router → context adjuster → background generalize+store (on cache miss). The original query and conversation history SHALL be preserved and passed to the LLM on cache miss.

#### Scenario: Cache hit returns cached response
- **WHEN** a semantically equivalent query has been cached (cosine distance ≤ 0.15)
- **THEN** the response is served from cache and the `choices[0].finish_reason` is `"stop"`

#### Scenario: Cache miss triggers LLM and background storage
- **WHEN** no cached entry matches within the cosine threshold
- **THEN** the LLM router generates a response and a background task generalizes and stores it

### Requirement: Map OpenAI message roles to DejaQ conversation format
The system SHALL extract the last `user`-role message as the current query. All preceding messages SHALL be passed as conversation history to the LLM on cache miss. Messages with `role: "system"` SHALL be prepended to the LLM system prompt.

#### Scenario: Last user message used as query
- **WHEN** the `messages` array contains multiple user messages
- **THEN** only the final `role: "user"` message is treated as the current query for cache lookup and enrichment

#### Scenario: System message forwarded to LLM
- **WHEN** the `messages` array contains a `role: "system"` message
- **THEN** its content is included in the system prompt sent to the LLM on cache miss

### Requirement: Return OpenAI-shaped response
The system SHALL return a response object that conforms to the OpenAI `ChatCompletion` schema for non-streaming and `ChatCompletionChunk` schema for streaming. The `model` field in the response SHALL echo the `model` value from the request. The response SHALL include a `usage` object with `prompt_tokens`, `completion_tokens`, and `total_tokens`.

#### Scenario: Non-streaming response has correct shape
- **WHEN** a non-streaming request completes
- **THEN** the response body contains `choices[0].message.role = "assistant"` and `choices[0].message.content` with the answer

#### Scenario: Streaming response chunks have correct shape
- **WHEN** a streaming request is in progress
- **THEN** each SSE chunk contains `choices[0].delta.content` with a token fragment, and the final chunk has `choices[0].finish_reason = "stop"`

#### Scenario: Model field echoed in response
- **WHEN** a client sends `"model": "gpt-4o"` in the request
- **THEN** the response contains `"model": "gpt-4o"` regardless of which internal model DejaQ used

### Requirement: Expose actual model used via response header
The system SHALL include an `x-dejaq-model-used` response header identifying the internal model that generated the response (or `"cache"` for cache hits).

#### Scenario: Cache hit sets header to cache
- **WHEN** the response is served from cache
- **THEN** the `x-dejaq-model-used` header value is `"cache"`

#### Scenario: LLM response sets header to model name
- **WHEN** the LLM router generates a response
- **THEN** the `x-dejaq-model-used` header contains the name of the model used (e.g., `"llama-3.2-1b"`)
