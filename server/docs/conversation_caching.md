# Conversation-Aware Caching Design

## Problem

Current caching is per-message — each normalized query is matched independently against ChromaDB. This fails for multi-turn conversations where messages depend on context:

- Turn 1: "What is Python?" — works fine standalone
- Turn 3: "Tell me more about decorators" — ambiguous without context
- Turn 5: "Can you give an example?" — meaningless without context

Wrong cache hits occur when different conversations share vague messages like "Can you explain more?"

## Solution: Context-Enriched Normalization

Add a **context enrichment step** before the normalizer that collapses conversation history + current message into a standalone query.

### Pipeline Change

```
Current:  user message → normalize → cache lookup
Proposed: user message + conversation history → enrich → normalize → cache lookup
```

### Example

**History:**
- User: "What is Python?"
- Assistant: "It's a programming language..."
- User: "Tell me about decorators"

**Enriched query:** "What are decorators in Python programming?"

This enriched query normalizes well, caches correctly, and matches future conversations asking the same thing.

## Implementation Plan

### 1. New Service: `app/services/context_enricher.py`

- Uses Qwen 2.5-0.5B (already loaded via ModelManager)
- Prompt: "Rewrite this message as a standalone question using the conversation context"
- Input: current message + last 2-4 turns of history
- Output: self-contained query string
- First-message optimization: if no history, return the message as-is (skip enrichment)

### 2. Changes to `app/routers/chat.py`

Update the pipeline in both `POST /chat` and `WS /ws/chat`:

```
# Before (current)
clean_query = normalizer.normalize(request.message)
cached_answer = memory.check_cache(clean_query)

# After (new)
enriched = enricher.enrich(request.message, history)  # NEW STEP
clean_query = normalizer.normalize(enriched)           # normalizer gets better input
cached_answer = memory.check_cache(clean_query)
```

- LLM still receives **original message + full history** (no change to generation quality)
- Cache stores the enriched+normalized key

### 3. No changes needed to

- `ConversationStore` — already tracks history
- `MemoryService` (ChromaDB) — works exactly as before
- `LLMRouterService` — still gets original query + history
- `ContextAdjusterService` — generalize/adjust unchanged

## Design Decisions

| Decision | Choice | Reasoning |
|----------|--------|-----------|
| History window for enricher | Last 2-4 turns | Qwen context window is small; recent turns capture the topic |
| Model for enrichment | Qwen 2.5-0.5B | Already loaded, fast, good enough for rewriting |
| First message handling | Skip enrichment | No context to enrich, avoids unnecessary inference |
| Cache key source | Enriched + normalized query | Self-contained = better cache matches across conversations |
