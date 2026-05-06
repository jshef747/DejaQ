# DejaQ Load Test Report

**Persona:** Dunder Mifflin office employees (The Office)  
**Department:** `dunder-mifflin-office-employees-20260506`  
**Updated:** 2026-05-06 12:29:57  
**Status:** ✅ Complete  

## Summary

| Metric | Value |
|--------|-------|
| Total turns | 58 |
| ✅ Cache hits | 0 (0%) |
| 🟡 Easy misses (local LLM) | 0 (0%) |
| 🔴 Hard misses (external LLM) | 26 (44%) |
| ❌ Errors | 32 |
| Latency p50 | 26607 ms |
| Latency p95 | 114290 ms |
| Latency p99 | 123566 ms |
| Latency avg | 36900 ms |

## Conversations

### Thread 1 — A potential client said our paper is 'basically the same as …

| Turn | Type | Latency (ms) | Difficulty | Score | Model | Prompt | Cache match |
|------|------|-------------|------------|-------|-------|--------|-------------|
| 1 | 🔴 HARD MISS | 21872 | easy | 0.22 | gemma-4-e4b | <details><summary>A potential client said our paper is 'basically the same as …</summary>A potential client said our paper is 'basically the same as Staples' and hung up. What's the best way to differentiate commodity office paper in a sales call when the prospect thinks it's all the same product?</details> | — |
| 2 | 🔴 HARD MISS | 27404 | easy | 0.19 | gemma-4-e4b | <details><summary>You mentioned lead time and reliability as differentiators. …</summary>You mentioned lead time and reliability as differentiators. Our warehouse has had two late deliveries this month — how do I handle that objection if the client brings it up before I can fix the fulfillment issue?</details> | — |
| 3 | 🔴 HARD MISS | 89112 | easy | 0.18 | gemma-4-e4b | <details><summary>That's helpful. If a prospect says they'll think about it an…</summary>That's helpful. If a prospect says they'll think about it and calls back in three weeks, what follow-up cadence should I use without being annoying?</details> | — |

### Thread 2 — My coworker keeps taking credit for my ideas in meetings in …

| Turn | Type | Latency (ms) | Difficulty | Score | Model | Prompt | Cache match |
|------|------|-------------|------------|-------|-------|--------|-------------|
| 1 | 🔴 HARD MISS | 26604 | easy | 0.17 | gemma-4-e4b | <details><summary>My coworker keeps taking credit for my ideas in meetings in …</summary>My coworker keeps taking credit for my ideas in meetings in front of our manager. I've tried addressing it one-on-one and it hasn't changed — what should I do next without making the whole office awkward?</details> | — |
| 2 | 🔴 HARD MISS | 38536 | easy | 0.15 | gemma-4-e4b | <details><summary>You suggested documenting contributions with timestamps befo…</summary>You suggested documenting contributions with timestamps before meetings. Is there a professional way to actually send those notes to my manager without looking like I'm tattling?</details> | — |

### Thread 3 — We're at 67% of our quarterly paper sales target with three …

| Turn | Type | Latency (ms) | Difficulty | Score | Model | Prompt | Cache match |
|------|------|-------------|------------|-------|-------|--------|-------------|
| 1 | 🔴 HARD MISS | 12662 | easy | 0.15 | gemma-4-e4b | <details><summary>We're at 67% of our quarterly paper sales target with three …</summary>We're at 67% of our quarterly paper sales target with three weeks left and our biggest account just cut their order by 40%. What are realistic tactics to close the gap without just cold-calling 200 people?</details> | — |
| 2 | 🔴 HARD MISS | 15159 | easy | 0.17 | gemma-4-e4b | <details><summary>You mentioned reactivating lapsed accounts. How do I find ou…</summary>You mentioned reactivating lapsed accounts. How do I find out which clients we had 18 months ago who stopped ordering — do I need to dig through old invoices manually or is there a smarter way?</details> | — |
| 3 | 🔴 HARD MISS | 30204 | easy | 0.19 | gemma-4-e4b | <details><summary>Found 12 lapsed accounts. What's a good opening line for a r…</summary>Found 12 lapsed accounts. What's a good opening line for a reactivation email that doesn't sound like a generic spam blast?</details> | — |
| 4 | 🔴 HARD MISS | 29204 | easy | 0.10 | gemma-4-e4b | <details><summary>One of those accounts said they left because a salesperson w…</summary>One of those accounts said they left because a salesperson was 'too pushy.' How do I rebuild trust on the first call without underselling?</details> | — |

### Thread 4 — I need to expense a client dinner that cost $340 but our pol…

| Turn | Type | Latency (ms) | Difficulty | Score | Model | Prompt | Cache match |
|------|------|-------------|------------|-------|-------|--------|-------------|
| 1 | 🔴 HARD MISS | 7559 | easy | 0.13 | gemma-4-e4b | <details><summary>I need to expense a client dinner that cost $340 but our pol…</summary>I need to expense a client dinner that cost $340 but our policy says the limit is $75 per person and there were 4 people. The math works out but HR is flagging it anyway — what's going on?</details> | — |
| 2 | 🔴 HARD MISS | 20510 | easy | 0.16 | gemma-4-e4b | <details><summary>HR said the system calculates per-receipt not per-person. Is…</summary>HR said the system calculates per-receipt not per-person. Is there a standard way to split a restaurant receipt across multiple expense line items to satisfy that kind of policy?</details> | — |

### Thread 5 — I'm planning the office holiday party and my budget is $800 …

| Turn | Type | Latency (ms) | Difficulty | Score | Model | Prompt | Cache match |
|------|------|-------------|------------|-------|-------|--------|-------------|
| 1 | 🔴 HARD MISS | 15928 | easy | 0.16 | gemma-4-e4b | <details><summary>I'm planning the office holiday party and my budget is $800 …</summary>I'm planning the office holiday party and my budget is $800 for 22 people. Last year it was awkward because half the team left early. What makes office parties actually enjoyable so people want to stay?</details> | — |
| 2 | 🔴 HARD MISS | 26607 | easy | 0.23 | gemma-4-e4b | <details><summary>You suggested activity-based parties over just food and drin…</summary>You suggested activity-based parties over just food and drinks. What are some low-cost activities that work for a mixed group of introverts and extroverts in a conference room?</details> | — |
| 3 | 🔴 HARD MISS | 31520 | easy | 0.18 | gemma-4-e4b | <details><summary>What's a realistic per-person food budget that leaves enough…</summary>What's a realistic per-person food budget that leaves enough for activities without making the food feel sad?</details> | — |

### Thread 6 — My annual review is next week and I've been at the company f…

| Turn | Type | Latency (ms) | Difficulty | Score | Model | Prompt | Cache match |
|------|------|-------------|------------|-------|-------|--------|-------------|
| 1 | 🔴 HARD MISS | 12739 | easy | 0.13 | gemma-4-e4b | <details><summary>My annual review is next week and I've been at the company f…</summary>My annual review is next week and I've been at the company four years without a raise. I have a competing offer for 18% more but I'd rather stay — how do I use that in the negotiation without it backfiring?</details> | — |
| 2 | 🔴 HARD MISS | 94661 | easy | 0.13 | gemma-4-e4b | <details><summary>You mentioned framing it as a market data point rather than …</summary>You mentioned framing it as a market data point rather than an ultimatum. What if my manager says 'we can't match that' — should I take the other offer or try to negotiate non-salary benefits?</details> | — |
| 3 | 🔴 HARD MISS | 75812 | easy | 0.15 | gemma-4-e4b | <details><summary>What non-salary benefits are actually worth negotiating for …</summary>What non-salary benefits are actually worth negotiating for versus ones that sound good but rarely get approved?</details> | — |

### Thread 7 — The office printer keeps jamming on the second tray even aft…

| Turn | Type | Latency (ms) | Difficulty | Score | Model | Prompt | Cache match |
|------|------|-------------|------------|-------|-------|--------|-------------|
| 1 | 🔴 HARD MISS | 8578 | easy | 0.17 | gemma-4-e4b | <details><summary>The office printer keeps jamming on the second tray even aft…</summary>The office printer keeps jamming on the second tray even after I cleared the jam three times and reloaded the paper. It's a Brother HL-L8360CDW. What am I probably missing?</details> | — |
| 2 | 🔴 HARD MISS | 13931 | easy | 0.15 | gemma-4-e4b | <details><summary>You mentioned the paper humidity issue. Our supply closet is…</summary>You mentioned the paper humidity issue. Our supply closet is next to the bathroom — is that actually causing this or is that a stretch?</details> | — |

### Thread 8 — I've been making 40 cold calls a day but my conversion to bo…

| Turn | Type | Latency (ms) | Difficulty | Score | Model | Prompt | Cache match |
|------|------|-------------|------------|-------|-------|--------|-------------|
| 1 | 🔴 HARD MISS | 21641 | easy | 0.12 | gemma-4-e4b | <details><summary>I've been making 40 cold calls a day but my conversion to bo…</summary>I've been making 40 cold calls a day but my conversion to booked meeting rate is under 2%. My opening line is 'Hi, is this a good time?' — what am I doing wrong?</details> | — |
| 2 | 🔴 HARD MISS | 28455 | easy | 0.28 | gemma-4-e4b | <details><summary>You said to lead with a specific reason for calling. Can you…</summary>You said to lead with a specific reason for calling. Can you give me three example openers for selling office paper that don't sound like every other sales call?</details> | — |
| 3 | 🔴 HARD MISS | 114290 | easy | 0.11 | gemma-4-e4b | <details><summary>The third example is interesting — how do I find out what a …</summary>The third example is interesting — how do I find out what a prospect's current paper supplier is before I call them?</details> | — |
| 4 | 🔴 HARD MISS | 47110 | easy | 0.14 | gemma-4-e4b | <details><summary>That LinkedIn approach you mentioned — is there a way to do …</summary>That LinkedIn approach you mentioned — is there a way to do that at scale without spending 20 minutes researching each prospect?</details> | — |

### Thread 9 — A client called to complain that a ream of paper they got wa…

| Turn | Type | Latency (ms) | Difficulty | Score | Model | Prompt | Cache match |
|------|------|-------------|------------|-------|-------|--------|-------------|
| 1 | 🔴 HARD MISS | 8253 | easy | 0.11 | gemma-4-e4b | <details><summary>A client called to complain that a ream of paper they got wa…</summary>A client called to complain that a ream of paper they got was the wrong weight — we sent 20lb when they ordered 24lb. They want a credit and a replacement. What's the right process for handling this?</details> | — |
| 2 | 🔴 HARD MISS | 17483 | easy | 0.15 | gemma-4-e4b | <details><summary>Our system shows the order was correct on our end but their …</summary>Our system shows the order was correct on our end but their invoice says 24lb. If it was a warehouse error, should I tell them that or just fix it without explaining?</details> | — |

### Thread 10 — Our weekly sales team meeting runs 90 minutes and nobody lea…

| Turn | Type | Latency (ms) | Difficulty | Score | Model | Prompt | Cache match |
|------|------|-------------|------------|-------|-------|--------|-------------|
| 1 | 🔴 HARD MISS | 123566 | easy | 0.18 | gemma-4-e4b | <details><summary>Our weekly sales team meeting runs 90 minutes and nobody lea…</summary>Our weekly sales team meeting runs 90 minutes and nobody leaves feeling like anything was decided. How do I fix this without being the person who complains about meetings?</details> | — |
| 2 | ❌ ERROR | — | — | — | — | <details><summary>You suggested a written agenda sent 24 hours before. Our man…</summary>You suggested a written agenda sent 24 hours before. Our manager never prepares one — how do I get them to adopt that without stepping on their toes?</details> | — |
| 3 | ❌ ERROR | — | — | — | — | <details><summary>What's a good format for a sales team meeting agenda that ke…</summary>What's a good format for a sales team meeting agenda that keeps things moving without feeling like a drill?</details> | — |

### Thread 11 — We keep running out of legal-size paper but always have too …

| Turn | Type | Latency (ms) | Difficulty | Score | Model | Prompt | Cache match |
|------|------|-------------|------------|-------|-------|--------|-------------|
| 1 | ❌ ERROR | — | — | — | — | <details><summary>We keep running out of legal-size paper but always have too …</summary>We keep running out of legal-size paper but always have too much letter-size. I don't have inventory software — how should I track this with what I already have?</details> | — |
| 2 | ❌ ERROR | — | — | — | — | <details><summary>You suggested a simple spreadsheet with reorder points. What…</summary>You suggested a simple spreadsheet with reorder points. What's a reasonable reorder point formula for paper stock given that our lead time from the warehouse is 3 business days?</details> | — |

### Thread 12 — My manager checks in on me five times a day and asks for upd…

| Turn | Type | Latency (ms) | Difficulty | Score | Model | Prompt | Cache match |
|------|------|-------------|------------|-------|-------|--------|-------------|
| 1 | ❌ ERROR | — | — | — | — | <details><summary>My manager checks in on me five times a day and asks for upd…</summary>My manager checks in on me five times a day and asks for updates on things I sent him an email about that morning. It's disrupting my workflow. What's a professional way to reduce the check-ins?</details> | — |
| 2 | ❌ ERROR | — | — | — | — | <details><summary>You mentioned proactive status updates as a way to reduce ch…</summary>You mentioned proactive status updates as a way to reduce check-ins. What's the right frequency and format so it actually builds trust instead of creating more work for me?</details> | — |
| 3 | ❌ ERROR | — | — | — | — | <details><summary>What if he still checks in after I've been doing the updates…</summary>What if he still checks in after I've been doing the updates for two weeks? At what point is it appropriate to bring this up directly?</details> | — |

### Thread 13 — Our branch has to submit monthly sales reports to corporate …

| Turn | Type | Latency (ms) | Difficulty | Score | Model | Prompt | Cache match |
|------|------|-------------|------------|-------|-------|--------|-------------|
| 1 | ❌ ERROR | — | — | — | — | <details><summary>Our branch has to submit monthly sales reports to corporate …</summary>Our branch has to submit monthly sales reports to corporate by the 5th but we always get the data late from our reps. What's the most effective way to enforce internal deadlines on a small team?</details> | — |
| 2 | ❌ ERROR | — | — | — | — | <details><summary>You mentioned social accountability as more effective than f…</summary>You mentioned social accountability as more effective than formal reminders. What does that actually look like in practice — do you mean making it visible on a shared screen or something else?</details> | — |

### Thread 14 — Our paper supplier just told us they're raising prices 8% ne…

| Turn | Type | Latency (ms) | Difficulty | Score | Model | Prompt | Cache match |
|------|------|-------------|------------|-------|-------|--------|-------------|
| 1 | ❌ ERROR | — | — | — | — | <details><summary>Our paper supplier just told us they're raising prices 8% ne…</summary>Our paper supplier just told us they're raising prices 8% next quarter due to pulp costs. We buy about $180k annually from them. How should I approach the negotiation to keep the increase as low as possible?</details> | — |
| 2 | ❌ ERROR | — | — | — | — | <details><summary>You suggested committing to a longer contract in exchange fo…</summary>You suggested committing to a longer contract in exchange for a price cap. What contract length is typically a good trade-off — does locking in for two years usually get a meaningful discount?</details> | — |
| 3 | ❌ ERROR | — | — | — | — | <details><summary>What if they won't budge on price at all? Are there other co…</summary>What if they won't budge on price at all? Are there other concessions worth asking for that still improve our position?</details> | — |

### Thread 15 — I'm training a new sales rep who's never done B2B sales befo…

| Turn | Type | Latency (ms) | Difficulty | Score | Model | Prompt | Cache match |
|------|------|-------------|------------|-------|-------|--------|-------------|
| 1 | ❌ ERROR | — | — | — | — | <details><summary>I'm training a new sales rep who's never done B2B sales befo…</summary>I'm training a new sales rep who's never done B2B sales before. They're enthusiastic but freeze up on objections. What's the fastest way to get someone comfortable with objection handling?</details> | — |
| 2 | ❌ ERROR | — | — | — | — | <details><summary>You mentioned role-playing as the best method. What's a good…</summary>You mentioned role-playing as the best method. What's a good way to structure a 30-minute daily role-play session that doesn't feel like a punishment?</details> | — |
| 3 | ❌ ERROR | — | — | — | — | <details><summary>How do I give critical feedback after a role-play session wi…</summary>How do I give critical feedback after a role-play session without demoralizing them?</details> | — |

### Thread 16 — I ordered printer toner last Tuesday and the system shows it…

| Turn | Type | Latency (ms) | Difficulty | Score | Model | Prompt | Cache match |
|------|------|-------------|------------|-------|-------|--------|-------------|
| 1 | ❌ ERROR | — | — | — | — | <details><summary>I ordered printer toner last Tuesday and the system shows it…</summary>I ordered printer toner last Tuesday and the system shows it was shipped but it hasn't arrived. It's been 6 business days. When should I escalate vs. just wait?</details> | — |
| 2 | ❌ ERROR | — | — | — | — | <details><summary>The tracking number shows 'in transit' with no updates for 4…</summary>The tracking number shows 'in transit' with no updates for 4 days. Is that normal for ground shipping or is something stuck?</details> | — |

### Thread 17 — We just lost Lackawanna County as a client — they switched t…

| Turn | Type | Latency (ms) | Difficulty | Score | Model | Prompt | Cache match |
|------|------|-------------|------------|-------|-------|--------|-------------|
| 1 | ❌ ERROR | — | — | — | — | <details><summary>We just lost Lackawanna County as a client — they switched t…</summary>We just lost Lackawanna County as a client — they switched to a competitor after 6 years with us. My manager wants a post-mortem. What should a good post-mortem include to actually prevent this from happening again?</details> | — |
| 2 | ❌ ERROR | — | — | — | — | <details><summary>One finding was that we hadn't called them in 8 months befor…</summary>One finding was that we hadn't called them in 8 months before the switch. How do I set up a simple touchpoint cadence for our top 20 accounts so this doesn't happen again?</details> | — |

### Thread 18 — Our Salesforce data is a mess — duplicate accounts, phone nu…

| Turn | Type | Latency (ms) | Difficulty | Score | Model | Prompt | Cache match |
|------|------|-------------|------------|-------|-------|--------|-------------|
| 1 | ❌ ERROR | — | — | — | — | <details><summary>Our Salesforce data is a mess — duplicate accounts, phone nu…</summary>Our Salesforce data is a mess — duplicate accounts, phone numbers that go to fax machines, contacts who left companies two years ago. I have to clean it up but there's no budget for a tool. What's the fastest manual approach?</details> | — |
| 2 | ❌ ERROR | — | — | — | — | <details><summary>You suggested deduplication by domain first. How do I do tha…</summary>You suggested deduplication by domain first. How do I do that in Salesforce without a third-party dedup tool — is there a native report I can run?</details> | — |
| 3 | ❌ ERROR | — | — | — | — | <details><summary>What's a realistic estimate for how long it takes to manuall…</summary>What's a realistic estimate for how long it takes to manually clean 800 account records if I'm doing it 30 minutes a day?</details> | — |

### Thread 19 — Someone keeps eating other people's labeled lunches in the b…

| Turn | Type | Latency (ms) | Difficulty | Score | Model | Prompt | Cache match |
|------|------|-------------|------------|-------|-------|--------|-------------|
| 1 | ❌ ERROR | — | — | — | — | <details><summary>Someone keeps eating other people's labeled lunches in the b…</summary>Someone keeps eating other people's labeled lunches in the break room and nobody admits to it. It's become a morale issue. How do you handle this kind of anonymous bad behavior at work professionally?</details> | — |
| 2 | ❌ ERROR | — | — | — | — | <details><summary>You mentioned a non-accusatory all-staff email. Can you writ…</summary>You mentioned a non-accusatory all-staff email. Can you write a draft that's firm but doesn't sound passive-aggressive?</details> | — |

### Thread 20 — It's late in the fiscal year and some clients are trying to …

| Turn | Type | Latency (ms) | Difficulty | Score | Model | Prompt | Cache match |
|------|------|-------------|------------|-------|-------|--------|-------------|
| 1 | ❌ ERROR | — | — | — | — | <details><summary>It's late in the fiscal year and some clients are trying to …</summary>It's late in the fiscal year and some clients are trying to use up remaining budget. How do I identify which of our accounts likely have unspent budget and proactively reach out before the quarter closes?</details> | — |
| 2 | ❌ ERROR | — | — | — | — | <details><summary>You mentioned asking directly as the most effective approach…</summary>You mentioned asking directly as the most effective approach. What's a good script for a 'year-end budget check-in' call that doesn't sound desperate?</details> | — |
| 3 | ❌ ERROR | — | — | — | — | <details><summary>If a client says they have $3,000 left but our minimum order…</summary>If a client says they have $3,000 left but our minimum order is $500, what products or bundles make sense to propose to hit that number efficiently?</details> | — |

### Thread 21 — My sales team hit their numbers for six straight months but …

| Turn | Type | Latency (ms) | Difficulty | Score | Model | Prompt | Cache match |
|------|------|-------------|------------|-------|-------|--------|-------------|
| 1 | ❌ ERROR | — | — | — | — | <details><summary>My sales team hit their numbers for six straight months but …</summary>My sales team hit their numbers for six straight months but morale has been dropping. People are showing up late and enthusiasm is clearly down. What causes burnout in sales teams even when they're performing?</details> | — |
| 2 | ❌ ERROR | — | — | — | — | <details><summary>You mentioned that recognition patterns matter as much as co…</summary>You mentioned that recognition patterns matter as much as compensation. What are low-cost recognition approaches that sales reps actually respond to versus ones that feel hollow?</details> | — |

### Thread 22 — I have to present our branch's Q2 results to the regional VP…

| Turn | Type | Latency (ms) | Difficulty | Score | Model | Prompt | Cache match |
|------|------|-------------|------------|-------|-------|--------|-------------|
| 1 | ❌ ERROR | — | — | — | — | <details><summary>I have to present our branch's Q2 results to the regional VP…</summary>I have to present our branch's Q2 results to the regional VP next Friday and our numbers are mixed — revenue is up 4% but margin is down due to a pricing experiment. How do I present bad news alongside good news without looking like I'm hiding the bad part?</details> | — |
| 2 | ❌ ERROR | — | — | — | — | <details><summary>You suggested leading with the business context before the n…</summary>You suggested leading with the business context before the numbers. What's the right slide count for a 15-minute executive presentation — is 10 slides too many?</details> | — |
| 3 | ❌ ERROR | — | — | — | — | <details><summary>How do I handle a question I don't know the answer to in the…</summary>How do I handle a question I don't know the answer to in the middle of a live presentation without losing credibility?</details> | — |

## Errors

- **Thread 10 Turn 2** — ``
- **Thread 10 Turn 3** — ``
- **Thread 11 Turn 1** — `[Errno 54] Connection reset by peer`
- **Thread 11 Turn 2** — `Cannot connect to host 127.0.0.1:8000 ssl:default [Connect call failed ('127.0.0.1', 8000)]`
- **Thread 12 Turn 1** — `Cannot connect to host 127.0.0.1:8000 ssl:default [Connect call failed ('127.0.0.1', 8000)]`
- **Thread 12 Turn 2** — `Cannot connect to host 127.0.0.1:8000 ssl:default [Connect call failed ('127.0.0.1', 8000)]`
- **Thread 12 Turn 3** — `Cannot connect to host 127.0.0.1:8000 ssl:default [Connect call failed ('127.0.0.1', 8000)]`
- **Thread 13 Turn 1** — `Cannot connect to host 127.0.0.1:8000 ssl:default [Connect call failed ('127.0.0.1', 8000)]`
- **Thread 13 Turn 2** — `Cannot connect to host 127.0.0.1:8000 ssl:default [Connect call failed ('127.0.0.1', 8000)]`
- **Thread 14 Turn 1** — `Cannot connect to host 127.0.0.1:8000 ssl:default [Connect call failed ('127.0.0.1', 8000)]`
- **Thread 14 Turn 2** — `Cannot connect to host 127.0.0.1:8000 ssl:default [Connect call failed ('127.0.0.1', 8000)]`
- **Thread 14 Turn 3** — `Cannot connect to host 127.0.0.1:8000 ssl:default [Connect call failed ('127.0.0.1', 8000)]`
- **Thread 15 Turn 1** — `Cannot connect to host 127.0.0.1:8000 ssl:default [Connect call failed ('127.0.0.1', 8000)]`
- **Thread 15 Turn 2** — `Cannot connect to host 127.0.0.1:8000 ssl:default [Connect call failed ('127.0.0.1', 8000)]`
- **Thread 15 Turn 3** — `Cannot connect to host 127.0.0.1:8000 ssl:default [Connect call failed ('127.0.0.1', 8000)]`
- **Thread 16 Turn 1** — `Cannot connect to host 127.0.0.1:8000 ssl:default [Connect call failed ('127.0.0.1', 8000)]`
- **Thread 16 Turn 2** — `Cannot connect to host 127.0.0.1:8000 ssl:default [Connect call failed ('127.0.0.1', 8000)]`
- **Thread 17 Turn 1** — `Cannot connect to host 127.0.0.1:8000 ssl:default [Connect call failed ('127.0.0.1', 8000)]`
- **Thread 17 Turn 2** — `Cannot connect to host 127.0.0.1:8000 ssl:default [Connect call failed ('127.0.0.1', 8000)]`
- **Thread 18 Turn 1** — `Cannot connect to host 127.0.0.1:8000 ssl:default [Connect call failed ('127.0.0.1', 8000)]`
- **Thread 18 Turn 2** — `Cannot connect to host 127.0.0.1:8000 ssl:default [Connect call failed ('127.0.0.1', 8000)]`
- **Thread 18 Turn 3** — `Cannot connect to host 127.0.0.1:8000 ssl:default [Connect call failed ('127.0.0.1', 8000)]`
- **Thread 19 Turn 1** — `Cannot connect to host 127.0.0.1:8000 ssl:default [Connect call failed ('127.0.0.1', 8000)]`
- **Thread 19 Turn 2** — `Cannot connect to host 127.0.0.1:8000 ssl:default [Connect call failed ('127.0.0.1', 8000)]`
- **Thread 20 Turn 1** — `Cannot connect to host 127.0.0.1:8000 ssl:default [Connect call failed ('127.0.0.1', 8000)]`
- **Thread 20 Turn 2** — `Cannot connect to host 127.0.0.1:8000 ssl:default [Connect call failed ('127.0.0.1', 8000)]`
- **Thread 20 Turn 3** — `Cannot connect to host 127.0.0.1:8000 ssl:default [Connect call failed ('127.0.0.1', 8000)]`
- **Thread 21 Turn 1** — `Cannot connect to host 127.0.0.1:8000 ssl:default [Connect call failed ('127.0.0.1', 8000)]`
- **Thread 21 Turn 2** — `Cannot connect to host 127.0.0.1:8000 ssl:default [Connect call failed ('127.0.0.1', 8000)]`
- **Thread 22 Turn 1** — `Cannot connect to host 127.0.0.1:8000 ssl:default [Connect call failed ('127.0.0.1', 8000)]`
- **Thread 22 Turn 2** — `Cannot connect to host 127.0.0.1:8000 ssl:default [Connect call failed ('127.0.0.1', 8000)]`
- **Thread 22 Turn 3** — `Cannot connect to host 127.0.0.1:8000 ssl:default [Connect call failed ('127.0.0.1', 8000)]`
