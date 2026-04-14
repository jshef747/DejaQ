## 1. Pre-flight verification

- [x] 1.1 Confirm `ModelManager.load_qwen_1_5b()` in `server/app/services/model_loader.py` loads `Qwen2.5-1.5B-Instruct-GGUF` Q4_K_M (check repo_id and filename pattern)
- [x] 1.2 Confirm the 1.5B GGUF file is present on the server (or document the download step)

## 2. Update context enricher

- [x] 2.1 Add `_CONTEXT_DEPENDENT` regex constant at module level in `server/app/services/context_enricher.py` (copy from `enricher-test/configs/v5_qwen_1_5b.py`)
- [x] 2.2 Swap `ModelManager.load_qwen()` → `ModelManager.load_qwen_1_5b()` in `ContextEnricherService.__init__`
- [x] 2.3 Add regex gate in `enrich()`: after the history check, return message unchanged if `not _CONTEXT_DEPENDENT.search(message)`, with a DEBUG log "Regex gate — skipping enrichment for: %s"

## 3. Smoke test

- [x] 3.1 Start server and send a multi-turn chat via `POST /chat` or WebSocket — confirm enrichment log shows 1.5B latency (~200–400ms on context-dependent queries)
- [x] 3.2 Send a standalone query in a multi-turn conversation — confirm DEBUG log "Regex gate — skipping enrichment" fires and response is fast (<50ms for enricher step)

## 4. Documentation

- [x] 4.1 Update `CLAUDE.md` model table: Context Enricher row → `Qwen 2.5-1.5B-Instruct | Q4_K_M | ModelManager.load_qwen_1_5b()`
- [x] 4.2 Update `CLAUDE.md` Current Status / Recent Changes to note v5 enricher deployed
