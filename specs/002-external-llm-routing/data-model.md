# Data Model: External LLM Routing

## Entities

### `ExternalLLMRequest`
Encapsulates all information needed for a request to an external LLM provider.
- **Fields:**
    - `query`: `str` (original user query)
    - `history`: `list[dict]` (multi-turn conversation messages)
    - `system_prompt`: `str` (guiding behavior prompt)
    - `model`: `str` (provider model name, e.g., `gpt-4o`)
    - `max_tokens`: `int` (limit for generation)
    - `temperature`: `float` (creativity parameter)

### `ExternalLLMResponse`
Standardizes the output from external providers.
- **Fields:**
    - `text`: `str` (the generated response)
    - `model_used`: `str` (actual model that responded)
    - `prompt_tokens`: `int` (input token count)
    - `completion_tokens`: `int` (output token count)
    - `latency_ms`: `float` (total request time)

### `RoutingDecision`
Captures the output of the classification step used for routing.
- **Fields:**
    - `query`: `str` (input query)
    - `complexity`: `str` ("easy" | "hard")
    - `confidence`: `float` (classifier's confidence score)
    - `routed_to`: `str` ("local" | "external")

## Relationships
- A `RoutingDecision` determines whether a `query` is converted into a `LocalLLMRequest` (internal) or an `ExternalLLMRequest`.
- Each `ExternalLLMRequest` produces exactly one `ExternalLLMResponse` (excluding errors).

## Validation Rules
- `query` MUST NOT be empty.
- `OPENAI_API_KEY` MUST be present for `ExternalLLMRequest` processing.
- `history` MUST contain valid role/content pairs (`system`, `user`, `assistant`).
