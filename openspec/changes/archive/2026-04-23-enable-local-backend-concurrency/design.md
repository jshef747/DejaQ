## Context

The backend abstraction change decoupled pipeline services from concrete inference runtimes, but the in-process backend still needs to behave correctly under concurrent FastAPI traffic. `llama-cpp-python` calls are blocking, so if they run directly on the event loop, one local generation can stall unrelated requests. That is acceptable for demos but not for real org traffic where multiple employees may issue requests at once.

This change is intentionally narrow. It does not alter prompt logic, routing policy, or backend selection semantics. It makes concurrency characteristics explicit for each backend mode, validates that the current implementation meets those expectations, and gives operators a simple way to measure real wall-clock behavior.

## Goals / Non-Goals

**Goals:**
- Ensure in-process local inference does not block the main async event loop
- Verify Ollama backend requests remain naturally concurrent under load
- Add a simple concurrent load test that compares one-request vs multi-request wall-clock behavior
- Document backend concurrency characteristics in `CLAUDE.md` so operators understand development vs production trade-offs

**Non-Goals:**
- Changing model prompts, cache behavior, or external API contracts
- Adding distributed scheduling, batching, or a new inference queue architecture
- Guaranteeing perfect linear scaling for all hardware and models
- Refactoring the classifier into the backend abstraction

## Decisions

### D1 — Treat event-loop non-blocking as the in-process concurrency contract

**Decision:** The in-process backend contract is not “true parallel model execution” but “model work SHALL be off the main event loop so other requests can progress.” Blocking `llama-cpp-python` work remains inside worker threads via `asyncio.to_thread`.

**Rationale:** This matches the user problem precisely: avoid serializing the whole FastAPI server behind one local model call. It also fits current architecture without introducing new worker pools or changing backend interfaces.

**Alternative:** Require full multi-model parallel throughput from one process. Rejected: stronger claim than current architecture can guarantee across CPU/GPU constraints.

### D2 — Measure concurrency with wall-clock load tests, not per-request microbenchmarks alone

**Decision:** Add a simple benchmark that fires concurrent requests and compares total elapsed time for `N` simultaneous requests against a single request baseline.

**Rationale:** Operators care about “does 10 concurrent traffic feel serialized or not,” not isolated function latency. Wall-clock measurement captures the real operational outcome.

**Alternative:** Unit-test only that `asyncio.to_thread` is called. Rejected: implementation detail coverage is useful, but alone it does not prove real request concurrency.

### D3 — Keep backend verification backend-agnostic but allow backend-specific expectations

**Decision:** One benchmark path should be reusable across backend modes, but the documented interpretation differs:
- `in_process`: concurrent requests should avoid naive 10x serialization
- `ollama`: concurrent requests should behave as async HTTP calls, with scaling limited mainly by Ollama/model capacity

**Rationale:** Same test harness, different operator expectations. This keeps maintenance low while still documenting practical differences.

### D4 — Document concurrency characteristics in `CLAUDE.md`

**Decision:** Add a dedicated explanation in repo docs covering:
- in-process backend: convenient for dev, limited by local model/runtime/hardware, but should not block event loop
- ollama backend: decoupled HTTP inference, better suited for concurrent serving
- benchmark interpretation guidance before choosing deployment mode

**Rationale:** Operators need explicit guidance before flipping backend config. Hidden behavior is operational risk.

## Risks / Trade-offs

- **`asyncio.to_thread` improves responsiveness but not infinite throughput** → Document this clearly; benchmark for “not 10x worse,” not perfect scaling
- **Hardware variance can make timing noisy** → Use a coarse assertion/threshold and report wall-clock numbers, not strict deterministic timings
- **Benchmark may be expensive with real models** → Keep it simple and optionally parameterized so it can run as a smoke/load utility instead of every fast unit test
- **Ollama concurrency depends on external server config/model capacity** → Document that the backend is async on DejaQ side, but end-to-end throughput still depends on Ollama deployment

## Migration Plan

1. Confirm in-process backend uses off-loop execution for blocking model calls.
2. Add benchmark/load test covering concurrent local inference requests.
3. Validate both in-process and Ollama modes with measured wall-clock behavior.
4. Update `CLAUDE.md` with backend concurrency expectations and operator guidance.

**Rollback:** Revert benchmark/doc changes and restore previous backend behavior if needed. No public API migration required.

## Open Questions

None.
