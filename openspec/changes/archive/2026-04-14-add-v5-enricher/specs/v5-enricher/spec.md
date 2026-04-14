## ADDED Requirements

### Requirement: Enricher uses Qwen 2.5-1.5B model
The context enricher SHALL load `ModelManager.load_qwen_1_5b()` instead of `ModelManager.load_qwen()` for all enrichment inference.

#### Scenario: Model loads on first enrichment call
- **WHEN** `ContextEnricherService` is instantiated
- **THEN** `ModelManager.load_qwen_1_5b()` is called and the 1.5B GGUF model is held in `self.llm`

### Requirement: Enricher applies regex precondition gate
The enricher SHALL skip LLM inference and return the original message unchanged when the message does not match the `_CONTEXT_DEPENDENT` regex pattern, regardless of conversation history.

#### Scenario: Standalone query bypasses LLM
- **WHEN** `enrich()` is called with a non-empty history and a message that contains no context-dependent signals (pronouns, continuations, or comparative triggers)
- **THEN** the original message is returned unmodified and no LLM call is made

#### Scenario: Context-dependent query triggers LLM
- **WHEN** `enrich()` is called with a non-empty history and a message matching `_CONTEXT_DEPENDENT` (e.g., contains "it", "they", "this", "which is", "tell me more")
- **THEN** the enricher calls the 1.5B LLM and returns the rewritten standalone question

#### Scenario: No history still short-circuits
- **WHEN** `enrich()` is called with an empty history list
- **THEN** the original message is returned immediately without regex evaluation or LLM call

### Requirement: Enricher logs gate decisions
The enricher SHALL emit a DEBUG-level log when the regex gate fires and enrichment is skipped, consistent with the existing no-history log pattern.

#### Scenario: Gate skip is logged
- **WHEN** the regex gate determines the message is standalone
- **THEN** a debug log is emitted indicating enrichment was skipped and the reason (regex gate)
