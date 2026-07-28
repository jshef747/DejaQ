# Image gate evaluation

Measures the question the image cache actually asks: **given two images, are they the
same content?** Same content must hit; different content must never be served, because a
false merge hands a user an answer about someone else's document while a miss only costs
one API call.

Thresholds in `server/app/config.py` are derived here. Do not tune them by hand.

## The protocol

`protocol.py` is the contract. A candidate is any function `score(a, b) -> float` over two
feature records, higher meaning "more likely the same". It sweeps the candidate's own
threshold and reports recall at 0, 5 and 25 false merges. **The headline number is recall
at zero false merges.**

```python
from protocol import load, evaluate, report, token_jaccard
recs = load()                       # document-routed images only
report(evaluate(recs, token_jaccard, "baseline"))
```

## Rebuilding a corpus

```bash
cd server

# 1. Your own documents. Several sittings of one exam, or several invoices on one
#    template, are the most valuable material — they are the hard negatives.
uv run python ../evals/image_similarity/build_corpus.py --pdf-dir ~/Documents/exams

# 2. DocUNet: 65 real paper documents, each as 2 camera photos + 2 crops + 1 flat scan.
#    ~1 GB. Cite Ma et al., CVPR 2018. https://www3.cs.stonybrook.edu/~cvl/docunet.html
mkdir -p ../evals/image_similarity/docunet && cd $_
for f in original scan crop; do
  curl -sSLO "http://vision.cs.stonybrook.edu/~kema/docwarp/$f.zip" && unzip -qo "$f.zip" -d unzipped/
done

# 3. Real scanned business forms (FUNSD, 199 forms) + arXiv paper pages, where v1/v2 of
#    one paper is the same document with genuinely changed content.
cd server
uv run python ../evals/image_similarity/fetch_round2.py
uv run python ../evals/image_similarity/fetch_arxiv.py

# 4. Extract every signal once (OCR text/boxes/confidences, CLIP, dHash, tile hashes).
#    ~1.5 s per image.
CORPUS_DIR=corpus FEATURES_OUT=features_rich.jsonl \
  uv run python ../evals/image_similarity/features_rich.py

# 4b. Round 3: real photos, receipts, screenshots, and camera photos of screens.
uv run python ../evals/image_similarity/fetch_round3.py holidays --limit 300
uv run python ../evals/image_similarity/fetch_round3.py sroie --limit 200
uv run python ../evals/image_similarity/fetch_round3.py rico --limit 200
uv run python ../evals/image_similarity/fetch_round3.py uhdm --limit 150

# 5. Score.
uv run python ../evals/image_similarity/protocol.py     # candidate research
uv run python ../evals/image_similarity/gate_report.py  # what the shipped code serves
uv run python ../evals/image_similarity/doc_sweep.py feat_receipts.jsonl
uv run python ../evals/image_similarity/photo_sweep.py feat_photos.jsonl

# 6. End to end, against a running server (see the module docstring for setup).
uv run python ../evals/image_similarity/e2e_gate.py
```

Datasets and `.jsonl` feature caches are gitignored — only code is tracked.

## The two questions, and which script answers which

`protocol.py` is a research tool: *could some scoring function separate these images?* It
filters to document-routed images and sweeps a candidate's own threshold, so its recall
numbers are **recall among documents**, not end to end.

`gate_report.py` is the operational one: *given these images, what does the code in
`server/app` actually serve?* It imports the predicates and constants from the application
rather than restating them, counts routing losses as misses, and reports the number a user
feels — **what fraction of served cache hits were about something else**. Its recall is
therefore lower than `protocol.py`'s on the same corpus; both are correct, they answer
different questions.

## What has been measured

Seven corpora, roughly 1.85M labelled pairs, scored against the shipped constants.

| corpus | what it is | recall | false merges | wrong per hit |
|---|---|---|---|---|
| round 1 | Hebrew coursework renders + DocUNet | 32.4% | 0 | 0% |
| round 2 | FUNSD business forms + arXiv pages | 13.2% | 1 | 0.8% |
| receipts | SROIE — real scanned receipts, many from one store | 19.4% | 2 | 0.8% |
| screens | Rico — real Android UI screenshots | 48.2% | 19 | 3.2% |
| photos | INRIA Holidays — 812 photos, 300 scenes | 7.0% | 1 | 1.5% |
| augment | the original 480 Copydays-derived variants | 44.6% | 0 | 0% |
| recapture | UHDM — camera photos of screens, paired with the source | 76.9% | 0 | 0% |

The table above is at the **old** constants (token 0.80, CLIP 0.10), which is what the round
found. Both have since moved, and the two merges they were moved for are gone:

**The 0.80 token threshold was not the zero-merge point it was believed to be.** Two SROIE
receipts from one restaurant — same items, same total, differing only in invoice number and
date — reach 0.848. **Shipped is now 0.85**, which is clean on receipts. Zero merges on UI
screenshots would need 0.95, and that figure is soft: those pairs are the same screen with a
dialog open or different chips selected, i.e. the same content in a different state, not
somebody else's document.

**The photo path had one unambiguous merge.** A daylight rocky beach and a sunset over water
(`hol01008` / `hol01268`) measure CLIP 0.0929, hamming 6 — both are portrait seascapes split
by a horizon, which is the dHash degeneracy `image_fingerprint.py` already warns about.
**Shipped is now 0.08**, which removes it.

At the new constants the seven corpora score 24.7 / 9.9 / 11.5 / 41.4 / 7.0 / 41.8 / 67.2%
recall, with false merges 0 / 1 / 0 / 15 / 0 / 0 / 0 — the surviving round-2 merge is two
FUNSD forms that OCR could not read at all (0–2 tokens), which fall to the pixel path because
the ambiguous rule needs 4 tokens.

**dHash earns its place.** Two different photos of one terraced hillside measured CLIP
**0.027** — well inside any sane semantic ceiling — and were refused only by hamming 29.
Loosening hamming to buy photo recall would open that class of merge immediately.

**Resolution, not framing, is what breaks the document path.** Round 1, by what changed
between two captures of one page:

| change | served |
|---|---|
| same resolution, any crop | 63–78% |
| different resolution, same crop | 3–35% |

Normalising it away before OCR was investigated in full and **rejected** — see
`## Rejected: normalising image size before OCR` in [docs/image-gate.md](../../docs/image-gate.md).
Four variants, all reproducible from `features_rich.py` env knobs (`CANON_HEIGHT`,
`CANON_WORD_HEIGHT` + `CANON_QUANT`, `CANON_FIXED_SCALE`, and `hybrid_probe.py` for the
routing-only recombination). The short version: a flat 2× upscale gains 8 points of recall and
introduces false merges on three of four corpora — 16 on receipts, 4 on the coursework — because
reading a page more completely also reads the shared boilerplate of two near-duplicate documents
more completely. Two different receipts go from 0.848 overlap to 0.983. `ocr_cost.py` measures
what it would cost on the request path.

## Dataset notes worth keeping

- `creative-graphic-design/Rico` serves **semantic-annotation renderings** (flat colour
  blocks) in its `screenshot` column, not screenshots. Use
  `rootsautomation/RICO-Screen2Words`, which also carries `app_package_name` — two screens
  of one app are the realistic screenshot hard negative.
- INRIA Holidays files three byte-identical photos under two scene ids. `gate_report.load()`
  collapses groups holding an identical fingerprint; without that the corpus reports false
  merges that are really labelling errors.
- `build_corpus.py` emits **duplicate label rows** for the DocUNet half — round 1's
  `labels.json` has 1097 entries over 845 distinct files. Duplicates pair with themselves at
  overlap 1.0 and are always served, so they inflate round-1 recall (23.8% deduplicated vs
  24.7% raw) without affecting merge counts. Deduplicate on `path` before quoting a round-1
  recall number.
- UHDM recapture pairs are camera captures **aligned with their source**, so 76.9% is an
  upper bound for photographing a screen. A handheld phone photo at an angle is harder.

## Candidates that were tried and lost

`candidates/` holds four families, each measured against the same protocol. Three lost;
all four are kept because knowing what does *not* work is the expensive part.

| candidate | idea | recall @ 0 merges |
|---|---|---|
| — | baseline token overlap | 45.5% |
| `textnorm_probe.py` | OCR-noise-robust text (char n-grams, fuzzy matching, embeddings) | 46.1% |
| `sequence_probe.py` | word order (bigrams, trigrams, LCS) | 49.1% |
| `layout_probe.py` | where words sit on the page | 52.1% |
| `fields_probe.py` | extract dates/times/version markers and veto on disagreement | 90.6% |

The field veto is **not shipped**, despite the number. It wins only where documents share
a template: on round 2 it *loses* to plain matching (91.4% vs 97.3%), and it wrongly
rejected 8 of 124 arXiv v1/v2 pairs because a revision changed the date — i.e. it breaks
any document that gets updated. Its gain was judged 60-70% specific to one corpus.

All four converged on the same finding: the difference between two near-duplicate
documents is a small localised edit, and no global similarity score isolates it. Fuzzy
token matching also measured 12.7 ms per pair, far too slow for a request path.

Hebrew literals in `candidates/` are written as `\uXXXX` escapes to keep every file ASCII;
behaviour is unchanged.

## Untested ideas worth a round

- **Align, then diff.** `layout_probe.py` already fits the scale+translation between two
  pages but never applies it and compares the aligned pixels. A changed date block would
  show as one concentrated region; a re-capture as diffuse noise. This is the one the
  failed candidates all point at.
- Document-specific page embeddings (ColPali/DSE family). Only a general English sentence
  model was tried, and it came last.
- Simply asking the local model "same document?" — known to cost ~500 ms from the
  validator work, never measured here.

## Known limits of the evidence

- The photo path's positives are still weak. Holidays pairs are two *different photographs
  of one scene*, which the gate refuses by design (7% served); the augmentation corpus is
  variants of a single shot. Nothing measures the middle — the same object photographed
  twice a second apart.
- UHDM recaptures are aligned with their source, so they flatter the recapture case.
- Rounds 2 and 3 are English apart from the coursework; Hebrew OCR behaves differently, and
  every Hebrew document in the corpus comes from one university's templates.
- Screenshot ground truth treats a UI state change as different content. Judge those merge
  counts by eye before acting on them.
- Nothing here measures whether a served answer was *useful*, only whether it was about the
  same image.

## Older scripts

`gate_eval.py`, `augment.py`, `phash*.py`, `cluster.py`, `ocr_eval.py` predate the
protocol above and score the photo path only. `gate_eval.py` is still the right tool for
CLIP+dHash; prefer it over `phash_gate.py`, whose band-limited pair sampling hid a
degenerate-hash failure.
