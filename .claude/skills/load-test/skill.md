---
name: load-test
description: Sends ~100 realistic prompts to the running DejaQ stack as a specific persona, organized as multi-turn conversations. Creates a matching department in the demo org each run. Writes a live-updating markdown report. Usage: /load-test <persona description>
---

Run a realistic load test against the DejaQ stack, impersonating a given persona.
Each run creates a fresh department in the demo org. Prompts are organized as **multi-turn
conversation threads** — each thread sends messages sequentially with the full history
accumulated in the `messages` array, then resets for the next thread.

## Steps

### 1. Parse the persona

The user invokes this skill as `/load-test <persona>`. Extract the persona from the args.

If no persona was given, ask: "What persona should I simulate? (e.g. 'CS students studying algorithms', 'marketing team at a SaaS company', 'medical residents')"

### 2. Check if DejaQ is already running

```bash
curl -s --max-time 3 http://127.0.0.1:8000/health
```

- 200 response → stack is up, skip to step 4.
- Fails → proceed to step 3.

### 3. Start the DejaQ stack

Tell the user: "Starting DejaQ stack (in-process mode)..."

```bash
DEJAQ_MODE=in-process DEJAQ_EXTERNAL_MODEL=claude-haiku-4-5-20251001 ./server/scripts/start.sh &
```

Poll `/health` every 3 seconds (up to 90s) until 200. Tell the user when ready.

### 4. Ensure demo org and API key exist

```bash
cd server && uv run dejaq-admin org list 2>/dev/null
```

If `demo` org does not exist:
```bash
cd server && uv run dejaq-admin seed demo 2>/dev/null
```

Get the API key:
```bash
cd server && uv run dejaq-admin key list --org demo 2>/dev/null
```

If none, create one:
```bash
cd server && uv run dejaq-admin key create --org demo --name "load-test" 2>/dev/null
```

If the CLI only shows truncated tokens, read the full key directly:
```bash
sqlite3 server/dejaq.db "SELECT token FROM api_keys WHERE revoked_at IS NULL AND org_id = (SELECT id FROM organizations WHERE slug='demo') LIMIT 1;"
```

### 5. Create a department for this run

Derive a slug from the persona: lowercase, spaces/special chars → hyphens, max 50 chars.
Add today's date suffix (YYYYMMDD) to avoid collisions across runs.
Example: `cs-students-algorithms-20260503`

```bash
cd server && uv run dejaq-admin dept create --org demo --name "<full persona name> <YYYYMMDD>" 2>/dev/null
```

Note the `slug` and `cache_namespace` from the output — send the slug as `X-DejaQ-Department`.

### 6. Generate conversation threads for the persona

Generate **20–25 conversation threads**, totaling ~100 turns across all threads.
Each thread is 2–6 turns. Mix thread lengths: some are quick 2-turn exchanges, others are
longer 5-6 turn deep dives where the user keeps drilling down.

**Structure per thread:**
- Turn 1: standalone question with context (sets the topic)
- Turn 2+: natural follow-ups that reference the previous answer — "how does that interact with X?",
  "what if our budget is only 20k?", "can you give me a concrete example?", "why does that happen?"
  These should sound like someone who got an answer and wants to dig deeper, NOT a new topic.
- Each thread ends when the topic is exhausted naturally.

**Persona authenticity:** Prompts must sound like a real person in that role mid-task.
Not textbook definitions. Not generic "what is X" questions. Think: someone hitting a real
problem, with real constraints, using the actual tools and vocabulary of their role.

For a Google marketing team: Google Ads internals (PMax, Smart Bidding, Quality Score, tROAS,
DDA, brand lift, GA4, YouTube, first-party data), campaign troubleshooting, stakeholder
justification, competitive positioning — not "what is SEO".

**Turn length:** every turn must be at least 2 sentences. First sentence = context or
reference to what was just discussed. Second = the actual question.

**Difficulty mix across all turns (~100 total):**
- ~25 hard turns: multi-step, analytical, strategic — require reasoning or trade-off analysis
- ~75 easy turns: specific, practical, factual — grounded in real context

**Format — generate as a Python list of lists:**
```python
CONVERSATIONS: list[list[str]] = [
    # Thread 1 — topic: PMax cannibalization
    [
        "Our Performance Max campaign launched 3 weeks ago and brand search volume dropped 18% since then. How do I tell if PMax is cannibalizing brand traffic or if the drop is organic?",
        "You mentioned brand exclusions — does adding a brand exclusion to PMax prevent it from showing on brand queries entirely, or just deprioritize them?",
        "If I add the brand exclusion and brand search volume recovers, does that mean PMax was definitely the cause, or could there be other explanations?",
    ],
    # Thread 2 — topic: tROAS tuning
    [
        "We set our tROAS at 500% six months ago and the campaign has been stable, but the team wants to push it to 700% to improve margin. What actually happens to delivery and spend when you raise tROAS that aggressively?",
        "So if the algorithm becomes more selective, does that mean our impression share will drop even on high-intent queries we were winning before?",
    ],
    # ... more threads
]
```

Do NOT shuffle within threads (turns must stay in order). You can vary which threads appear
first, but within each thread the turns are sequential.

### 7. Write the load test script and tell the user to run it

After writing the script to `/tmp/dejaq_load_test.py`, **do NOT run it yourself**. Instead, tell the user:

> "Script is ready. Run this in your terminal — Claude can't run it due to tool timeout limits:
> ```bash
> /Users/jonathansheffer/Desktop/Coding/DejaQ/server/.venv/bin/python /tmp/dejaq_load_test.py
> ```
> The report will update live at `load-test-reports/<dept-slug>.md`."

Then skip to step 8 and report what you've set up (persona, dept slug, thread count, turn count).

### 7a. Write the load test script

Write the script to `/tmp/dejaq_load_test.py`. Fill in `CONVERSATIONS`, `API_KEY`, `DEPT_SLUG`,
`PERSONA`, and `REPORT_PATH`.

`REPORT_PATH` must be set to:
```
/Users/jonathansheffer/Desktop/Coding/DejaQ/load-test-reports/<dept-slug>.md
```

Create the directory if it doesn't exist:
```bash
mkdir -p /Users/jonathansheffer/Desktop/Coding/DejaQ/load-test-reports
```

**Response type classification:** use `x-dejaq-model-used` header to distinguish three types:
- `"cache"` → cache hit (served from ChromaDB)
- local model name (e.g. `gemma_local`, `gemma4:e4b`) → easy miss (routed to local LLM)
- external model name (e.g. `claude-haiku-4-5-20251001`, `gemini-2.5-flash`) → hard miss (routed to external provider)

**Difficulty score:** read `x-dejaq-prompt-difficulty-score` header (float 0.0–1.0).
This header is set by the server on every cache-miss response.

**Cache hit metadata (new headers):**
- `x-dejaq-cache-distance` — cosine distance to the matched entry (float, lower = closer match)
- `x-dejaq-cache-matched-query` — the normalized query stored in ChromaDB that triggered the hit

**Prompt display:** do NOT truncate prompts in the report. Show full prompt text in the table.
Use `<details><summary>…</summary>…</details>` HTML in the markdown for long prompts so the
table stays readable but the full text is accessible on click.

The script must do everything below:

```python
#!/usr/bin/env python3
"""DejaQ load test — multi-turn conversations, sequential, with live MD report."""
import asyncio
import time
import statistics
import datetime

PERSONA = "PLACEHOLDER"
API_KEY = "PLACEHOLDER"
DEPT_SLUG = "PLACEHOLDER"
REPORT_PATH = "/tmp/dejaq_load_test_report.md"
BASE_URL = "http://127.0.0.1:8000"

# List of conversation threads. Each thread is a list of user turns (strings).
# Turns are sent sequentially; history accumulates within each thread.
CONVERSATIONS: list[list[str]] = [
    # PLACEHOLDER
]

LOCAL_MODEL_NAMES = {"gemma_local", "gemma4:e4b", "gemma4:e2b", "local"}


def classify_response_type(model_used: str | None, resp_id: str | None, status: int) -> str:
    if status != 200:
        return "error"
    if model_used == "cache":
        return "cache_hit"
    if model_used and any(local in model_used for local in LOCAL_MODEL_NAMES):
        return "easy_miss"
    if model_used and model_used not in ("cache", "error", ""):
        return "hard_miss"
    if resp_id and ":" in resp_id:
        return "easy_miss"
    return "easy_miss"


def write_report(results: list[dict], persona: str, dept: str, total_turns: int, in_progress: bool = True) -> None:
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cache_hits  = [r for r in results if r["response_type"] == "cache_hit"]
    easy_misses = [r for r in results if r["response_type"] == "easy_miss"]
    hard_misses = [r for r in results if r["response_type"] == "hard_miss"]
    errs        = [r for r in results if r["response_type"] == "error"]
    latencies   = [r["latency_ms"] for r in results if r["response_type"] != "error"]
    total = len(results)

    STATUS_ICON = {
        "cache_hit": "✅ CACHE HIT",
        "easy_miss": "🟡 EASY MISS",
        "hard_miss": "🔴 HARD MISS",
        "error":     "❌ ERROR",
    }

    lines = []
    lines.append("# DejaQ Load Test Report")
    lines.append("")
    lines.append(f"**Persona:** {persona}  ")
    lines.append(f"**Department:** `{dept}`  ")
    lines.append(f"**Updated:** {now}  ")
    progress = f"⏳ In progress ({total}/{total_turns} turns)" if in_progress else "✅ Complete"
    lines.append(f"**Status:** {progress}  ")
    lines.append("")

    if total > 0:
        lines.append("## Summary")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append(f"| Total turns | {total} |")
        lines.append(f"| ✅ Cache hits | {len(cache_hits)} ({100*len(cache_hits)//total}%) |")
        lines.append(f"| 🟡 Easy misses (local LLM) | {len(easy_misses)} ({100*len(easy_misses)//total}%) |")
        lines.append(f"| 🔴 Hard misses (external LLM) | {len(hard_misses)} ({100*len(hard_misses)//total}%) |")
        lines.append(f"| ❌ Errors | {len(errs)} |")
        if latencies:
            s = sorted(latencies)
            n = len(s)
            lines.append(f"| Latency p50 | {s[n//2]} ms |")
            lines.append(f"| Latency p95 | {s[int(n*0.95)]} ms |")
            lines.append(f"| Latency p99 | {s[int(n*0.99)]} ms |")
            lines.append(f"| Latency avg | {int(statistics.mean(s))} ms |")
        lines.append("")

    # Group results by thread for the report
    lines.append("## Conversations")
    lines.append("")
    seen_threads: dict[int, list[dict]] = {}
    for r in results:
        seen_threads.setdefault(r["thread_idx"], []).append(r)

    for thread_idx, turns in seen_threads.items():
        topic = turns[0]["prompt"][:60].replace("|", "\\|")
        lines.append(f"### Thread {thread_idx + 1} — {topic}…")
        lines.append("")
        lines.append("| Turn | Type | Latency (ms) | Difficulty | Score | Model | Prompt | Cache match |")
        lines.append("|------|------|-------------|------------|-------|-------|--------|-------------|")
        for r in turns:
            icon = STATUS_ICON.get(r["response_type"], "?")
            score_raw = r.get("diff_score", "")
            score_cell = f"{float(score_raw):.2f}" if score_raw not in ("", None, "—") else "—"
            model_cell = (r.get("model_used") or "—")[:25]
            # Full prompt in collapsible details block
            prompt_escaped = r["prompt"].replace("|", "\\|").replace("\n", " ")
            prompt_short = prompt_escaped[:60]
            if len(r["prompt"]) > 60:
                prompt_cell = f"<details><summary>{prompt_short}…</summary>{prompt_escaped}</details>"
            else:
                prompt_cell = prompt_escaped
            latency = r["latency_ms"] if r["response_type"] != "error" else "—"
            # Cache hit extra info
            if r["response_type"] == "cache_hit":
                dist = r.get("cache_distance", "—")
                matched = (r.get("cache_matched_query") or "—").replace("|", "\\|").replace("\n", " ")
                matched_short = matched[:50]
                if len(matched) > 50:
                    cache_cell = f"dist={dist} <details><summary>{matched_short}…</summary>{matched}</details>"
                else:
                    cache_cell = f"dist={dist} {matched}"
            else:
                cache_cell = "—"
            lines.append(
                f"| {r['turn_idx'] + 1} | {icon} | {latency} | {r.get('difficulty','—')} | {score_cell} | {model_cell} | {prompt_cell} | {cache_cell} |"
            )
        lines.append("")

    if errs:
        lines.append("## Errors")
        lines.append("")
        for e in errs:
            lines.append(f"- **Thread {e['thread_idx']+1} Turn {e['turn_idx']+1}** — `{(e['error'] or '')[:200]}`")
        lines.append("")

    with open(REPORT_PATH, "w") as f:
        f.write("\n".join(lines))


async def send_turn(session, messages: list[dict], prompt: str, thread_idx: int, turn_idx: int) -> tuple[dict, str]:
    """Send one turn. Returns (result, assistant_reply) for history accumulation."""
    import aiohttp
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "X-DejaQ-Department": DEPT_SLUG,
    }
    body = {
        "model": "gpt-3.5-turbo",
        "messages": messages + [{"role": "user", "content": prompt}],
    }
    t0 = time.monotonic()
    try:
        async with session.post(
            f"{BASE_URL}/v1/chat/completions",
            json=body,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=180),
        ) as resp:
            latency_ms = int((time.monotonic() - t0) * 1000)
            resp_id    = resp.headers.get("x-dejaq-response-id")
            model_used = resp.headers.get("x-dejaq-model-used", "")
            difficulty = resp.headers.get("x-dejaq-prompt-difficulty", "—")
            diff_score = resp.headers.get("x-dejaq-prompt-difficulty-score", "—")
            status     = resp.status
            body_text  = await resp.text()

            # Extract assistant reply for history
            assistant_reply = ""
            if status == 200:
                try:
                    import json as _json
                    data = _json.loads(body_text)
                    assistant_reply = data["choices"][0]["message"]["content"]
                except Exception:
                    pass

            cache_distance    = resp.headers.get("x-dejaq-cache-distance", "—")
            cache_matched_query = resp.headers.get("x-dejaq-cache-matched-query", "")
            rtype = classify_response_type(model_used, resp_id, status)
            result = {
                "thread_idx": thread_idx,
                "turn_idx": turn_idx,
                "prompt": prompt,
                "status": status,
                "latency_ms": latency_ms,
                "response_id": resp_id,
                "response_type": rtype,
                "difficulty": difficulty,
                "diff_score": diff_score,
                "model_used": model_used,
                "cache_distance": cache_distance,
                "cache_matched_query": cache_matched_query,
                "error": body_text if status != 200 else None,
            }
            return result, assistant_reply
    except Exception as e:
        latency_ms = int((time.monotonic() - t0) * 1000)
        result = {
            "thread_idx": thread_idx,
            "turn_idx": turn_idx,
            "prompt": prompt,
            "status": 0,
            "latency_ms": latency_ms,
            "response_id": None,
            "response_type": "error",
            "difficulty": "—",
            "diff_score": "—",
            "model_used": None,
            "cache_distance": "—",
            "cache_matched_query": "",
            "error": str(e),
        }
        return result, ""


async def main():
    import aiohttp

    total_turns = sum(len(t) for t in CONVERSATIONS)
    print(f"\n=== DejaQ Load Test ===")
    print(f"Persona       : {PERSONA}")
    print(f"Department    : {DEPT_SLUG}")
    print(f"Threads       : {len(CONVERSATIONS)}")
    print(f"Total turns   : {total_turns}")
    print(f"Report        : {REPORT_PATH}")
    print(f"Strategy      : multi-turn conversations, sequential\n")

    results: list[dict] = []
    write_report(results, PERSONA, DEPT_SLUG, total_turns, in_progress=True)

    TYPE_SHORT = {
        "cache_hit": "HIT ", "easy_miss": "EASY", "hard_miss": "HARD", "error": "ERR ",
    }

    async with aiohttp.ClientSession() as session:
        for thread_idx, thread in enumerate(CONVERSATIONS):
            print(f"\n── Thread {thread_idx + 1}/{len(CONVERSATIONS)} ──────────────────────────")
            history: list[dict] = []  # accumulates {role, content} for this thread

            for turn_idx, prompt in enumerate(thread):
                result, assistant_reply = await send_turn(
                    session, history, prompt, thread_idx, turn_idx
                )
                results.append(result)

                # Accumulate history for next turn
                history.append({"role": "user", "content": prompt})
                if assistant_reply:
                    history.append({"role": "assistant", "content": assistant_reply})

                type_label = TYPE_SHORT.get(result["response_type"], "?")
                score_str = result.get("diff_score", "—")
                try:
                    score_str = f"{float(score_str):.2f}"
                except (ValueError, TypeError):
                    score_str = "—"
                indent = "  " * (turn_idx + 1)
                print(
                    f"{indent}[T{turn_idx + 1}] {type_label} {result['latency_ms']:6d}ms"
                    f"  score={score_str}  {prompt[:55]}"
                )

                write_report(results, PERSONA, DEPT_SLUG, total_turns, in_progress=True)

    write_report(results, PERSONA, DEPT_SLUG, total_turns, in_progress=False)

    cache_hits  = [r for r in results if r["response_type"] == "cache_hit"]
    easy_misses = [r for r in results if r["response_type"] == "easy_miss"]
    hard_misses = [r for r in results if r["response_type"] == "hard_miss"]
    errs        = [r for r in results if r["response_type"] == "error"]
    latencies   = [r["latency_ms"] for r in results if r["response_type"] != "error"]

    print(f"\n{'='*52}")
    print(f"=== DejaQ Load Test Results ===")
    print(f"Persona       : {PERSONA}")
    print(f"Threads       : {len(CONVERSATIONS)}")
    print(f"Total turns   : {len(results)}")
    print(f"Cache hits    : {len(cache_hits):3d}  ({100*len(cache_hits)//len(results)}%)")
    print(f"Easy misses   : {len(easy_misses):3d}  ({100*len(easy_misses)//len(results)}%)")
    print(f"Hard misses   : {len(hard_misses):3d}  ({100*len(hard_misses)//len(results)}%)")
    print(f"Errors        : {len(errs):3d}")
    if latencies:
        s = sorted(latencies)
        n = len(s)
        print(f"\nLatency (ms)")
        print(f"  p50    : {s[n//2]}")
        print(f"  p95    : {s[int(n*0.95)]}")
        print(f"  p99    : {s[int(n*0.99)]}")
        print(f"  avg    : {int(statistics.mean(s))}")
    if errs:
        print(f"\nFirst errors:")
        for e in errs[:3]:
            print(f"  [Thread {e['thread_idx']+1} T{e['turn_idx']+1}] — {(e['error'] or '')[:120]}")
    print(f"\nFull report: {REPORT_PATH}")
    print(f"{'='*52}\n")


if __name__ == "__main__":
    asyncio.run(main())
```

```bash
/Users/jonathansheffer/Desktop/Coding/DejaQ/server/.venv/bin/python /tmp/dejaq_load_test.py
```

### 8. Report to user

Show the final summary. Tell the user:
- The live report is at `DejaQ/load-test-reports/<dept-slug>.md` (open in any markdown viewer)
- Number of threads, total turns
- Cache hit rate, easy miss rate, hard miss rate
- How many hard turns were routed to Anthropic
- Any remaining errors
