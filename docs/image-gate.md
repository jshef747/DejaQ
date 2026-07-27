# Image gate — evidence and threshold rationale

The shipped rule is in `CLAUDE.md`; this file holds the measurements behind it. Implementation: `server/app/services/image_text.py` (documents) and `server/app/services/image_fingerprint.py` (photos). Harness: [evals/image_similarity/](../evals/image_similarity/).

## Two paths, because one signal cannot do both

An image is compared **by its words if OCR finds confident text, otherwise by its pixels**. This is not a preference — pixel similarity is measurably *inverted* for documents:

| | CLIP | dHash hamming | pixel gate would… |
|---|---|---|---|
| **Same** syllabus, two screenshots | 0.089 ✅ | 10–19 ❌ | **miss** (wrong) |
| **Different courses**, same template | **0.027** ✅ | **0** ✅ | **serve** (wrong, and dangerous) |

Two different courses (142180 Complex Analysis, 142241 Cloud/AWS) scored *closer together* than two screenshots of one document. A template document is ~95% identical boilerplate; the few words that distinguish it are invisible to any whole-image measure.

dHash cannot be rescued by resolution — at every size the same document scored **worse** than two genuinely different photos:

| hash size | same syllabus | two different photos |
|---|---|---|
| 8×8 | 15.6% bits differ | **12.5%** |
| 16×16 | 24.2% | **19.9%** |
| 32×32 | 39.9% | **33.7%** |

A magnitude-preserving grayscale comparison failed the same way (0.62 same-document vs 0.25 different-photo).

## Routing: OCR confidence, not pixel statistics

A pixel-based "is this a document?" detector was tried and **rejected**: a real photo of a screen full of text measured 0.3% near-white and saturation 8.3 — statistically a photo — yet contained 155 readable words. The OCR result itself is the classifier.

Both criteria must hold (`mean confidence ≥ 60` **and** `≥ 6 words at conf ≥ 60`). The
original table below was built against a floor of 80 and 45 words:

| group | mean confidence | confident words |
|---|---|---|
| Documents (4 rendered pages + close photo of a screen) | **83.3 – 92.2** | **54 – 373** |
| Unreadable photos of screens (far/angled) | 34.6 – 45.2 | 1 – 60 |
| Real photos (12 sampled) | 0 – 93.6 | **0 – 38** |

An unreadable screen photo reached 60 confident words but only ~35 confidence; the wordiest real photo reached 87.7 confidence but only 38 words.

### Both routing floors were set too high, and both cost real misses

The confidence floor of 80 sat **inside** the range real screenshots produce. One user's
images measured 86.8, 84.8, 80.5 and 77.5 — so whether a screenshot was cacheable at all came
down to OCR noise. At 77.5 it was refused on every request.

Swept 50–80 over both corpora: **0 false merges at every level**. The floor does not carry
safety — the 0.80 token threshold does — it only routes. Lowering it moves images from
"refused entirely" into "compared by words", which measured zero merges.

The cost is photo recall: of 480 real photo files, 42 route to the document path at a floor of
80 and 69 at 60, and those lose pixel matching. The worst overlap between any two of them is
**0.041** at every level, so they cannot merge — they simply miss. Documents are the workload
that matters here, so the trade favours them. Floor is now **60**.

### The word floor was 45, then 25, and it cost real misses

A **cropped exercise snippet** — two lines of a Hebrew complexity-theory question — OCR'd to **34 words at 84.8 confidence**. Confident, unambiguously a document, but under the 45-word floor, so it fell to the photo path and missed at **hamming 36** — while its token overlap with a re-cropped upload of the same snippet was **0.833**. Cropped snippets are a normal way to ask about a worksheet, so this was a whole class of misses.

Swept the floor over the 60 real photos (conf floor held at 80):

| word floor | photos routed to the document path | false merges among them | max cross-photo token overlap |
|---|---|---|---|
| 20 – 35 | 5 / 60 | **0** | 0.038 |
| 40 – 45 | 4 / 60 | **0** | 0.038 |

The **confidence floor does nearly all the filtering** — dropping the word floor from 45 to 25 misroutes exactly one extra photo (src032, the 38-word one above), and no floor produces a false merge: the worst cross-photo overlap is 0.038 against a 0.35 threshold, a ~10× margin. The cost is that src032's variants split across kinds (`logo` 23 words, `resized` 9, `rot3` 21 stay photos while the rest become documents), losing some of that one photo's own recall. A lost hit, never a wrong answer.

Note the three text-heavy photos that route to the document path at *any* floor (92–198 words, conf 80–86) are photos **of documents** — the routing is correct, not a misclassification.

## Document matching: one threshold at 0.80

**Serve when OCR token overlap ≥ 0.80.** Nothing else — no identifier rule, no zones.

That number is the measured zero-false-merge point. Swept over **69,411 pairs of genuinely
different documents**, the highest overlap any of them reached was **0.798**: two exam papers
for the same course, same lecturer, same semester, differing only by a date, a time and one
letter. The threshold sits immediately above the worst case the evidence contains.

### What this replaced, and why

The previous rule (token ≥ 0.35 AND digit-token ≥ 0.30, with 0.70 as a no-digit fallback) was
derived from **three syllabi**. Measured properly it produced **234 false merges**. A joint
sweep of all three parameters found that **every configuration retaining the digit rule
admitted merges**; the only clean point was a single threshold with the middle zone always
rejecting.

The digit rule failed three separate ways:

1. It cost **10.7 points of recall** for no safety gain.
2. It fired on OCR junk. A mangled formula (`E[time_M(x)] ≤ p(|x|)`) produced the
   "identifiers" `קאס6ר` and `6087`, which agreed on nothing and vetoed a **true** match at
   0.736 overlap — a photo of a screen and a screenshot of the same homework question.
3. On real receipts it was actively harmful: a document's numbers are a bag of many values,
   and OCR captures a different subset in each photo.

### The cost, stated plainly

| threshold | round 1 (coursework + DocUNet) | round 2 (forms + papers) |
|---|---|---|
| 0.70 | 77.9% recall / **114 merges** | 78.7% / 0 |
| 0.75 | 62.5% / 43 | 68.7% / 0 |
| **0.80** | **45.4% / 0** | **54.0% / 0** |
| 0.85 | 31.4% / 0 | 39.2% / 0 |

Round 2 is clean at every threshold — all the danger lives in documents sharing a template.
Recall of ~45–54% is the accepted trade: a miss costs one API call, a merge serves an answer
about a different document.

### Why not something smarter

Four approaches were measured against the same 286,000 labelled pairs
([evals/image_similarity/](../evals/image_similarity/)): word order, page layout, structured
field extraction, and noise-robust text. Three lost to the plain threshold. All four
converged on the same explanation — the difference between two near-duplicate documents is a
**small localised edit** (one word and a date in ~300 tokens), and every one of these methods
reduces a document pair to a single global ratio, in which that edit is indistinguishable from
ordinary OCR noise.

The structured-field veto did reach 90.6%, and is **deliberately not shipped**: it wins only
where documents share a template (round 1 coursework 50.4% → 98.5%) and *loses* where they do
not (round 2: 91.4% against the baseline's 97.3%). It also wrongly rejected 8 of 124 arXiv
v1/v2 pairs because the revision changed a date — it breaks any document that gets updated.

## The pixel fallback was the biggest leak of all

Bigger than the document rule ever was. An image whose OCR finds text but misses the document
bar used to fall through to CLIP+dHash, where two different pages of text look near-identical.
That produced **1,712 false merges** in round 1 and **204** in round 2.

It mattered so much because the routing bar is high relative to real-world scans:

| source | routed as "document" | median OCR confidence |
|---|---|---|
| clean PDF renders (arXiv) | 78% | 91.0 |
| **real scanned business forms (FUNSD)** | **11%** | **60.3** |

So 89% of genuine scanned forms took the unsafe path. The confidence floor of 80 was
calibrated on clean renders and does not describe real scans.

**Fix:** an image with ≥ `CACHE_IMAGE_AMBIGUOUS_MIN_WORDS` (4) tokens read *below* the
confidence floor is classified `ambiguous` — never served, never stored, no pixel fingerprint
computed. It becomes a cache miss, which regenerates.

The test is **OCR quality, not amount of text**, and getting that wrong caused a live
regression. The first version keyed on "below the document bar", which also caught a short
crop of a question — 9 words at 86.8 confidence, read perfectly — and made it permanently
un-cacheable. An unreliable read of a lot of text is garbage; a confident read of a little
text is a small document.

That also exposed the word floor as dead weight. Swept 6/8/10/15/25 over both corpora: **0
false merges at every level**, with under a point of recall between them, because the
confidence floor does the separating. On 60 real photos a floor of 6 reclassifies only 2, and
the worst overlap between any two text-bearing photos is 0.038 against a 0.80 threshold. The
floor has been 45, then 25, now **6**; each reduction fixed real misses and cost nothing
measurable.

A minimum of `CACHE_IMAGE_TEXT_MIN_SHARED_TOKENS` (4) shared tokens is also required before an
overlap ratio counts at all — two images with three tokens each that happen to share them
would otherwise score a perfect 1.0. No such pair appears in the corpora; this guards an edge
the data does not cover.

Separately, near-uniform images (a mostly-blank page is a white rectangle, and CLIP sees all
white rectangles as identical) are refused by `tile_variety()`: distinct dHashes over a 4×4
grid, floor 10. Measured, 60 real photos scored 13–16 while the merging blank renders scored
below 10.

> **Correction to an earlier claim in this document.** The near-blank guard was described as
> costing nothing. It blocks 0 of 60 real photos — that part holds — but its recall cost on the
> pixel path was never measured at the time. On round 1 it reduces served pixel-path pairs from
> 316 to 32, and on round 2 it removes only 7 of 204 merges, because scanned forms are not
> blank, they merely look alike. The ambiguous-image rule, not this guard, is what closes the
> leak.

## Photo matching: why both thresholds stay load-bearing

For photos the CLIP + dHash gate is unchanged and validated on 480 labeled images (86,730 cross-pairs): **0 false merges**, with per-variant acceptance of 100% (brightness), 100% (logo), 100% (resize), 98.3% (recompress), 95% (crop), 76.7% (rotation).

There is no unguarded trusted tier: the closest genuinely-*different* photo pair sits at CLIP ~0.048, well inside any usable CLIP ceiling, so dHash gates every photo hit (~0.24 ms, deterministic).

A proposed "structural tier" — accept strong dHash agreement (hamming ≤ 10) under a looser CLIP ceiling — was measured and **rejected**: 39 false accepts. dHash degenerates on low-structure images; two unrelated 4K photos with a left-right brightness split each hash to a repeating `0f0f…` and land at hamming 8.

## Rejected: trimming blank borders

`trim_border()` was implemented and then **removed**. Its entire benefit came from a synthetic "padded" variant added to the eval set; on realistic variants it was neutral to harmful:

| variant | no trim | trim |
|---|---|---|
| pad (synthetic) | 15% | 98.3% |
| logo | **100%** | 98.3% |
| all realistic variants | **96.1%** | 95.8% |

It also could not fix the real case it was written for: on the actual screenshots it made hamming *worse* (10 → 14), because their content sits at different scales and offsets. Re-framed documents are handled by OCR instead.

## Known limits, by design

- **Far or angled photos of a screen never match** — OCR returns garbage (the same document scored 0.000 against itself). They fail as a cache *miss*, which regenerates, never as a false merge.
- Heavy photo edits (print/scan, paint, blur, rotation) fail the photo gate and become a miss.
- A photo never matches a document entry and vice-versa; a text request matches neither.
- Hebrew OCR quality drives document results; Tesseract `heb` is strong on clean renders, poor on skewed photos.
- **Latency:** OCR adds ~0.3 s (sparse page) to ~1.9 s (dense page or photo) versus 0.24 ms for the photo gate. Accepted against a rejected 4.5 s VLM-caption alternative and the external-provider call that a miss triggers anyway.

## Three storage bugs found in production logs (fixed)

The first two were found while investigating a wrong cached answer, and neither was in the gate itself — the gate matched the correct image; the *stored text* was already wrong. The third explains why images kept missing even once the gate was right.

1. **Errored generations were cached.** A request logged `route=error model=error store=queued`: generation failed, the user got the apology text, and that apology was stored as a real answer with an image fingerprint attached, ready to be served to every later match. Now `route == "error"` skips the store entirely (`tests/test_cache_store_guards.py`).

2. **Image answers were passed through the generalizer.** `generalize()` strips tone so a *text* answer survives rephrasing, but it only ever sees the answer — never the image — so on image answers it invents specifics. Observed live: an answer about the **Complex Analysis** syllabus was stored as *"(Statistics or Data Analysis Course)"*. Image-anchored answers are now stored verbatim; the image gate already pins the answer to one image, so there is nothing to generalize across and the rewrite was pure risk. Text answers still generalize as before.

3. **Image requests were never stored at all.** The cache filter drops queries under 3 words as "too short" — but with an image attached the text is not the query. `"solve it"` (2 words) is the *normal* way to ask about an image, so every image request logged `store=skipped`, no entry was ever written, and a perfectly correct gate produced an endless run of misses. Image requests now bypass the text-length rules (`cache_filter.should_cache(..., has_image=True)`); the fingerprint guard that follows still refuses to store an image it cannot fingerprint, so a thin query can never leak an entry to an unrelated ask.

> Note: the generalizer's few-shot examples contain "Paris … the capital of France". That made few-shot leakage a suspect for an unrelated France-flavoured answer, but three reproduction runs on a syllabus answer showed **no leakage**, so it remains unconfirmed.

## Serving an image hit: three blind models, one family of bugs

The gate proves *same image*. Everything downstream is text-only and **cannot see the image**, so each stage that reasons about the answer was wrong in the same way:

| stage | what it was asked | outcome |
|---|---|---|
| generalizer (store) | rewrite this answer | invented "Statistics or Data Analysis Course" — **fixed**, stored verbatim |
| validator (serve) | does this ANSWER cover this QUESTION? | rejected `how to solve?` against `how to solve this?` at distance 0.0753 — **fixed**, see below |
| adjuster (serve) | rewrite this answer in the question's tone | same blind rewrite; nothing was generalized away to restore — **fixed**, skipped |

**Image hits now validate question-vs-question.** The cached answer is not sent at all; the validator is asked only whether the two questions ask for the same thing about the (already-verified identical) image. `_IMAGE_SYSTEM_PROMPT` / `_IMAGE_FEW_SHOTS` in `services/validator.py`.

The embedding cannot do this job alone — the two distance ranges **overlap**:

| class | BGE distance range | tier |
|---|---|---|
| paraphrases (must hit) | 0.0753 – 0.1094 | all trusted |
| numbered-item siblings (must miss) | **0.0867** – 0.1351 | all trusted |

`solve q1`/`solve q2` (0.0867) and `solve part a`/`solve part b` (0.0898) sit *closer together* than the legitimate paraphrase `what is this document about?`/`what is the topic of this document?` (0.1094). No threshold separates them; BGE treats `1`/`2`/`a`/`b` as near-interchangeable. Lowering the trusted ceiling would kill real hits and still serve the worksheet. The closest sibling (0.0867) is above `VALIDATOR_SKIP_DISTANCE` (0.05), so none of them bypasses the validator.

Measured on `gemma4:e2b` (`evals/validator/scripts/image_intent_check.py`, 25 pairs):

| | result |
|---|---|
| paraphrases served | **9/9** |
| siblings rejected | **15/16**, 0 of them reachable by the cache |
| validator latency | **577 ms median** (was 6,468 ms in answer mode) |
| hit latency end-to-end | ~1 s (was **9,490 ms** — slower than the 6,261 ms miss it replaced) |

The single miss is `what does this say?` vs `translate this to english` at distance **0.2497** — past `DEJAQ_CACHE_BAND_MAX_DISTANCE` (0.20), so the validator is never called on it in production. Worth recording anyway: that pair is a **verbatim few-shot** in the prompt and the model still answered VALID, which is a fair measure of how much `gemma4:e2b` can be pushed on read-vs-translate. Reachable phrasings of the same trap (`transcribe`/`translate` 0.1603, `what is written here?`/`translate what is written here` 0.1359) are rejected only after the prompt gained an explicit containment rule: extra words about *tone or depth* keep it VALID, extra words changing *output language or form* make it INVALID.

## What the evidence does not cover

The thresholds above rest on 286,000 labelled pairs across two corpora, re-derivable with
`evals/image_similarity/protocol.py`. Three gaps remain, and they are real:

- **Photos of screens are barely covered.** Every measured image is a render, a scan, or a
  photo of *paper*. The case that prompted this work — photographing a laptop screen — rests
  on a handful of examples. No public dataset supplies it, least of all in Hebrew.
- **Round 2 is English.** Tesseract's Hebrew behaviour differs, and the Hebrew evidence comes
  from one person's coursework.
- **Renders stand in for re-screenshotting**, not for re-photographing. Rasterising a page at
  a different DPI is a genuinely independent render, but it does not reproduce perspective,
  glare or moiré.

An earlier version of this document derived the document thresholds from **three syllabi** and
described the resulting separation as roughly 10×. Measured against a proper corpus, that rule
turned out to produce 234 false merges. Treat any number here as provisional until it has been
swept over a corpus that contains the failure mode you care about.

## Cache threshold rationale (text path)

- **`DEJAQ_CACHE_BAND_MAX_DISTANCE` = 0.20** is the empirically safe ceiling. The validator's first false-accept appears at ~0.21, where sibling questions (freezing/boiling, hamlet/macbeth) cluster with heavier typos. Set it at or below `DEJAQ_CACHE_TRUST_DISTANCE` to disable the band; raise it only alongside a stronger validator.
- **`DEJAQ_CACHE_RESCUE_MAX_DISTANCE` = 0.60** — the heaviest real typo observed live sits at 0.52.
- **`DEJAQ_VALIDATOR_SKIP_DISTANCE` = 0.05** — at this distance the embedding already guarantees correctness, so the validator adds latency and no safety.
