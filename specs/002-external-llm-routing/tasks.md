# Tasks: External LLM API Integration

**Input**: Design documents from `/specs/002-external-llm-routing/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure

- [x] T001 Install `openai` library using `uv add openai` and `uv sync`
- [x] T002 Update `app/config.py` to include `OPENAI_API_KEY`, `EXTERNAL_MODEL_NAME`, and `EXTERNAL_API_BASE` environment variables

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

- [x] T003 [P] Create `ExternalLLMRequest` and `ExternalLLMResponse` Pydantic models in `app/schemas/chat.py`
- [x] T004 [P] Update `ChatResponse` in `app/schemas/chat.py` to include `model_used` and `latency_ms` in metadata
- [x] T005 [P] Implement custom exceptions (`ExternalLLMError`, `ExternalLLMAuthError`, `ExternalLLMTimeoutError`) in `app/utils/exceptions.py` (create file if needed)
- [x] T006 Initialize `ExternalLLMService` class as a singleton in `app/services/external_llm.py` with an `AsyncOpenAI` client placeholder

**Checkpoint**: Foundation ready - external routing implementation can now begin

---

## Phase 3: User Story 1 - Hard Prompts Receive High-Quality Responses (Priority: P1) 🎯 MVP

**Goal**: Automatically route complex queries to a capable external model and return the substantive response to the user.

**Independent Test**: Submit a multi-step complex query to the `/chat` endpoint and verify the response `model_used` metadata indicates the external provider (e.g., `gpt-4o`).

### Implementation for User Story 1

- [x] T007 [US1] Implement `AsyncOpenAI` client initialization with API key and base URL in `app/services/external_llm.py`
- [x] T008 [US1] Implement `generate_response` in `app/services/external_llm.py` to call OpenAI chat completions API
- [x] T009 [US1] Update `LLMRouterService` in `app/services/llm_router.py` to integrate `ExternalLLMService` for queries classified as "hard"
- [x] T010 [US1] Update `app/routers/chat.py` to handle the `async` call to `ExternalLLMService` while keeping local inference synchronous (or making the route fully async)
- [x] T011 [US1] Ensure responses from external LLM are passed to the background `generalize_and_store_task` in `app/tasks/cache_tasks.py` on cache miss
- [x] T012 [US1] Add latency logging for external API calls in `app/services/external_llm.py`

**Checkpoint**: User Story 1 is functional - complex queries are successfully routed to and from the external LLM.

---

## Phase 4: User Story 2 - Easy Prompts Continue Using Local Model (Priority: P2)

**Goal**: Maintain cost efficiency by ensuring simple queries are handled by the local model without triggering external API calls.

**Independent Test**: Submit a simple greeting or factual question and verify the `model_used` metadata indicates the local model (e.g., `llama-3.2-1b`) and no external API logs are generated.

### Implementation for User Story 2

- [x] T013 [US2] Verify and reinforce routing logic in `app/services/llm_router.py` to ensure "easy" queries bypass the `ExternalLLMService`
- [x] T014 [US2] Add an explicit safeguard check in `ExternalLLMService.generate_response` to log a warning and return early if called for a query not explicitly routed as "hard"

**Checkpoint**: User Story 2 is functional - the platform preserves cost efficiency by using local models for simple tasks.

---

## Phase 5: User Story 3 - Graceful Failure When External LLM Is Unavailable (Priority: P3)

**Goal**: Handle provider outages, rate limits, and configuration errors gracefully by informing the user without crashing the system.

**Independent Test**: Temporarily remove the `OPENAI_API_KEY` and submit a "hard" query; verify the user receives a clear error message instead of a 500 or timeout.

### Implementation for User Story 3

- [x] T015 [US3] Implement comprehensive `try-except` blocks in `ExternalLLMService.generate_response` to catch `openai.OpenAIError` and its subclasses
- [x] T016 [US3] Map caught external errors to the custom exceptions defined in T005
- [x] T017 [US3] Update `app/routers/chat.py` and WebSocket handlers to catch `ExternalLLMError` and return a user-friendly error message to the client
- [x] T018 [US3] Implement basic retry logic (2 retries) for transient network errors in `ExternalLLMService.generate_response`

**Checkpoint**: User Story 3 is functional - the system is resilient to external provider failures.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final refinements and UI updates to support the new routing capability.

- [x] T019 [P] Update `index.html` (WebSocket test UI) to display the `model_used` and `latency_ms` from the response metadata
- [x] T020 [P] Update `app/utils/logger.py` if needed to ensure `dejaq.services.external_llm` logs are correctly formatted and captured
- [x] T021 Perform a final end-to-end validation of the `quickstart.md` steps
- [x] T022 [P] Update `GEMINI.md` (or other project docs) with the new configuration requirements

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: Must be completed first to provide the necessary libraries and config.
- **Foundational (Phase 2)**: Depends on Phase 1; blocks all User Stories.
- **User Story 1 (Phase 3)**: Depends on Phase 2; provides the MVP.
- **User Story 2 (Phase 4)**: Depends on Phase 3 logic but can be verified in parallel with Phase 5.
- **User Story 3 (Phase 5)**: Depends on Phase 3 (needs implementation to add error handling to).
- **Polish (Phase 6)**: Final step after all stories are implemented.

### Parallel Opportunities

- T003, T004, and T005 can be implemented in parallel as they are independent schema/util updates.
- T019, T020, and T022 in the Polish phase can run in parallel.

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Setup and Foundational phases.
2. Implement `ExternalLLMService` and integrate it into `LLMRouterService`.
3. Verify that complex queries go to OpenAI and simple ones stay local.
4. **STOP and VALIDATE**: Test User Story 1 independently with a real API key.

### Incremental Delivery

1. Foundation ready (T001-T006).
2. Hard routing working (T007-T012) -> MVP Delivery.
3. Easy routing confirmed (T013-T014) -> Cost protection verified.
4. Resilience added (T015-T018) -> Reliability hardened.
5. UI and docs updated (T019-T022) -> Polish complete.
