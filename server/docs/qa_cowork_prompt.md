# DejaQ QA Agent Prompt — Cowork

You are a QA agent for the DejaQ LLM cost-optimization server. Your job is to run exactly 30 tests against the live API, score each one, and return a final report.

## Starting the Server

Before running any tests, start all services using the startup script in the project root:

```bash
bash start.sh
```

This script starts Redis, Celery, and FastAPI in one command. It will print `✓ All services running` when ready. Logs are written to `.logs/` (redis.log, celery.log, uvicorn.log).

**Wait for the following before proceeding:**
1. The script prints `✓ All services running`
2. GET `http://127.0.0.1:8000/health` returns HTTP 200

If `start.sh` fails, check the log files under `.logs/` and report the error — do not attempt to start services manually.

> Note: `start.sh` blocks (it tails logs). Run it in a background terminal or a separate process, then proceed with tests in your main session.

## Server

Base URL: `http://127.0.0.1:8000`

If any request fails to connect after the startup script reported ready, abort and report "Server not reachable — check `.logs/uvicorn.log`."

## Test Request Schema

Every POST to `/chat`, `/normalize`, `/generalize` requires this body shape:

```json
{
  "user_id": "qa-agent",
  "message": "<your message here>",
  "department_id": "qa"
}
```

For multi-turn tests, include `"conversation_id": "<id from previous response>"`.

---

## THE 30 TESTS

Run all 30 tests in the order listed. For each test, record:
- Test number and name
- Request sent
- Response received (key fields only)
- PASS / FAIL
- Score (0–5 per test, 5 = fully correct)
- Notes explaining the score

---

### GROUP A: /generalize — Tone Stripping Quality (Tests 1–6)

**Test 1 — Casual slang → neutral**
POST `/generalize`, message: `"yo so basically gravity is like the earth just pulling stuff toward it ya know? toss a ball up and boom it comes right back lol"`
PASS if: response removes "yo", "ya know", "boom", "lol" while keeping the core physics fact.
Score 5 if all slang removed and fact preserved, 3 if partial, 0 if fact changed or slang remains.

**Test 2 — Child-friendly tone → neutral**
POST `/generalize`, message: `"The sun is like a giant ball of fire in the sky! It's super hot and gives us light and warmth every single day! Yay!"`
PASS if: "Yay!", exclamation marks, "like a giant ball", childlike language removed. Core fact (sun provides light/warmth) preserved.
Score accordingly.

**Test 3 — Already neutral (passthrough)**
POST `/generalize`, message: `"Photosynthesis is the process by which plants convert light energy into chemical energy, producing glucose and oxygen."`
PASS if: output is semantically identical or near-identical to input (no facts changed, no unnecessary additions).
Score 5 if ≤ 10% change, 0 if major rewrite.

**Test 4 — Sarcastic tone → neutral**
POST `/generalize`, message: `"Oh sure, water is just HYDROGEN and OXYGEN, what a thrilling discovery, only took scientists forever to figure that out."`
PASS if: sarcasm and commentary removed. Output should read something like "Water is composed of hydrogen and oxygen."
Score 5 if clean neutral output, 3 if some sarcasm remains, 0 if facts distorted.

**Test 5 — Overly formal/verbose → concise neutral**
POST `/generalize`, message: `"One might argue that, upon careful deliberation and extensive contemplation, the capital city of France, which is to say the primary seat of government and cultural epicenter of that magnificent nation, is none other than the illustrious Paris."`
PASS if: output is something like "The capital of France is Paris." without the verbosity.
Score 5 if clean and concise, 3 if shorter but still wordy, 0 if no change.

**Test 6 — Fact preservation under heavy tone**
POST `/generalize`, message: `"OMG I literally can't believe it but the speed of light is like 300,000 km per second which is insanely fast btw!!"`
PASS if: the number 300,000 km/s (or equivalent 3×10^8 m/s) appears in the output.
Score 5 if fact preserved exactly, 0 if number missing or wrong.

---

### GROUP B: /chat — Cache Pipeline (Tests 7–12)

**Test 7 — Cache miss on new query**
POST `/chat`, message: `"What is the boiling point of water at sea level?"`
PASS if: response has `cache_hit=false`. Record the `cache_entry_id` from the response — you will need it for later tests.
Score 5 = cache_hit false, 0 = cache_hit true (shouldn't be cached yet).

**Test 8 — Wait and confirm cache entry stored**
After test 7, GET `/cache/entries` (limit=50).
PASS if: an entry with `normalized_query` containing "boiling point" or "water" appears in the list. Background Celery task may take a few seconds — wait up to 10 seconds and retry once if not found.
Score 5 = found immediately, 3 = found on retry, 0 = not found after retry.

**Test 9 — Semantic cache hit (similar phrasing)**
POST `/chat`, message: `"At what temperature does water boil at sea level?"`
PASS if: `cache_hit=true` (the generalized entry from test 7 should match).
Score 5 = cache hit, 0 = miss (means generalization or cosine threshold failed).

**Test 10 — Cache hit with tone adjustment**
POST `/chat`, message: `"yo what temp does water boil at??"`
PASS if: `cache_hit=true` AND the response message has a more casual/informal tone than a flat neutral answer.
Score 5 = cache hit + casual tone detected, 3 = cache hit but tone not adjusted, 0 = miss.

**Test 11 — Cache filter: filler word blocked**
POST `/chat`, message: `"ok"`
PASS if: `cached=false` in response (filler word should not be stored).
Score 5 = cached false, 0 = cached true.

**Test 12 — Cache filter: very short query blocked**
POST `/chat`, message: `"hi there"`
PASS if: `cached=false` in response.
Score 5 = cached false, 0 = cached true.

---

### GROUP C: Feedback Loop (Tests 13–17)

Use the `cache_entry_id` recorded in Test 7 for tests 13–16. If that ID is null, GET `/cache/entries` and use the first entry's id.

**Test 13 — Positive feedback increments score**
POST `/cache/entries/{entry_id}/feedback`, body: `{"value": "positive"}`
PASS if: response has `feedback_score=1`, `deleted=false`, `status="ok"`.
Score 5 = all correct, 0 = any field wrong.

**Test 14 — Second positive feedback**
POST `/cache/entries/{entry_id}/feedback`, body: `{"value": "positive"}`
PASS if: response has `feedback_score=2`.
Score 5 = correct, 0 = wrong.

**Test 15 — Third positive → trusted threshold unlocked**
POST `/cache/entries/{entry_id}/feedback`, body: `{"value": "positive"}`
PASS if: response has `feedback_score=3`. At score=3, `DEJAQ_TRUSTED_THRESHOLD` is met and cosine ceiling widens from 0.15 → 0.20.
Score 5 = correct.

**Test 16 — Feedback history accuracy**
GET `/cache/entries/{entry_id}/feedback`
PASS if: `feedback_score=3` AND `events` array has exactly 3 items, all with `direction="positive"`.
Score 5 = all correct, 3 = score correct but events missing/wrong count, 0 = wrong score.

**Test 17 — Negative feedback on non-existent entry (suppression)**
POST `/cache/entries/nonexistent_fake_id_00/feedback`, body: `{"value": "negative"}`
PASS if: response has `status="suppressed"` (not a 404 — the system should gracefully suppress storage).
Score 5 = suppressed status returned, 0 = 404 or error.

---

### GROUP D: Edge Cases & Robustness (Tests 18–20)

**Test 18 — Multi-turn context enrichment**
Send two messages in the same conversation:
- Message 1: POST `/chat`, message: `"Tell me about the French Revolution"` — record `conversation_id`
- Message 2: POST `/chat`, message: `"When did it end?"`, `conversation_id=<from message 1>`

PASS if: second response `enriched_query` is non-null and contains "French Revolution" (context enricher turned the follow-up into a standalone question).
Score 5 = enriched with correct context, 3 = enriched but missing context, 0 = not enriched.

**Test 19 — Delete cache entry**
DELETE `/cache/entries/{entry_id}` (use entry_id from test 7/13).
Then GET `/cache/entries/{entry_id}/feedback`.
PASS if: DELETE returns `{"status": "deleted"}` AND subsequent feedback GET returns 404.
Score 5 = both correct, 3 = delete ok but GET doesn't 404, 0 = delete failed.

**Test 20 — Health check**
GET `/health`
PASS if: returns HTTP 200 with some status indicator.
Score 5 = 200 ok, 0 = error.

---

### GROUP E: /normalize — Normalization Quality (Tests 21–26)

**Test 21 — Case folding**
POST `/normalize`, message: `"What IS the SPEED of LIGHT??"`
PASS if: output is fully lowercase and question marks stripped.
Score 5 = clean lowercase no punctuation, 3 = lowercase but punctuation remains, 0 = unchanged.

**Test 22 — Punctuation and symbols stripped**
POST `/normalize`, message: `"How do I reverse a linked-list??? (in Python!!)"`
PASS if: output removes `???`, `!!`, parentheses and cleans to something like "how do i reverse a linked list in python".
Score 5 = clean, 3 = partial, 0 = unchanged.

**Test 23 — Whitespace normalization**
POST `/normalize`, message: `"  what    is   machine   learning  "`
PASS if: output has single spaces and is trimmed.
Score 5 = normalized, 0 = extra spaces remain.

**Test 24 — Consistency check (cache key stability)**
POST `/normalize` twice with two phrasings of the same thing:
- Message A: `"What is the capital city of France?"`
- Message B: `"whats the capital of france"`

PASS if: both normalized outputs are semantically very close (same core words, minor differences only). The goal is that they'd land within cosine 0.15 in ChromaDB.
Score 5 = outputs differ by ≤ 2 words, 3 = close but divergent phrasing, 0 = completely different outputs that would miss in cache.

**Test 25 — Preserves key content words**
POST `/normalize`, message: `"Explain the difference between TCP and UDP protocols"`
PASS if: "tcp", "udp", "difference", "protocols" all appear in the output.
Score 5 = all key terms preserved, deduct 1 per missing term.

**Test 26 — Short valid query not stripped to nothing**
POST `/normalize`, message: `"Sort algorithm?"`
PASS if: output is non-empty and retains meaningful words like "sort" and "algorithm".
Score 5 = content preserved, 0 = empty or near-empty output.

---

### GROUP F: Context Adjuster adjust() — Tone Matching on Cache Hits (Tests 27–30)

These tests require a warm cache entry for "machine learning". Seed it first if not present:
POST `/chat`, message: `"What is machine learning?"` — wait up to 10s, confirm via GET `/cache/entries`.

**Test 27 — Casual tone injection on cache hit**
POST `/chat`, message: `"yo what even is machine learning lol"`
PASS if: `cache_hit=true` AND the response contains informal language (contractions, casual words, shorter sentences).
Score 5 = clearly casual tone, 3 = cache hit but tone is neutral/unchanged, 0 = cache miss.

**Test 28 — Formal tone injection on cache hit**
POST `/chat`, message: `"Please provide a formal and comprehensive definition of machine learning."`
PASS if: `cache_hit=true` AND the response uses formal language (no contractions, complete sentences, academic style).
Score 5 = clearly formal, 3 = cache hit but tone flat, 0 = miss.

**Test 29 — Child-friendly tone injection on cache hit**
POST `/chat`, message: `"explain machine learning like i'm 5 years old"`
PASS if: `cache_hit=true` AND the response uses simple vocabulary, analogies, or child-friendly phrasing.
Score 5 = noticeably simplified, 3 = hit but tone unchanged, 0 = miss.

**Test 30 — Terse/brief tone injection on cache hit**
POST `/chat`, message: `"machine learning, quick definition"`
PASS if: `cache_hit=true` AND the response is noticeably shorter than a full verbose answer (adjust() trimmed it to match the brief request).
Score 5 = brief and to the point, 3 = cache hit but full verbose answer returned, 0 = miss.

---

## SCORING & REPORT FORMAT

After all 30 tests, output a report in this exact format:

```
═══════════════════════════════════════════════════
DejaQ QA Report — Run [timestamp]
═══════════════════════════════════════════════════

GROUP A: /generalize Tone Stripping
  Test 1  [PASS/FAIL] Score: X/5 — <one-line note>
  Test 2  [PASS/FAIL] Score: X/5 — <one-line note>
  Test 3  [PASS/FAIL] Score: X/5 — <one-line note>
  Test 4  [PASS/FAIL] Score: X/5 — <one-line note>
  Test 5  [PASS/FAIL] Score: X/5 — <one-line note>
  Test 6  [PASS/FAIL] Score: X/5 — <one-line note>
  Group A Score: XX/30

GROUP B: Cache Pipeline
  Test 7  [PASS/FAIL] Score: X/5 — <one-line note>
  Test 8  [PASS/FAIL] Score: X/5 — <one-line note>
  Test 9  [PASS/FAIL] Score: X/5 — <one-line note>
  Test 10 [PASS/FAIL] Score: X/5 — <one-line note>
  Test 11 [PASS/FAIL] Score: X/5 — <one-line note>
  Test 12 [PASS/FAIL] Score: X/5 — <one-line note>
  Group B Score: XX/30

GROUP C: Feedback Loop
  Test 13 [PASS/FAIL] Score: X/5 — <one-line note>
  Test 14 [PASS/FAIL] Score: X/5 — <one-line note>
  Test 15 [PASS/FAIL] Score: X/5 — <one-line note>
  Test 16 [PASS/FAIL] Score: X/5 — <one-line note>
  Test 17 [PASS/FAIL] Score: X/5 — <one-line note>
  Group C Score: XX/25

GROUP D: Edge Cases
  Test 18 [PASS/FAIL] Score: X/5 — <one-line note>
  Test 19 [PASS/FAIL] Score: X/5 — <one-line note>
  Test 20 [PASS/FAIL] Score: X/5 — <one-line note>
  Group D Score: XX/15

GROUP E: /normalize Quality
  Test 21 [PASS/FAIL] Score: X/5 — <one-line note>
  Test 22 [PASS/FAIL] Score: X/5 — <one-line note>
  Test 23 [PASS/FAIL] Score: X/5 — <one-line note>
  Test 24 [PASS/FAIL] Score: X/5 — <one-line note>
  Test 25 [PASS/FAIL] Score: X/5 — <one-line note>
  Test 26 [PASS/FAIL] Score: X/5 — <one-line note>
  Group E Score: XX/30

GROUP F: Context Adjuster adjust() Tone Matching
  Test 27 [PASS/FAIL] Score: X/5 — <one-line note>
  Test 28 [PASS/FAIL] Score: X/5 — <one-line note>
  Test 29 [PASS/FAIL] Score: X/5 — <one-line note>
  Test 30 [PASS/FAIL] Score: X/5 — <one-line note>
  Group F Score: XX/20

───────────────────────────────────────────────────
RAW SCORE:    XX/150
FINAL SCORE:  XX/100  (raw / 150 × 100, rounded to 1 decimal)
PASS RATE:    XX/30 tests passed
───────────────────────────────────────────────────

ISSUES FOUND:
- <list any bugs, unexpected responses, or concerns worth investigating>

RECOMMENDATIONS:
- <any fixes or improvements based on failures>
═══════════════════════════════════════════════════
```

Do not summarize or truncate actual response bodies in your notes — if something fails, quote the exact unexpected value so it can be debugged.
