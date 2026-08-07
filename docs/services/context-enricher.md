# Context Enricher

The context enricher's job is to make a follow-up question **self-contained** before it reaches the cache. Without it, vague follow-ups would be stored under useless keys and never produce cache hits.

## The problem it solves

In a conversation, people naturally ask short follow-up questions that only make sense in context:

> User: "Tell me about the Roman Empire."
> Bot: "The Roman Empire was..."
> User: **"When did it fall?"**

"When did it fall?" is meaningless without the conversation history. If it went into the cache as-is, it would never match a future user asking "When did the Roman Empire fall?" — even though they're asking the exact same thing.

The enricher rewrites the follow-up into a standalone question:

> "When did it fall?" → "When did the Roman Empire fall?"

Now it can be normalized, cached, and matched against future queries correctly.

## How it works

### Step 1 — History check

If there's no conversation history, the enricher skips inference entirely and returns the message as-is. A first message is always self-contained by definition.

### Step 2 — LLM rewrite

If history exists, the enricher sends the last 3 turns of conversation (up to 6 messages) along with the follow-up to a small LLM (Qwen 2.5-1.5B). The model is instructed to rewrite the follow-up into a standalone question.

The model uses four built-in examples to understand the task:

| History topic | Follow-up | Rewritten |
|---|---|---|
| Python is a programming language | "Tell me more about its features" | "What are the main features of Python?" |
| Photosynthesis converts light to energy | "What about the dark reactions?" | "What are the dark reactions in photosynthesis?" |
| The capital of Italy is Rome | "I am traveling there, recommend restaurants" | "What restaurants should I visit in Rome?" |
| (gravity topic) | "What is the capital of France?" | "What is the capital of France?" *(unchanged — already standalone)* |

The fourth example is critical: if the follow-up is already a standalone question, the model returns it unchanged. This is how the enricher avoids unnecessary rewrites without a separate gating step.

### What the enricher does NOT do

- It does not summarize, rephrase for tone, or change the meaning
- It does not answer the question
- It does not correct spelling — nothing in the pipeline does; typos are handled downstream by
  the distance tiers and word-level alignment (see [normalizer.md](normalizer.md))
- It does not run when there's no history

## Where it fits in the pipeline

```
User message + conversation history
    ↓
No history? ──yes──> return message as-is
    │
    no
    ↓
Qwen 1.5B rewrites follow-up into standalone question
    ↓
Enriched query (self-contained, ready for normalization)
    ↓
Normalizer → Cache lookup
```

The original message (not the enriched version) is still what gets sent to the LLM for answering. This preserves the user's tone and phrasing in the response, while the enriched version is only used as the cache key.

## Known limitations

**Bare comparative questions** — "Which is cheaper?" or "Which came first?" without naming the subjects can't be resolved if the model doesn't know which two things are being compared. The 1.5B model sometimes fails these and may return the question unchanged or hallucinate subjects. Fixing this properly requires extracting the subjects from the conversation before prompting.

## Source

`server/app/services/context_enricher.py`
