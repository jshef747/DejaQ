---
name: load-test
description: Sends ~100 realistic prompts to the running DejaQ stack as a specific persona via the Responses API (/v1/responses), organized as multi-turn conversations. Creates a matching department in the demo org each run. Writes a live-updating markdown report with cache-hit rate, validator rejections, and nearest-cache diagnostics. Usage: /load-test <persona description>
---

Run a realistic load test against the DejaQ stack, impersonating a given persona.
Each run creates a fresh department in the demo org. Prompts are organized as **multi-turn
conversation threads** — each thread sends messages sequentially with the full history
accumulated in the `input` array, then resets for the next thread.

All requests go to `POST /v1/responses` (the OpenAI Responses API endpoint). The server
returns the same `X-DejaQ-*` headers as `/v1/chat/completions`.

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

Tell the user: "Starting DejaQ stack (local mode)..."

```bash
DEJAQ_EXTERNAL_MODEL=claude-haiku-4-5-20251001 DEJAQ_START_LOGS=requests ./start.sh --stack=server --mode=local &
```

`DEJAQ_START_LOGS=requests` is required — without it `start.sh` prompts interactively for log mode and hangs.

Poll `/health` every 3 seconds (up to 90s) until 200. Tell the user when ready.

Note: the cache-answer validator is **on by default**. This is intentional — the report
captures validator rejections. Pass `--validator=off` only if you want to skip validation.

### 4. Ensure demo org and API key exist

```bash
cd server && uv run dejaq-admin org list 2>/dev/null
```

If `demo` org does not exist:
```bash
cd server && uv run dejaq-admin org create --name Demo 2>/dev/null
```

Get the API key:
```bash
cd server && uv run dejaq-admin key list --org demo 2>/dev/null
```

If none, create one:
```bash
cd server && uv run dejaq-admin key generate --org demo 2>/dev/null
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

### 5b. Ensure a hard-query credential exists

Hard turns are classified as `external` and routed to the configured external provider
(`anthropic` when using `claude-haiku-4-5-20251001`). Without an encrypted org credential
the server returns **HTTP 402**. The load test runs regardless, but those turns are reported
as `🟠 HARD MISS (402)` instead of `🔴 HARD MISS`.

Check whether the demo org already has an Anthropic key:

```bash
sqlite3 server/dejaq.db "SELECT provider FROM org_provider_credentials c JOIN organizations o ON o.id=c.org_id WHERE o.slug='demo';"
```

- `anthropic` appears → fine, proceed.
- Empty → add one via the dashboard (**Settings → Credentials → Anthropic**), or via curl
  (requires `DEJAQ_CREDENTIAL_ENCRYPTION_KEY` to be set):
  ```bash
  curl -sX PUT http://127.0.0.1:8000/admin/v1/orgs/demo/credentials/anthropic \
    -H "Authorization: Bearer dev-local" \
    -H "Content-Type: application/json" \
    -d '{"api_key":"<YOUR_ANTHROPIC_API_KEY>"}'
  ```
  If `DEJAQ_CREDENTIAL_ENCRYPTION_KEY` is not set, warn the user but continue — hard turns
  will simply appear as `🟠` rows in the report.

### 6. Generate conversation threads for the persona

Generate **20–25 conversation threads**, totaling ~100 turns across all threads.
Target **4–5 turns per thread on average** — lean toward 5-turn threads. 24 threads × 2–3 turns
averages only ~64 turns; you need enough 5–6 turn threads to hit ~100.
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
> nohup /Users/jonathansheffer/Desktop/Coding/DejaQ/server/.venv/bin/python /tmp/dejaq_load_test.py > /tmp/dejaq_load_test_console.log 2>&1 &
> ```
> Tail progress: `tail -f /tmp/dejaq_load_test_console.log`  
> The report will update live at `evals/load-test-reports/<dept-slug>.md`."

Then skip to step 8 and report what you've set up (persona, dept slug, thread count, turn count).

### 7a. Write the load test script

Write the script to `/tmp/dejaq_load_test.py`. Fill in `CONVERSATIONS`, `API_KEY`, `DEPT_SLUG`,
`PERSONA`, and `REPORT_PATH`.

`REPORT_PATH` must be set to (relative to the repo root):
```
evals/load-test-reports/<dept-slug>.md
```

Create the directory if it doesn't exist:
```bash
mkdir -p evals/load-test-reports
```

**Response type classification:** use `x-dejaq-tier` header (the authoritative source):
- `"cache"` → cache hit (served from ChromaDB)
- `"local"` → easy miss (routed to local LLM)
- `"external"` → hard miss (routed to external provider)
- HTTP 402 → hard miss without a configured credential (`hard_miss_no_cred`)

**Validator verdict:** `x-dejaq-validator-verdict` is set on every response:
- `"valid"` → cache answer accepted
- `"invalid"` → cache candidate was rejected; the turn fell through to LLM generation

**Miss diagnostics (new):** on cache misses the server returns:
- `x-dejaq-nearest-cache-distance` — cosine distance to the closest ChromaDB entry
- `x-dejaq-nearest-cache-prompt` — the normalized query of that nearest entry

**Cache hit metadata:**
- `x-dejaq-cache-distance` — cosine distance to the matched entry
- `x-dejaq-cache-matched-query` — the normalized query that triggered the hit

**Difficulty score:** `x-dejaq-prompt-difficulty-score` (float 0.0–1.0) on cache-miss responses.

**Prompt display:** do NOT truncate prompts in the report. Use `<details><summary>…</summary>…</details>`
HTML for long prompts so the table stays readable but full text is accessible on click.

The script must do everything below:

```python
#!/usr/bin/env python3
"""DejaQ load test — multi-turn conversations via /v1/responses, sequential, with live MD report."""
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
# Turns are sent sequentially; history accumulates within each thread as
# {"role": "user"|"assistant", "content": "..."} items sent in the `input` array.
CONVERSATIONS: list[list[str]] = [
    # PLACEHOLDER
]

# Auto-detect which run number this is from the existing report file.
import os as _os, re as _re
def _detect_run_number() -> int:
    if not _os.path.exists(REPORT_PATH):
        return 1
    with open(REPORT_PATH) as _f:
        _txt = _f.read()
    _n = len(_re.findall(r"^# Run \d+", _txt, _re.MULTILINE))
    return (_n + 1) if _n else (2 if _txt.strip() else 1)
RUN_NUMBER = _detect_run_number()

_COMBINED_MARKER = "\n\n---\n\n## Combined Summary"


def _build_combined_summary(content: str) -> str:
    """Parse per-run ## Summary tables and return a side-by-side comparison table."""
    sections = _re.split(r"\n---\n\n# Run \d+\n\n", content)
    run_stats: list[dict] = []
    for section in sections[1:]:  # skip header block
        stats: dict = {}
        for line in section.split("\n"):
            m = _re.match(r"\|\s*(.+?)\s*\|\s*(.+?)\s*\|", line)
            if not m:
                continue
            k, v = m.group(1).strip(), m.group(2).strip()
            if "Total turns" in k:       stats["total"]     = v
            elif "Cache hits" in k:      stats["cache"]     = v
            elif "Easy misses" in k:     stats["easy"]      = v
            elif "Hard misses" in k and "402" not in k: stats["hard"] = v
            elif "Validator" in k:       stats["validator"] = v
            elif "Errors" in k:          stats["errors"]    = v
            elif "avg" in k.lower():     stats["latency"]   = v
        if stats:
            run_stats.append(stats)
    if not run_stats:
        return ""
    headers = ["Metric"] + [f"Run {i + 1}" for i in range(len(run_stats))]
    rows = [
        ("Total turns",              "total"),
        ("✅ Cache hits",            "cache"),
        ("🟡 Easy misses",           "easy"),
        ("🔴 Hard misses",           "hard"),
        ("🔁 Validator rejections",  "validator"),
        ("❌ Errors",                "errors"),
        ("Latency avg",              "latency"),
    ]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for label, key in rows:
        vals = [s.get(key, "—") for s in run_stats]
        lines.append("| " + " | ".join([label] + vals) + " |")
    return "\n".join(lines)


def classify_response_type(tier: str | None, status: int) -> str:
    if status == 402:
        return "hard_miss_no_cred"
    if status != 200:
        return "error"
    if tier == "cache":
        return "cache_hit"
    if tier == "external":
        return "hard_miss"
    if tier == "local":
        return "easy_miss"
    return "easy_miss"  # fallback for unknown tier


def write_report(results: list[dict], persona: str, dept: str, total_turns: int, in_progress: bool = True) -> None:
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cache_hits       = [r for r in results if r["response_type"] == "cache_hit"]
    easy_misses      = [r for r in results if r["response_type"] == "easy_miss"]
    hard_misses      = [r for r in results if r["response_type"] == "hard_miss"]
    no_cred_misses   = [r for r in results if r["response_type"] == "hard_miss_no_cred"]
    errs             = [r for r in results if r["response_type"] == "error"]
    validator_rejects = [r for r in results if r.get("validator_verdict") == "invalid"]
    latencies        = [r["latency_ms"] for r in results if r["response_type"] not in ("error", "hard_miss_no_cred")]
    total = len(results)

    STATUS_ICON = {
        "cache_hit":         "✅ CACHE HIT",
        "easy_miss":         "🟡 EASY MISS",
        "hard_miss":         "🔴 HARD MISS",
        "hard_miss_no_cred": "🟠 HARD MISS (402)",
        "error":             "❌ ERROR",
    }

    # Build the current run's section content (header lives in the Run 1 block; subsequent runs append)
    progress = f"⏳ In progress ({total}/{total_turns} turns)" if in_progress else "✅ Complete"
    lines: list[str] = []
    lines.append(f"**Updated:** {now}  ")
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
        if no_cred_misses:
            lines.append(f"| 🟠 Hard misses (no credential / 402) | {len(no_cred_misses)} |")
        lines.append(f"| 🔁 Validator rejections (near-hit → miss) | {len(validator_rejects)} |")
        lines.append(f"| ❌ Errors | {len(errs)} |")
        if latencies:
            s = sorted(latencies)
            n = len(s)
            lines.append(f"| Latency p50 | {s[n//2]} ms |")
            lines.append(f"| Latency p95 | {s[int(n*0.95)]} ms |")
            lines.append(f"| Latency p99 | {s[int(n*0.99)]} ms |")
            lines.append(f"| Latency avg | {int(statistics.mean(s))} ms |")
        lines.append("")

    lines.append("## Conversations")
    lines.append("")
    seen_threads: dict[int, list[dict]] = {}
    for r in results:
        seen_threads.setdefault(r["thread_idx"], []).append(r)

    for thread_idx, turns in seen_threads.items():
        topic = turns[0]["prompt"][:60].replace("|", "\\|")
        lines.append(f"### Thread {thread_idx + 1} — {topic}…")
        lines.append("")
        lines.append("| Turn | Type | Latency (ms) | Difficulty | Score | Model | Prompt | Cache / Nearest |")
        lines.append("|------|------|-------------|------------|-------|-------|--------|-----------------|")
        for r in turns:
            icon = STATUS_ICON.get(r["response_type"], "?")
            score_raw = r.get("diff_score", "")
            score_cell = f"{float(score_raw):.2f}" if score_raw not in ("", None, "—") else "—"
            model_cell = (r.get("model_used") or "—")[:25]
            prompt_escaped = r["prompt"].replace("|", "\\|").replace("\n", " ")
            prompt_short = prompt_escaped[:60]
            if len(r["prompt"]) > 60:
                prompt_cell = f"<details><summary>{prompt_short}…</summary>{prompt_escaped}</details>"
            else:
                prompt_cell = prompt_escaped
            latency = r["latency_ms"] if r["response_type"] not in ("error", "hard_miss_no_cred") else "—"
            vv = r.get("validator_verdict", "")
            if r["response_type"] == "cache_hit":
                dist = r.get("cache_distance", "—")
                matched = (r.get("cache_matched_query") or "—").replace("|", "\\|").replace("\n", " ")
                matched_short = matched[:50]
                cache_cell = f"dist={dist} <details><summary>{matched_short}…</summary>{matched}</details>" if len(matched) > 50 else f"dist={dist} {matched}"
            else:
                nd = r.get("nearest_distance", "")
                np_ = (r.get("nearest_prompt") or "").replace("|", "\\|").replace("\n", " ")
                if nd and nd != "—" and np_:
                    cache_cell = f"nearest={nd} <details><summary>{np_[:50]}…</summary>{np_}</details>" if len(np_) > 50 else f"nearest={nd} {np_}"
                else:
                    cache_cell = "—"
                if vv == "invalid":
                    cache_cell = f"⚠️ validator rejected  {cache_cell}"
            lines.append(
                f"| {r['turn_idx'] + 1} | {icon} | {latency} | {r.get('difficulty','—')} | {score_cell} | {model_cell} | {prompt_cell} | {cache_cell} |"
            )
        lines.append("")

    if validator_rejects:
        lines.append("## Validator Rejection Details")
        lines.append("")
        lines.append("> Each entry shows the incoming prompt tested against the nearest cached answer.")
        lines.append("")
        for r in validator_rejects:
            nd = r.get("nearest_distance", "—")
            np_ = r.get("nearest_prompt") or "—"
            lines.append(f"### Thread {r['thread_idx']+1} · Turn {r['turn_idx']+1} — dist={nd}")
            lines.append("")
            lines.append("**Incoming prompt:**")
            lines.append("")
            lines.append(f"> {r['prompt']}")
            lines.append("")
            lines.append("**Nearest cached query:**")
            lines.append("")
            lines.append(f"> {np_}")
            lines.append("")

    if errs or no_cred_misses:
        lines.append("## Errors / 402s")
        lines.append("")
        for e in errs:
            lines.append(f"- **Thread {e['thread_idx']+1} Turn {e['turn_idx']+1}** — `{(e['error'] or '')[:200]}`")
        for e in no_cred_misses:
            lines.append(f"- **Thread {e['thread_idx']+1} Turn {e['turn_idx']+1}** — 402 No credential for provider")
        lines.append("")

    current_run_content = "\n".join(lines)

    # ── Assemble full file ──────────────────────────────────────────────────
    if RUN_NUMBER == 1:
        header = "\n".join([
            "# DejaQ Load Test Report",
            "",
            f"**Persona:** {persona}  ",
            f"**Department:** `{dept}`  ",
            "",
            "---",
            "",
            "# Run 1",
            "",
        ])
        full = header + current_run_content
    else:
        # Read existing, strip old combined summary + stale in-progress block for this run
        existing = ""
        if _os.path.exists(REPORT_PATH):
            with open(REPORT_PATH) as _f:
                existing = _f.read()
        if _COMBINED_MARKER in existing:
            existing = existing[:existing.index(_COMBINED_MARKER)]
        run_marker = f"\n\n---\n\n# Run {RUN_NUMBER}\n\n"
        if run_marker in existing:
            existing = existing[:existing.index(run_marker)]
        full = existing.rstrip() + f"\n\n---\n\n# Run {RUN_NUMBER}\n\n" + current_run_content

    # Append combined summary table when this run completes and we have 2+ runs
    if not in_progress and RUN_NUMBER >= 2:
        combined = _build_combined_summary(full)
        if combined:
            first_run_marker = "\n\n---\n\n# Run 1\n\n"
            if first_run_marker in full:
                idx = full.index(first_run_marker)
                full = full[:idx] + _COMBINED_MARKER + "\n\n" + combined + full[idx:]
            else:
                full += _COMBINED_MARKER + "\n\n" + combined

    with open(REPORT_PATH, "w") as f:
        f.write(full)


async def send_turn(session, history: list[dict], prompt: str, thread_idx: int, turn_idx: int) -> tuple[dict, str]:
    """Send one turn via /v1/responses. Returns (result, assistant_reply) for history accumulation."""
    import aiohttp
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "X-DejaQ-Department": DEPT_SLUG,
    }
    # Build full input: accumulated history + current user turn
    body = {
        "model": "gpt-3.5-turbo",
        "input": history + [{"role": "user", "content": prompt}],
    }
    t0 = time.monotonic()
    try:
        async with session.post(
            f"{BASE_URL}/v1/responses",
            json=body,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=180),
        ) as resp:
            latency_ms = int((time.monotonic() - t0) * 1000)
            tier              = resp.headers.get("x-dejaq-tier", "")
            model_used        = resp.headers.get("x-dejaq-model-used", "")
            difficulty        = resp.headers.get("x-dejaq-prompt-difficulty", "—")
            diff_score        = resp.headers.get("x-dejaq-prompt-difficulty-score", "—")
            validator_verdict = resp.headers.get("x-dejaq-validator-verdict", "")
            cache_distance    = resp.headers.get("x-dejaq-cache-distance", "—")
            cache_matched_query = resp.headers.get("x-dejaq-cache-matched-query", "")
            nearest_distance  = resp.headers.get("x-dejaq-nearest-cache-distance", "—")
            nearest_prompt    = resp.headers.get("x-dejaq-nearest-cache-prompt", "")
            status            = resp.status
            body_text         = await resp.text()

            # Extract assistant reply for history accumulation
            assistant_reply = ""
            if status == 200:
                try:
                    import json as _json
                    data = _json.loads(body_text)
                    assistant_reply = data.get("output_text", "")
                except Exception:
                    pass

            rtype = classify_response_type(tier, status)
            result = {
                "thread_idx":       thread_idx,
                "turn_idx":         turn_idx,
                "prompt":           prompt,
                "status":           status,
                "latency_ms":       latency_ms,
                "response_type":    rtype,
                "difficulty":       difficulty,
                "diff_score":       diff_score,
                "model_used":       model_used,
                "validator_verdict": validator_verdict,
                "cache_distance":   cache_distance,
                "cache_matched_query": cache_matched_query,
                "nearest_distance": nearest_distance,
                "nearest_prompt":   nearest_prompt,
                "error":            body_text if status not in (200, 402) else None,
            }
            return result, assistant_reply
    except Exception as e:
        latency_ms = int((time.monotonic() - t0) * 1000)
        result = {
            "thread_idx":       thread_idx,
            "turn_idx":         turn_idx,
            "prompt":           prompt,
            "status":           0,
            "latency_ms":       latency_ms,
            "response_type":    "error",
            "difficulty":       "—",
            "diff_score":       "—",
            "model_used":       None,
            "validator_verdict": "",
            "cache_distance":   "—",
            "cache_matched_query": "",
            "nearest_distance": "—",
            "nearest_prompt":   "",
            "error":            str(e),
        }
        return result, ""


async def main():
    import aiohttp

    total_turns = sum(len(t) for t in CONVERSATIONS)
    print(f"\n=== DejaQ Load Test (Responses API) ===")
    print(f"Persona       : {PERSONA}")
    print(f"Department    : {DEPT_SLUG}")
    print(f"Threads       : {len(CONVERSATIONS)}")
    print(f"Total turns   : {total_turns}")
    print(f"Report        : {REPORT_PATH}")
    print(f"Strategy      : multi-turn conversations, sequential\n")

    results: list[dict] = []
    write_report(results, PERSONA, DEPT_SLUG, total_turns, in_progress=True)

    TYPE_SHORT = {
        "cache_hit":         "HIT ",
        "easy_miss":         "EASY",
        "hard_miss":         "HARD",
        "hard_miss_no_cred": "402 ",
        "error":             "ERR ",
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

                # Accumulate history; reset on error to prevent cascade failures
                if result["response_type"] == "error":
                    history = []  # Ollama crash/timeout — don't send broken context to next turn
                else:
                    history.append({"role": "user", "content": prompt})
                    if assistant_reply:
                        history.append({"role": "assistant", "content": assistant_reply})

                type_label = TYPE_SHORT.get(result["response_type"], "?")
                score_str = result.get("diff_score", "—")
                try:
                    score_str = f"{float(score_str):.2f}"
                except (ValueError, TypeError):
                    score_str = "—"
                vv_flag = " ⚠️ validator-rejected" if result.get("validator_verdict") == "invalid" else ""
                indent = "  " * (turn_idx + 1)
                print(
                    f"{indent}[T{turn_idx + 1}] {type_label} {result['latency_ms']:6d}ms"
                    f"  score={score_str}  {prompt[:55]}{vv_flag}"
                )

                write_report(results, PERSONA, DEPT_SLUG, total_turns, in_progress=True)

    write_report(results, PERSONA, DEPT_SLUG, total_turns, in_progress=False)

    cache_hits       = [r for r in results if r["response_type"] == "cache_hit"]
    easy_misses      = [r for r in results if r["response_type"] == "easy_miss"]
    hard_misses      = [r for r in results if r["response_type"] == "hard_miss"]
    no_cred_misses   = [r for r in results if r["response_type"] == "hard_miss_no_cred"]
    errs             = [r for r in results if r["response_type"] == "error"]
    validator_rejects = [r for r in results if r.get("validator_verdict") == "invalid"]
    latencies        = [r["latency_ms"] for r in results if r["response_type"] not in ("error", "hard_miss_no_cred")]

    print(f"\n{'='*52}")
    print(f"=== DejaQ Load Test Results ===")
    print(f"Persona       : {PERSONA}")
    print(f"Threads       : {len(CONVERSATIONS)}")
    print(f"Total turns   : {len(results)}")
    print(f"Cache hits    : {len(cache_hits):3d}  ({100*len(cache_hits)//len(results)}%)")
    print(f"Easy misses   : {len(easy_misses):3d}  ({100*len(easy_misses)//len(results)}%)")
    print(f"Hard misses   : {len(hard_misses):3d}  ({100*len(hard_misses)//len(results)}%)")
    if no_cred_misses:
        print(f"Hard miss 402 : {len(no_cred_misses):3d}  (no credential)")
    print(f"Validator rej : {len(validator_rejects):3d}")
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
nohup /Users/jonathansheffer/Desktop/Coding/DejaQ/server/.venv/bin/python /tmp/dejaq_load_test.py > /tmp/dejaq_load_test_console.log 2>&1 &
```

### 8. Report to user

Show the final summary. Tell the user:
- The live report is at `evals/load-test-reports/<dept-slug>.md` (open in any markdown viewer)
- Number of threads, total turns
- Cache hit rate, easy miss rate, hard miss rate
- Number of validator rejections (near-hits demoted to misses by the cache-answer validator)
- Number of 402 hard-miss turns if any (indicates missing provider credential)
- Any remaining errors

### 9. Offer another run

After reporting the results, always ask:

> "Want me to run another test with the same persona? I'll reuse the same department
> (`<dept-slug>`) so Run 2 hits the warm cache from Run 1 — great for measuring
> how cache hit rate evolves."

If the user says yes:
- Keep the same `DEPT_SLUG` and `REPORT_PATH` (same cache namespace + same report file).
- Generate a fresh `CONVERSATIONS` list — same topics and mix, but different phrasing. This
  tests whether the cache generalizes to paraphrases rather than just replaying the exact same prompts.
- Write a new `/tmp/dejaq_load_test.py`. The script auto-detects the run number from the
  existing report — no manual change needed.
- Tell the user to run the same `nohup` command as before.

After Run 2+ completes, the report gets a **Combined Summary** table inserted near the top
comparing all runs side by side (cache hit %, easy/hard miss %, validator rejections, latency avg).

**Interpreting validator rejections:**
- `dist ~0.0000` = normalizer garbled the stored key (e.g. `segfault` stored as `default`,
  `sizeof` as `size`). Validator is **correctly** rejecting — cached answer was stored
  against a corrupted query. Root cause: spell-corrector mangles technical vocabulary.
- `dist 0.01–0.10` = validator overly conservative on close paraphrases; cached answer likely
  would have worked. This is a validator calibration issue.
- Cascading `Server disconnected` on Turn N+1 after error on Turn N = Ollama OOM/timeout.
  History is reset on error so cascade stops after one additional turn.
