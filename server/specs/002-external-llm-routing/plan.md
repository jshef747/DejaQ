# Implementation Plan: External LLM API Integration

**Branch**: `002-external-llm-routing` | **Date**: 2026-03-28 | **Spec**: [specs/002-external-llm-routing/spec.md](spec.md)
**Input**: Feature specification from `/specs/002-external-llm-routing/spec.md`

## Summary

Implement integration with an external LLM provider (OpenAI) to handle queries classified as "hard". This feature extends the existing hybrid routing pipeline, ensuring high-quality responses for complex queries while maintaining cost efficiency by using local models for simple tasks. The integration will support environment-based configuration, multi-turn history, and graceful error handling.

## Technical Context

**Language/Version**: Python 3.13+
**Primary Dependencies**: FastAPI, Celery, Redis, ChromaDB, llama-cpp-python, `openai`
**Storage**: ChromaDB (semantic cache), Redis (task queue/metadata)
**Testing**: `pytest` with model markers
**Target Platform**: Mac (Metal), Windows (CUDA), Linux (CUDA/CPU)
**Project Type**: AI Middleware / Web Service
**Performance Goals**: < 30s for external LLM responses; < 200ms for cache hits
**Constraints**: No `print()`, `uv` only, singleton service pattern, separation of tone and semantics
**Scale/Scope**: Hybrid routing for "easy" vs "hard" query classification

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- [x] **Cost Optimization**: FR-002 ensures external calls only for "hard" prompts.
- [x] **Non-Blocking UX**: Async handlers used for I/O; background storage via Celery.
- [x] **Local-First**: FR-002 preserves local model usage for "easy" prompts.
- [x] **Singleton Management**: `ExternalLLMService` will follow the singleton pattern.
- [x] **Separation of Tone**: FR-008 ensures external responses are generalized before storage.
- [x] **Logging**: All routing decisions and errors will use the `dejaq` logger.
- [x] **Package Management**: `uv` will be used for all dependency management.

## Project Structure

### Documentation (this feature)

```text
specs/002-external-llm-routing/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
└── tasks.md             # Phase 2 output
```

### Source Code (repository root)

```text
app/
├── routers/
│   └── chat.py          # Modified: Update routing logic to call ExternalLLMService
├── services/
│   ├── external_llm.py  # NEW: Service for external API communication
│   ├── llm_router.py    # Modified: Integrate external routing branch
│   └── ...
├── schemas/
│   └── chat.py          # Modified: Add metadata for external model info
├── tasks/
│   └── cache_tasks.py   # Verified: Background generalization for external responses
└── config.py            # Modified: Add OPENAI_API_KEY and EXTERNAL_MODEL settings
```

**Structure Decision**: Single project (Option 1) as it fits the existing FastAPI monolithic structure. Adding a new service in `app/services/` and updating routers/config as needed.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| N/A | | |
