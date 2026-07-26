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

# 5. Score.
uv run python ../evals/image_similarity/protocol.py
```

Datasets and `.jsonl` feature caches are gitignored — only code is tracked.

## What has been measured

Two corpora, 286,000 labelled pairs.

| corpus | what it is |
|---|---|
| round 1 | Hebrew coursework renders + DocUNet — contains near-duplicate documents from one template |
| round 2 | FUNSD business forms + arXiv paper pages — contains none |

**The shipped rule is a single token-overlap threshold at 0.80.** It is the measured
zero-false-merge point: across 69,411 different-document pairs the highest overlap any of
them reached was 0.798 — two exam papers for one course differing only by a date, a time
and one letter. Recall is ~45% (round 1) and ~54% (round 2). The full trade-off curve and
the reasoning are in [docs/image-gate.md](../../docs/image-gate.md).

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

- Both corpora are documents. The photo path was validated separately on 480 labelled
  photos.
- Renders at different DPI/crop stand in for re-screenshotting, not for photographing a
  screen. **Photos of screens remain barely covered**, and are a real use case.
- Round 2 is English; Hebrew OCR behaves differently.

## Older scripts

`gate_eval.py`, `augment.py`, `phash*.py`, `cluster.py`, `ocr_eval.py` predate the
protocol above and score the photo path only. `gate_eval.py` is still the right tool for
CLIP+dHash; prefer it over `phash_gate.py`, whose band-limited pair sampling hid a
degenerate-hash failure.
