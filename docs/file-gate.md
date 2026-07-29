# File gate — why there is nothing to measure

This document exists mostly to explain an absence. [docs/image-gate.md](image-gate.md) is long because every constant in the image gate had to be swept over ~1.85M labelled pairs. The file gate has no such numbers, and that is the design, not an omission.

## The difference that removes the thresholds

The image gate approximates identity because **OCR output is noisy**. Two reads of the same page disagree on characters, so "is this the same document?" can only ever be answered as "are these similar enough?" — and *enough* is a number that has to be found empirically, defended against the population that breaks it, and re-derived whenever the corpus changes. That is where the 0.85 token-overlap threshold, the 0.08 CLIP ceiling, the hamming ceiling, and the confidence floors all come from.

A PDF or a Markdown file hands us the text **directly and deterministically**. The same bytes always extract the same characters. So:

| | image gate | file gate |
|---|---|---|
| identity | approximate (CLIP / dHash / token overlap) | exact (sha256 of normalised text) |
| decision | several thresholds, all swept | string equality |
| false merges | measured, non-zero, traded against recall | impossible by construction |
| tuning surface | 9 constants | none |
| eval harness | `evals/image_similarity/` | none needed |

There is no recall-versus-false-merge curve to plot, because the two are not in tension: the gate accepts exactly the same file and rejects everything else. Recall is lower than a fuzzy matcher would give (an edited PDF is a new document, and is treated as one), and that is the accepted trade — the same trade the image gate makes, just without having to be argued from data.

## What the gate actually does

1. Extract text — `pypdf` for PDF, UTF-8 decode for Markdown.
2. Normalise: collapse every whitespace run to a single space, trim. **Nothing else.** No case folding, no punctuation stripping, no header removal.
3. `sha256` the result. That string is the file's identity.
4. Serve a cached entry only when `request.sha == entry.file_sha` **and** the kinds agree.

Step 2 is the only place where a judgement is embedded, so it is worth stating what it buys and what it costs. It buys the "same document, different producer" case: a PDF re-saved by another tool commonly reflows line breaks and spacing while preserving every word, and without normalisation those would be two different documents. It costs nothing measurable, because it cannot merge two files that differ in any actual character.

Case folding was considered and rejected: the same file always extracts the same case, so folding buys nothing, and it could only ever merge two documents that genuinely differ.

## Files that cannot be identified are refused

If the normalised text is shorter than `DEJAQ_CACHE_FILE_MIN_CHARS` (200), the file is **never served and never stored**. The answer still comes back from the provider; there is simply no cache entry.

The population this catches is **scanned PDFs** — an image of a page has no text layer, so `pypdf` returns approximately nothing. This mirrors the image gate's `ambiguous` class and is the same reasoning: an attachment we cannot identify must not be guessed at. The image gate learned this the expensive way — routing unidentifiable text-bearing images to the pixel path produced 1,712 and 204 false merges on two measured corpora, because two different pages of text look near-identical to CLIP. The file gate declines to repeat it.

200 is not a tuned number. Anything from a few dozen upward behaves identically, because the populations it separates (0–2 characters from a scan, versus hundreds from a real document) are nowhere near the line. Raising it only refuses more short-but-real files.

Corrupt and encrypted PDFs land in the same bucket via the same rule: nothing extracted, no identity, not cached.

## Entry identity includes the file

`store_interaction` derives its entry id from `sha256(normalized_query)` for text entries and `sha256(normalized_query + "|file:" + file_sha)` when a file is attached.

The suffix is load-bearing. Without it, two **different** documents asked the **same** question share one id and silently overwrite each other — and "summarise this document" is precisely the question people ask about documents. Text entries keep their original ids, so nothing already cached moves.

## Serving a file hit

Identical to an image hit, for identical reasons — every model downstream is blind to the attachment:

- **The validator compares question-to-question.** The cached answer is never sent; the validator is asked only whether both questions ask for the same thing about the already-verified-identical file. (Shared with the image path as `attachment_anchored`.)
- **The context adjuster is skipped.** Attachment answers are stored verbatim, because the generalizer only sees the answer text and invents specifics for content it cannot read — measured on images, where a Complex Analysis syllabus was generalized into "Statistics or Data Analysis Course".

Note that the exact hash proves the *file* is the same; it says nothing about whether the two *questions* want the same thing. The validator remains load-bearing.

## Reaching the model

| | how it is sent |
|---|---|
| PDF | native document part — Google `Part.from_bytes(mime_type="application/pdf")`, Anthropic `document` block, OpenAI `file` part |
| Markdown | inlined into the prompt inside a `<<<ATTACHED DOCUMENT>>>` fence, explicitly labelled as data rather than instructions |

Markdown is inlined because no provider has a markdown part and it is already text. The fence is a trust boundary: the document is untrusted input from whoever uploaded it, and a file containing "ignore your instructions" must read as content.

Attachment content never enters the **cache key**. The enricher, normalizer, and embedding see only the user's question, exactly as with images — a 40-page document would produce a useless key and an enormous embedding.

## Deliberately absent

- **No `evals/document_similarity/` harness.** Nothing to sweep.
- **No `cache purge-files` command.** `purge-images` exists because image thresholds change and old entries carry fingerprints the new rules would reject. A sha256 cannot go stale that way. Add one only if `_normalize` itself ever changes.
- **No OCR fallback for scanned PDFs.** Rasterising pages and running them through the image gate would recover scanned documents at the cost of inheriting that gate's known leak (two FUNSD forms merge at CLIP 0.0648 / hamming 14). Heavy VLM parsers (MinerU, Marker, Docling, Baidu's Unlimited-OCR) solve this properly but put a multi-GB model in the hot path of a cache lookup, and Unlimited-OCR is CUDA-only. Revisit only when scanned documents become a requirement.
- **No per-page or per-chunk fingerprinting**, no multi-file requests, no file alias learning.

## Settings

| Setting | Default | Purpose |
|---|---|---|
| `DEJAQ_CACHE_FILE_ENABLED` | `true` | kill switch |
| `DEJAQ_CACHE_FILE_MIN_CHARS` | `200` | below this a file has no identity, so it is refused |
| `DEJAQ_MAX_ATTACHMENT_BYTES` | `10485760` | server-side size cap, applied to files **and** images |

## Reading the logs

Three lines, each answering one question. All prompt text respects `DEJAQ_LOG_SHOW_CONTENT`.

**Is this a document?**
```
file kind=pdf contract.pdf 842KB freshly-attached — extractable text (12,431 chars, sha=3f9a1c2e) | prompt=...
file kind=pdf contract.pdf 842KB carried-over — extractable text (12,431 chars, sha=3f9a1c2e) | prompt=...
file kind=pdf scan.pdf 3.1MB freshly-attached — NOT CACHEABLE: 4 chars extracted (need >= 200) — no text layer, likely a scan | prompt=...
```

`freshly-attached` vs `carried-over` comes from the `X-DejaQ-Attachment-Sticky` header. The chat app keeps an attachment **pinned** after a send so follow-up turns carry it too — without that, turn 2 arrives with no file at all, the model answers from its own previous reply, and the answer is stored as an ungated plain-text entry that a different document could later match. The marker is diagnostic only; nothing branches on it. It earns a place on the line because the two states fail differently: a REJECT on a fresh turn means two documents genuinely differ, while a REJECT on a carried turn means the *same bytes* hashed differently — extraction or transport is broken. The lines are otherwise identical. The same marker appears on `image kind=`.

**Is it the same document?**
```
file_gate ACCEPT — this=pdf/3f9a1c2e cached=pdf/3f9a1c2e SAME FILE | text_distance=0.1142 matched_prompt='...' entry=abc123
file_gate REJECT — this=pdf/3f9a1c2e cached=pdf/91be07d4 DIFFERENT FILE | ...
```

**Do we hold this document at all?** When the text lookup produces no candidate the file is never compared, and this line says whether we have it anyway — because "the question missed" and "we have never seen this file" are different problems with different fixes:
```
file_gate NOT REACHED — pdf/3f9a1c2e, the file was never compared: nearest text_distance=0.3104
(need <= 0.20) ... | NOTE: this exact file IS cached (2 entries) — the question was what missed,
not the file | prompt=...
```
