# Verification screenshots

Manual E2E evidence checked into the repo alongside the commits/PRs they verify. Not living
documentation - each image is a one-time snapshot from the verification pass named in its row;
consult the commit/PR for the full description, not the image alone.

## `decision-card/`

Local-path decision cards from the manual E2E pass for PR #76 (commit `fd7f02c`,
"feat(logging): one decision card per request in 'requests' log mode"), rendered from
headless-tmux-verified terminal output.

| File | Verifies |
|---|---|
| `01-local-miss.png` | Cold cache miss, routed to the local model |
| `02-trusted-hit.png` | Trusted-tier cache hit (cosine ≤ `DEJAQ_CACHE_TRUST_DISTANCE`) |
| `03-validator-accept.png` | Band-tier hit, Cache Validator accepts |
| `04-validator-reject.png` | Band-tier hit, Cache Validator rejects (treated as a miss) |
| `05-attachment-judge.png` | An attachment routed through the hard-content judge |
| `06-rag.png` | A RAG-grounded question |
| `07-enricher.png` | A multi-turn follow-up, showing the context enricher's rewrite line |

See `docs/e2e/` for the other verification screenshot, tied to a different PR.
