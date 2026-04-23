## 1. Backend Concurrency Verification

- [x] 1.1 Verify `InProcessBackend` runs blocking local completions off the main async event loop and adjust implementation if any local path still blocks directly
- [x] 1.2 Verify `OllamaBackend` issues concurrent completions as independent async HTTP requests without in-process serialization
- [x] 1.3 Add focused tests around backend concurrency behavior so regressions are caught without requiring a full manual load run

## 2. Concurrent Load Test

- [x] 2.1 Add a simple benchmark/load-test utility that fires configurable concurrent local-inference requests and measures total wall-clock time
- [x] 2.2 Make the benchmark output easy to compare between single-request and multi-request runs for the same backend mode
- [x] 2.3 Validate the benchmark against `in_process` and `ollama` modes and tune any coarse pass/fail expectation so it detects naive serialization without overfitting to one machine

## 3. Operator Documentation

- [x] 3.1 Update `CLAUDE.md` to describe concurrency characteristics and deployment trade-offs for `in_process` and `ollama`
- [x] 3.2 Document how to run the new load test and how operators should interpret the wall-clock results before choosing a backend mode

## 4. Final Verification

- [x] 4.1 Run the relevant automated tests for backend concurrency and benchmark coverage
- [x] 4.2 Run at least one manual concurrent benchmark pass and confirm 10 simultaneous requests do not behave like strict 10x serialization under the intended backend mode
