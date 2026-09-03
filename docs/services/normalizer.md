# Normalizer

The normalizer's job is to turn a user's question into a **cache key** — a clean, consistent form that can be matched against previous questions in the cache.

## The problem it solves

Two users can ask the same thing in completely different ways:

- "What's the best coffee?" vs "Which coffee is the greatest?"
- "why is Ukraine at war with Russia?" vs "why is russia at war with ukraine?"

Without normalization, the cache would treat these as different questions and call the LLM twice. The normalizer collapses variations into a single key so the cache finds the match.

## How it works

Every query goes through one gate before hitting the cache:

### Opinion gate

The normalizer checks whether the question is asking for a subjective recommendation ("best", "greatest", "top-rated", "finest", etc.) or a factual question.

**Factual question** → lowercase passthrough. No model is called. Fast.

```
"Why is Ukraine at war with Russia?" → "why is ukraine at war with russia?"
"How does photosynthesis work?"      → "how does photosynthesis work?"
```

**Opinion question** → an LLM rewrites it to a short canonical form (default `granite4.1:3b` on master, per-workspace configurable via `normalizer_model`).

```
"What is the greatest coffee bean origin?" → "best coffee"
"Which country produces the finest coffee?" → "best coffee"
"What are the top-rated hiking boots?"      → "best hiking boot"
```

This ensures that any phrasing of "best X" maps to the same cache key, so the cache works across all opinion phrasings.

### Why not just use embeddings for everything?

Embeddings handle semantic similarity well (0.01 distance between "Ukraine at war with Russia" and "Russia at war with Ukraine"), but they struggle when the surface form is very different. The opinion rewrite makes these cases exact string matches instead of relying on the embedding distance threshold.

## The howto guard

One edge case: "What's the best way to cook steak?" uses "best" but isn't asking for a recommendation — it's asking for a method. The normalizer detects this pattern (best + way/method/technique/approach/...) and routes it to the factual passthrough instead of the opinion rewriter.

## Where it fits in the pipeline

```
User query
    ↓
Opinion? ──yes──> LLM rewrite (granite4.1:3b default) ──> "best <noun>"
    │
    no
    ↓
Lowercase passthrough
    ↓
Cache key (used for lookup + storage)
```

## Typos

The normalizer does not correct spelling — deliberately, since a dictionary checker mangles jargon
and proper nouns and poisons the cache key. Typo'd phrasings are handled downstream instead, by the
embedding distance tiers and word-level alignment described under "Typo handling" in `CLAUDE.md` and
measured in [lexical-match-report.md](../lexical-match-report.md).

## Source

`server/app/services/normalizer.py`
