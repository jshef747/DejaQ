import os
import logging

from dotenv import load_dotenv


load_dotenv()


logger = logging.getLogger("dejaq.config")


def _get_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid %s value; using default %s", name, default)
        return default


def _get_text(name: str, default: str) -> str:
    value = os.getenv(name, default).strip()
    return value or default


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid %s value; using default %s", name, default)
        return default


# Redis
REDIS_URL = os.getenv("DEJAQ_REDIS_URL", "redis://localhost:6379/0")

# ChromaDB
CHROMA_HOST = os.getenv("DEJAQ_CHROMA_HOST", "127.0.0.1")
CHROMA_PORT = int(os.getenv("DEJAQ_CHROMA_PORT", "8001"))

# Text-matching embedder, shared by the Q->A cache and RAG (memory_chromaDB.py,
# rag_service.py both call embed_text). Qwen3-Embedding-0.6B replaces
# BAAI/bge-small-en-v1.5 (384-dim) - measured on a 172-pair EN/HE corpus
# (dejaq-hebrew-model-swap report): Hebrew sibling-trap false merges 27/37 ->
# 11/37, English 19/37 -> 6/37, at the unchanged 0.15/0.20 trust/band
# thresholds. Cost: ~5x single-item encode latency (20ms -> 95ms on this
# machine) and 1024 vs 384 dims, so every existing ChromaDB collection needs
# rebuilding (Chroma fixes a collection's dimension on first insert - a
# dimension change is a hard error on the old collection, not a degraded
# result). Revert to "BAAI/bge-small-en-v1.5" with TEXT_EMBEDDING_QUERY_PREFIX
# set to "" to roll back; the collections must be rebuilt again either way.
TEXT_EMBEDDING_MODEL = _get_text("DEJAQ_TEXT_EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-0.6B")
# Qwen3-Embedding's instructed variant - measured best of 5 candidates in the
# same report. Applied uniformly to every embed_text call (cache queries, RAG
# chunks, RAG queries): the shared function has no query/document distinction
# today, and the evaluation that picked this prefix measured it the same way -
# symmetric question-to-question comparison, matching how the cache actually
# uses embed_text. Set to "" for a model with no instruction format (e.g. the
# original bge-small).
TEXT_EMBEDDING_QUERY_PREFIX = _get_text(
    "DEJAQ_TEXT_EMBEDDING_QUERY_PREFIX",
    "Instruct: Given a question, retrieve a question that asks the same thing\nQuery: ",
)

# External LLM
# No baked-in default: an unset DEJAQ_EXTERNAL_MODEL means no external model
# is configured server-wide, and every consumer must treat that as "ask the
# workspace to configure a provider" rather than silently picking one.
EXTERNAL_MODEL_NAME = os.getenv("DEJAQ_EXTERNAL_MODEL")
# 0.2986 goes with classifier.py's re-derived score weights, not the old
# 0.30/0.26 sweep of NVIDIA's weights - the two were searched jointly
# (dejaq-routing-weights-hebrew) and shipping one without the other is an
# untested combination, not "the best of both". 0.26 was the accuracy-
# maximizing threshold for the OLD weights only; once the weights changed,
# so does the distance distribution the threshold is cutting. On the
# weights' own 122-item corpus this combination is a strict improvement
# over the old 0.26/old-weights config (fewer false positives AND fewer
# false negatives), cross-validated at +5.7 accuracy points over baseline.
# Like the weights themselves, it does not rescue hard proofs or Hebrew -
# see classifier.py's process_logits comment and the Hebrew hybrid in
# openai_compat.py's routing step.
ROUTING_THRESHOLD = _get_float("DEJAQ_ROUTING_THRESHOLD", 0.2986)

# Multilingual difficulty classifier (LaBSE embedding + a LogisticRegression
# head trained on 770 items across seven languages,
# dejaq-classifier-probe-multilang) - now the classifier that decides
# easy/hard routing for every language, no per-language branching (see
# openai_compat.py's "classify" step). It replaced the old Hebrew-specific
# judge (removed - see fm/dejaq-classifier-wire-in) and, on this branch, the
# NVIDIA classifier below it: the old classifier missed essentially all hard
# Hebrew and only ~16.6% of hard questions overall
# (dejaq-classifier-wire-in/report.md), while this head was trained on
# labelled Hebrew directly. Threshold 0.5 is the LogisticRegression default
# decision boundary; class_weight="balanced" during training already
# corrects for the 60/40 easy/hard class imbalance, so 0.5 is not naively
# biased toward the majority class. Not swept against a captain-specified
# cost ratio between the two routing-error directions - predict_proba
# exposes every point on the ROC curve if one is ever specified.
LABSE_CLASSIFIER_THRESHOLD = _get_float("DEJAQ_LABSE_CLASSIFIER_THRESHOLD", 0.5)
# Default ON: this is the classifier that serves routing decisions now.
LOAD_LABSE_CLASSIFIER = _get_bool("DEJAQ_LOAD_LABSE_CLASSIFIER", True)
# Default OFF on this branch: the old NVIDIA classifier (ClassifierService,
# ~1.5GB) has no job left once routing moved to LaBSE, and not loading it is
# the whole point of the cutover - it is what pays for the new head's memory
# (dejaq-classifier-cutover/report.md). The code and model stay in the tree
# unmodified for staging, which still routes off this classifier and must
# not lose it when this branch merges; flip this on for local
# fallback/comparison without reverting any code.
LOAD_LEGACY_CLASSIFIER = _get_bool("DEJAQ_LOAD_LEGACY_CLASSIFIER", False)
CREDENTIAL_ENCRYPTION_KEY = os.getenv("DEJAQ_CREDENTIAL_ENCRYPTION_KEY", "")

# API key cache
KEY_CACHE_TTL = int(os.getenv("DEJAQ_KEY_CACHE_TTL", "60"))

# Ollama model-tag discovery cache (per-workspace pipeline model picker).
# Short on purpose: installing/removing an Ollama model is an operator
# action, not something needing sub-second freshness - the dashboard's
# manual "Refresh" bypasses this entirely for "I just ran ollama pull".
OLLAMA_CATALOG_CACHE_TTL_SECONDS = _get_float("DEJAQ_OLLAMA_CATALOG_TTL_SECONDS", 30.0)

# Stats DB
STATS_DB_PATH = os.getenv("DEJAQ_STATS_DB", "dejaq_stats.db")

# Feature flags
USE_CELERY = os.getenv("DEJAQ_USE_CELERY", "true").lower() == "true"

# Logging
LOG_LEVEL = _get_text("DEJAQ_LOG_LEVEL", "INFO").upper()
LOG_SHOW_CONTENT = _get_bool("DEJAQ_LOG_SHOW_CONTENT", False)

# In-process torch device for the difficulty classifier.
# "auto" probes the runtime (CUDA, then Apple Metal, then CPU); "cpu"/"cuda"/
# "mps" force one, for a driver bug or to leave the GPU free for something
# else. An unavailable or unrecognised value falls back to the probe rather
# than crashing the server - see services/classifier.py::_select_device.
TORCH_DEVICE = _get_text("DEJAQ_TORCH_DEVICE", "auto").lower()

# Cache eviction
EVICTION_FLOOR = _get_float("DEJAQ_EVICTION_FLOOR", -5.0)

# Cache lookup distance bands (cosine).
# Hits at or below CACHE_TRUST_DISTANCE are served directly (subject to the
# existing validator-skip / validation rules). Hits in the band
# (CACHE_TRUST_DISTANCE, CACHE_BAND_MAX_DISTANCE] are candidates only — they are
# served ONLY if the cache validator accepts them. Set CACHE_BAND_MAX_DISTANCE
# at or below CACHE_TRUST_DISTANCE to disable the band entirely.
CACHE_TRUST_DISTANCE = _get_float("DEJAQ_CACHE_TRUST_DISTANCE", 0.15)
# 0.20 is the empirically safe band ceiling: an offline sweep (typo vs
# different-question pairs, real validator verdicts) found the validator's first
# false-accept at distance ~0.21 ("freezing point" served the boiling answer).
# Sibling questions (freezing/boiling, hamlet/macbeth, list/string) cluster at
# 0.21–0.27 — the same range as heavier typos — so a wider band buys ~1 wrong
# answer per extra typo caught. Raise only alongside a stronger validator.
CACHE_BAND_MAX_DISTANCE = _get_float("DEJAQ_CACHE_BAND_MAX_DISTANCE", 0.20)

# Lexical rescue: candidates past the band but within this distance are still
# eligible when word-level alignment confirms the query is a typo'd variant of
# the stored one (see services/lexical_match.py). Heaviest real typo observed
# live sits at 0.52. Rescued hits are always validator-gated.
CACHE_RESCUE_ENABLED = _get_bool("DEJAQ_CACHE_RESCUE_ENABLED", True)
CACHE_RESCUE_MAX_DISTANCE = _get_float("DEJAQ_CACHE_RESCUE_MAX_DISTANCE", 0.60)

# Alias learning: after the validator accepts a band/rescue hit, store the
# typo'd phrasing as an alias entry pointing at the same answer, so the same
# typo becomes an instant trusted hit next time.
CACHE_ALIAS_ENABLED = _get_bool("DEJAQ_CACHE_ALIAS_ENABLED", True)

# Image fingerprint gate: a cached entry that carries an image is served to an
# image request ONLY if BOTH the CLIP cosine distance and the perceptual-hash
# (dHash) hamming distance are within bounds. Image hits get NO unguarded fast
# tier: dHash (~0.24ms) gates every one.
#
# 0.08, not 0.10. On 812 real photographs (INRIA Holidays, 300 scenes, 325,930
# different-scene pairs) a daylight rocky beach and a sunset over water were
# served as the same image at CLIP 0.0929 / hamming 6 — both are portrait
# seascapes split by a horizon, which is the degenerate-hash case image_
# fingerprint.py already warns about. 0.08 is the highest ceiling that admits
# none of those; it costs the re-upload corpus 69.5% -> 66.3% recall.
#
# hamming stays at 15 and is not negotiable downward-in-strictness: two DIFFERENT
# photographs of one terraced hillside measured CLIP 0.027 — inside any sane
# semantic ceiling — and were refused by hamming 29 alone.
CACHE_IMAGE_MAX_DISTANCE = _get_float("DEJAQ_CACHE_IMAGE_MAX_DISTANCE", 0.08)
CACHE_IMAGE_MAX_HAMMING = int(_get_float("DEJAQ_CACHE_IMAGE_MAX_HAMMING", 15))

# Note: both thresholds are load-bearing and neither may be relaxed alone. A
# "structural tier" (accept on hamming <= 10 with a looser CLIP ceiling) was
# measured and rejected — see the comment in services/image_fingerprint.py.
# The pixel gate above applies to PHOTOS only; documents go through OCR (below),
# because pixel similarity is actively wrong for them: two DIFFERENT syllabi on
# one university template measured CLIP 0.027 / hamming 0 (i.e. would have been
# served as the same image), while two screenshots of the SAME syllabus measured
# hamming 10-19 (i.e. would have missed).

# --- Image document path (OCR) ---
# Routing: an image is treated as a document only when OCR returns confident
# text. Measured over 4 rendered document pages, 4 handheld photos of a screen
# and 12 real photos: documents scored mean confidence 83.3-92.2 with 54-373
# confident words; unreadable screen photos reached 60 confident words but only
# ~35 mean confidence; the wordiest real photo reached 87.7 confidence but only
# 38 words. Requiring BOTH separates them with margin on either side.
#
# The word floor was 45 and cost a real miss: a cropped exercise snippet (two
# lines of Hebrew) OCR'd to 34 words at 84.8 confidence, so it fell to the photo
# path and missed at hamming 36 — while its token overlap with the re-cropped
# version was 0.833. Swept 20/25/30/34/35/40/45 over the 60 real photos: the
# confidence floor does nearly all the filtering, so 25 misroutes exactly ONE
# extra photo (src032, the 38-word one above) and produces **0 false merges at
# every floor** (max cross-photo token_jaccard 0.038 against a 0.85 threshold).
# The cost is that src032's variants split across kinds, losing some of its own
# recall — a miss, never a wrong answer.
CACHE_IMAGE_OCR_ENABLED = _get_bool("DEJAQ_CACHE_IMAGE_OCR_ENABLED", True)
# Swept 50-80 over both corpora: **0 false merges at every level**, because the
# 0.85 token threshold does the safety work — this floor only routes. It was 80,
# which sat inside the range real screenshots actually produce (measured live at
# 86.8, 84.8, 80.5 and 77.5 on one user's images) and refused them at random.
# Lowering it costs some photo recall: on 480 real photo files, 42 are routed to
# the document path at 80 and 69 at 60, and those lose pixel matching. Worst
# overlap between any two of them is 0.041 at every level, so they cannot merge —
# they simply miss. Documents are the workload that matters here, so the trade
# favours them.
CACHE_IMAGE_OCR_MIN_CONFIDENCE = _get_float("DEJAQ_CACHE_IMAGE_OCR_MIN_CONFIDENCE", 60.0)
# The word floor is deliberately low: the CONFIDENCE floor does the real work.
# It was 45, then 25, and both were wrong for the same reason — a short crop of a
# question is read perfectly (measured live: 9 words at 86.8 confidence) but has
# little text, so a high floor made it permanently un-cacheable. Swept 6/8/10/15/25
# over both corpora: 0 false merges at every level and under a point of recall
# between them. On 60 real photos a floor of 6 reclassifies just 2, and the worst
# overlap between any two text-bearing photos is 0.038 against a 0.85 threshold.
CACHE_IMAGE_OCR_MIN_WORDS = int(_get_float("DEJAQ_CACHE_IMAGE_OCR_MIN_WORDS", 6))

# A ratio over a handful of tokens is noise, not similarity: two images with three
# tokens each that happen to share them score a perfect 1.0. No such pair exists in
# the measured corpora, so this guards an edge the data does not cover rather than
# one it demonstrates. Kept below the smallest real document seen (9 words).
CACHE_IMAGE_TEXT_MIN_SHARED_TOKENS = int(_get_float("DEJAQ_CACHE_IMAGE_TEXT_MIN_SHARED_TOKENS", 4))

# An image that yields real text but misses the document bar is neither a
# document nor a photo: it is un-cacheable. It used to fall through to the pixel
# gate, which was the largest single source of wrong answers — 1,712 false merges
# on one measured corpus and 204 on another, because two different pages of text
# are near-identical to CLIP. The bar matters: only 11% of real scanned business
# forms clear the confidence floor (their median is 60.3), so the fallback was
# carrying most real-world documents. 4 words is where the merge count in the
# measured corpora collapses (204 -> 9); below it an image carries no readable
# text at all and the pixel gate is the right tool.
CACHE_IMAGE_AMBIGUOUS_MIN_WORDS = int(_get_float("DEJAQ_CACHE_IMAGE_AMBIGUOUS_MIN_WORDS", 4))

# Near-uniform images cannot be fingerprinted by pixels: a mostly-blank page is a
# white rectangle, and CLIP and dHash see all white rectangles as identical.
# Counted as distinct dHashes over a 4x4 grid, 60 real photos scored 13-16 of 16,
# while the blank page renders that were false-merging scored below 10. Blocking
# at 10 removed all 1,712 of those merges and 0 of the 60 real photos.
CACHE_IMAGE_MIN_TILE_VARIETY = int(_get_float("DEJAQ_CACHE_IMAGE_MIN_TILE_VARIETY", 10))

# Matching: OCR token overlap must clear this threshold AND the shared-token
# floor above (CACHE_IMAGE_TEXT_MIN_SHARED_TOKENS) — see image_text.py.
#
# 0.85, not 0.80. 0.80 was believed to be the zero-false-merge point because no
# corpus then measured contained two receipts from one shop: two SROIE receipts
# from one restaurant — same items, same total, differing only in invoice number
# and date — reach 0.848. 0.85 is the measured zero-merge point once real
# receipts are in the corpus.
#
# It was previously 0.70 plus a digit-token rule, which measured 234 false merges.
# Both the extra zones and the digit rule are gone: a joint sweep found that every
# configuration keeping them admitted merges. This costs recall (coursework 44%
# -> 34% of document-routed pairs) and that is the intended trade — a miss costs
# one API call, a merge serves an answer about someone else's document.
# Raise the value for more safety, lower it for more hits; 0.80 buys back ~10
# points at 2 measured merges. Full curve in docs/image-gate.md.
CACHE_IMAGE_TEXT_MIN_JACCARD = _get_float("DEJAQ_CACHE_IMAGE_TEXT_MIN_JACCARD", 0.85)

TESSERACT_BIN = _get_text("DEJAQ_TESSERACT_BIN", "tesseract")
TESSERACT_LANGS = _get_text("DEJAQ_TESSERACT_LANGS", "heb+eng")
OCR_TIMEOUT_SECONDS = _get_float("DEJAQ_OCR_TIMEOUT_SECONDS", 20.0)

# --- File gate (PDF, DOCX, text/Markdown/code) ---
# Deliberately three settings and NO swept thresholds, unlike the image gate
# above. Images need approximate identity because OCR is noisy — two reads of one
# page disagree, so every constant up there had to be measured over ~1.85M
# labelled pairs. Files hand us the text directly and deterministically:
# the same file always extracts the same characters, so identity is EXACT
# (sha256 of the whitespace-normalised text) and false merges are impossible by
# construction. There is no recall-vs-merge curve here, so there is nothing to
# sweep and no eval harness. See docs/file-gate.md.
CACHE_FILE_ENABLED = _get_bool("DEJAQ_CACHE_FILE_ENABLED", True)

# Generation ceiling when the client sends no limit of its own. 4096 rather than
# 1024 because 1024 truncated ordinary answers mid-sentence (done_reason=length);
# one measured coursework answer needed ~3,700 tokens on its own.
DEFAULT_MAX_TOKENS = int(_get_float("DEJAQ_DEFAULT_MAX_TOKENS", 4096))

# Output budget for the two rewrite steps (generalize, adjust), independent of
# whatever budget the original request ran under. Both prompts are told to keep
# every fact, so a rewrite needs room for at least the whole answer it was
# handed: at the old 1024 the stored copy of a long answer was truncated
# mid-sentence, and a truncated STORED answer never self-heals - it is what
# every future cache hit serves. 8192 rather than DEFAULT_MAX_TOKENS to leave
# headroom above it, since a client may ask for more than the default. Nothing
# clamps a client-supplied max_tokens, so an answer generated above this budget
# can still outgrow a rewrite of it; raise this - and OLLAMA_NUM_CTX with it -
# if that population turns out to be real. Must stay comfortably inside
# OLLAMA_NUM_CTX, which has to hold this generation PLUS the prompt carrying
# that answer.
REWRITE_MAX_TOKENS = int(_get_float("DEJAQ_REWRITE_MAX_TOKENS", 8192))

# Below this many characters a file cannot be identified, so it is neither served
# nor stored — the same rule as the image gate's `ambiguous` class, and the reason
# a scanned PDF (no text layer, ~0 characters extracted) is refused rather than
# guessed at. Not a tuned number: anything from a few dozen up works identically,
# because the population it separates (0-2 chars vs a real document) is not close
# to the line. Raising it only refuses more short-but-real files.
CACHE_FILE_MIN_CHARS = int(_get_float("DEJAQ_CACHE_FILE_MIN_CHARS", 200))

# Server-side attachment size cap, applied to files AND images. The chat client
# checks 10MB of its own, but a client-side check is not a limit — anything
# speaking the API directly bypasses it.
MAX_ATTACHMENT_BYTES = int(_get_float("DEJAQ_MAX_ATTACHMENT_BYTES", 10 * 1024 * 1024))

# --- RAG — per-workspace knowledge layer ---
# A third answer source alongside the Q→A cache and the LLM: admins curate
# documents into a workspace's own knowledge base ("{workspace_slug}__rag_kb"
# Chroma collection). On a cache MISS, the closest chunks are retrieved and
# injected into the prompt as grounding, so the answer comes from the workspace's own
# information — synthesised by whichever model (local/external) the query routes
# to. See services/rag_service.py and the retrieval step in openai_compat.py.
# Off switches BOTH retrieval and ingestion: every add path (dashboard, API, CLI)
# is refused in rag_admin_service, so a server that will never read knowledge
# cannot accumulate it. Listing and deleting stay open so an operator can clean up.
RAG_ENABLED = _get_bool("DEJAQ_RAG_ENABLED", True)
# Whether a cache MISS with no explicit `@`-reference may still guess which
# document is relevant via rag_service.retrieve()'s nearest-neighbour search.
# Defaults OFF on this branch: the captain does not want the system guessing
# which document a question is about — only an explicit `@`-reference
# (openai_responses.py's rag_document_id, fetched by exact id via
# rag_service.retrieve_by_document, never gated by this flag) grounds an
# answer. RAG_ENABLED stays the master switch for the whole layer — this only
# controls the automatic, guess-which-document path under it, and is
# deliberately independent so the automatic path can be turned back on later
# (e.g. once retrieval recall is fixed - see docs/rag-layer.md) without
# touching RAG_ENABLED, credentials, or the explicit-reference path at all.
RAG_AUTO_RETRIEVE = _get_bool("DEJAQ_RAG_AUTO_RETRIEVE", False)
# How many chunks to pull per query, and the cosine-distance ceiling a chunk must
# clear to count as relevant. 0.35 is deliberately looser than the cache trust
# distance (0.15): we want related context to ground the model, not an exact
# match. NOT a swept threshold — tune against real knowledge bases before trusting
# it in production; too loose injects noise, too tight injects nothing.
RAG_TOP_K = _get_int("DEJAQ_RAG_TOP_K", 4)
RAG_MAX_DISTANCE = _get_float("DEJAQ_RAG_MAX_DISTANCE", 0.35)
# Below this many total chunks in a workspace's knowledge base, retrieve()
# searches EXHAUSTIVELY (a linear scan) instead of through Chroma's HNSW
# approximate index. Measured: HNSW can miss a chunk that is objectively the
# best match when one large document's chunks dominate the graph. Rationale,
# before/after recall numbers, and the (deliberately conservative, untuned
# past ~5k chunks) reasoning behind this default: docs/rag-layer.md.
RAG_EXHAUSTIVE_MAX_CHUNKS = _get_int("DEJAQ_RAG_EXHAUSTIVE_MAX_CHUNKS", 20_000)
# Chunking: window size and overlap in characters when splitting a document.
RAG_CHUNK_CHARS = _get_int("DEJAQ_RAG_CHUNK_CHARS", 1000)
RAG_CHUNK_OVERLAP = _get_int("DEJAQ_RAG_CHUNK_OVERLAP", 150)
# Hard cap on the total characters of retrieved context injected into one prompt,
# so a handful of large chunks cannot blow the local model's context budget.
RAG_MAX_CONTEXT_CHARS = _get_int("DEJAQ_RAG_MAX_CONTEXT_CHARS", 6000)
# When RAG chunks are found, optionally force the request to the external
# (long-context) provider instead of respecting the difficulty classifier's
# local/external decision. Off by default — the classifier only ever sees the
# bare question, so routing stays stable and the local model still gets grounding.
RAG_FORCE_EXTERNAL = _get_bool("DEJAQ_RAG_FORCE_EXTERNAL", False)

# Model backend: generation runs through Ollama (local or remote per this URL).
OLLAMA_URL = _get_text("DEJAQ_OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_TIMEOUT_SECONDS = _get_float("DEJAQ_OLLAMA_TIMEOUT_SECONDS", 60.0)

# Context window for every Ollama-backed role, local answering (gemma4:e4b)
# included. Ollama's own runtime default is independent of what a model
# supports and far smaller than every model here allows (qwen2.5:1.5b 32768,
# gemma4:e2b 131072), and num_ctx bounds the PROMPT as well as the
# generation: left unset, a long enough prompt or generation overflows the
# window and Ollama silently drops the head of the prompt. For the two
# REWRITE roles (generalize, adjust) that means the rewrite never sees the
# tail of the answer it was told to preserve - the same silently-truncated
# stored copy REWRITE_MAX_TOKENS exists to prevent, reached from the other
# side. For local answering it means a large attachment's inlined text
# (openai_compat.py's _query_with_inlined_file - local generation has no
# native document part, so a big PDF/DOCX/text file rides in the prompt as
# plain text) can silently lose everything but its tail: confirmed, a
# 60,001-line file with a marker on line 1 answered as if only the last ~800
# lines existed, no error. 32768 is the smaller rewrite model's own maximum,
# so it is safe there; local answering runs gemma4:e4b, a different, larger
# model, but shares this same value rather than a bespoke one - one property
# to reason about, and the size guard in openai_compat.py (routing a file too
# large for THIS budget to the external provider instead of generating
# against it) is what actually keeps large attachments from silently
# truncating, not the size of the window alone. Every role that shares one of
# the two rewrite models' tags sends it too (enricher on qwen2.5:1.5b,
# normalizer and validator on gemma4:e2b, local answering wherever a
# workspace happens to point it at one of them), because Ollama treats a
# changed runner option as a reload of that model - two windows on one model
# tag unload and reload it between consecutive roles on the same request, on
# the synchronous serve path. That costs no extra memory over the rewrite
# roles alone: the model is already loaded at this window whenever
# generalize()/adjust()/generate() run.
#
# A workspace may override this value (workspace_llm_configs.ollama_num_ctx), and
# doing so reintroduces that same reload between WORKSPACES rather than between
# roles: two workspaces running different windows on one shared Ollama host force
# a reload of the underlying model tag on every alternating request, including on
# the synchronous serve path. Accepted tradeoff of the per-workspace token-budget
# feature, not a defect - a deployment that cares should keep the override
# uniform (or unset) across workspaces sharing a host. That override can only
# LOWER this window: because this value is already the smaller model's own
# maximum, it doubles as the admin-API ceiling for the per-workspace field
# (schemas/admin/llm_config.py reads it rather than restating a literal).
OLLAMA_NUM_CTX = int(_get_float("DEJAQ_OLLAMA_NUM_CTX", 32768))

# Ceiling on an attached FILE's extracted-text size (estimated tokens) for
# local answering, independent of whatever the context window would still
# technically fit. Exists because the hard-content judge (openai_compat.py's
# _judge_hard_content_over_text) gets measurably less reliable past roughly
# 30KB of surrounding text even with chunking narrowing the gap - a workspace
# running a stronger local model on more powerful hardware can afford to
# raise this, which is exactly why it is a per-workspace override
# (workspace_llm_configs.local_attachment_max_tokens) alongside OLLAMA_NUM_CTX,
# not a hard-coded constant. 8000 tokens (~32KB) is the measured point past
# which single-pass judging started missing buried hard content. Above the
# cap, a file routes external on the existing oversized-file path and the
# judge is never called - this is the one case where skipping the judge
# entirely is correct, since the judge call itself is what gets expensive on
# a large document. The context window is still a HARD precondition on top of
# this: openai_compat.py takes the smaller of the two, so raising this cap
# past what OLLAMA_NUM_CTX can hold has no effect.
LOCAL_ATTACHMENT_MAX_TOKENS = int(_get_float("DEJAQ_LOCAL_ATTACHMENT_MAX_TOKENS", 8000))

# Deadline for adjust() alone, the one rewrite role on the synchronous
# cache-hit path. Its budget is REWRITE_MAX_TOKENS, sized so a full-fidelity
# rewrite of the largest stored answer fits; without a deadline of its own the
# only bound left is OLLAMA_TIMEOUT_SECONDS, so a runaway spending that whole
# budget makes a waiting user hold the fast path open for the full shared
# timeout before the fallback fires. Not swept, and it does not need to be: the
# fallback is the complete cached answer (the same one every other guard in
# adjust() falls back to), so a deadline set too tight costs tone, never
# content. Half OLLAMA_TIMEOUT_SECONDS, which leaves a slow but legitimate
# large rewrite room while halving the worst case. generalize() gets no
# equivalent - it runs in a background Celery task with nobody waiting on it.
#
# CAPTAIN DECISION, do not re-litigate: this deadline and REWRITE_MAX_TOKENS
# are sized for opposite goals on the same call - the budget wide enough that
# the largest measured rewrite (~3,700 tokens) is never cut short, the
# deadline tight enough that a waiting user is never held past half the shared
# timeout. They can therefore disagree: emitting the full budget on
# qwen2.5:1.5b is plausibly 25-45s, so this deadline can fire before
# generation would have finished on its own, on exactly the long structured
# answers the adjust() prompt was reworked to preserve. Left as-is on purpose.
# THE DEADLINE IS THE REAL BOUND; REWRITE_MAX_TOKENS IS A BACKSTOP, not the
# other way around - and firing it is not a failure mode to close, because
# is_adjustment_sane()'s own fallback and this timeout's fallback are the same
# answer: the complete, already-validated cached text. A tighter deadline
# never serves anything wrong, only untailored - the identical trade this
# file's own safety nets already make. Reviewed and confirmed across several
# review rounds on this same PR (one raised REWRITE_MAX_TOKENS/OLLAMA_NUM_CTX,
# a later one scoped num_ctx to the rewrite roles, this one added the deadline
# and surfaced this exact tension) - a further pass over either number needs a
# captain decision, not another automated correction.
ADJUST_TIMEOUT_SECONDS = _get_float("DEJAQ_ADJUST_TIMEOUT_SECONDS", 30.0)

# Control-plane access control:
# DEJAQ_ADMIN_LOOPBACK_ONLY (default True) — /admin/v1/* only accepts loopback peers.
# DEJAQ_BIND_HOST — uvicorn listen host; used by start.sh (127.0.0.1 for bare uv run).
ADMIN_LOOPBACK_ONLY = _get_bool("DEJAQ_ADMIN_LOOPBACK_ONLY", True)
BIND_HOST = _get_text("DEJAQ_BIND_HOST", "127.0.0.1")

# Enricher stays on qwen_1_5b (qwen2.5:1.5b), NOT switched to qwen3:0.6b as
# dejaq-model-roles-refresh proposed: that switch was conditional on the
# target deployment holding a 4th distinct resident Ollama tag alongside the
# other three, and this machine measured (see fm-dejaq-model-refresh-implement
# report) that it does not reliably keep even today's 3 tags resident under
# rapid sequential load - it evicts down to one. A 4th tag that evicts the
# adjuster's qwen_1_5b tag (which the enricher shares today, by design, so a
# single cache-hit request never triggers a same-tag reload between the two)
# would replace the contention penalty this switch targets with a strictly
# worse cross-tag cold-load penalty. Left unchanged; see the implementation
# report for the measurement.
ENRICHER_MODEL_NAME = _get_text("DEJAQ_ENRICHER_MODEL_NAME", "qwen_1_5b")
# granite4.1:3b: same accuracy as gemma_e2b on the measured cases (5/5,
# cluster-consistent, deterministic), ~2x faster (~170ms vs ~390ms median).
NORMALIZER_MODEL_NAME = _get_text("DEJAQ_NORMALIZER_MODEL_NAME", "granite4_1_3b")
# Reverted from phi4_mini_3_8b (correction #2, dejaq-refresh-corrections):
# phi4-mini:3.8b reports only `completion, tools` on Ollama's own /api/show -
# no vision - so every image request silently routed external unconditionally,
# undoing the local-image feature. gemma4:e4b reports `completion, vision,
# audio, tools, thinking`. phi4-mini's speed/size win was real but not worth
# losing local image answering for; a vision-capable local model is required
# on this role.
LOCAL_LLM_MODEL_NAME = _get_text("DEJAQ_LOCAL_LLM_MODEL_NAME", "gemma_local")

# Swapped from phi_generalizer (phi3.5:latest) to gemma_e2b (gemma4:e2b):
# on a 20-query batch of fresh raw answers run through the real generalize()
# call, phi3.5 ran away on 5/20 (25%, matching the incident); gemma4:e2b ran
# away on 0/20, at roughly a third of the mean latency, with comparable or
# better factual fidelity (phi3.5 sometimes added unrequested commentary not
# present in the raw answer; gemma4:e2b mostly stayed a close, faithful
# restatement). One residual weakness observed, not a runaway: on a
# pathologically bare raw answer ("Au", no sentence), gemma4:e2b lost the
# fact entirely ("Acknowledgement.") rather than restating it - phi3.5
# mangled the same input into garbage instead, so this is not a regression,
# but it is a real content-fidelity gap worth watching, not a clean bill of
# health. See the incident report (dejaq-generalizer-runaway) for the full
# comparison.
# granite4.1:3b: no fabrication regression on the known defect's two inputs,
# comparable-or-faster than gemma_e2b, and bundles onto the same tag as the
# normalizer/validator below - three roles sharing one (smaller) tag, same
# shape as today.
GENERALIZER_MODEL_NAME = _get_text("DEJAQ_GENERALIZER_MODEL_NAME", "granite4_1_3b")
# Every other candidate tested (qwen3:0.6b/1.7b, granite4.1:3b, phi4-mini:3.8b)
# failed the "give me the short version" case - output was a near-verbatim
# copy of the input instead of a genuine condensation. qwen_1_5b is the only
# model that reliably shortens on request, and this role sits on the hot
# cache-hit path, so it stays.
CONTEXT_ADJUSTER_MODEL_NAME = _get_text("DEJAQ_CONTEXT_ADJUSTER_MODEL_NAME", "qwen_1_5b")
# granite4.1:3b: ties gemma_e2b on the broad accuracy set, ~2x faster, never
# produced an unparseable verdict (unlike two rejected candidates). NOT
# adopted because it "fixes a named defect" - an independent reconstruction
# of that defect (dejaq-thread-followup-form-mismatch) found the current
# model already answers it correctly, so the original claim doesn't hold; the
# swap rests on speed and equal accuracy alone.
VALIDATOR_MODEL_NAME = _get_text("DEJAQ_VALIDATOR_MODEL_NAME", "granite4_1_3b")
# Cache hits at or below this cosine distance are near-identical to the stored
# query; skip the validator and serve them directly (the embedding already
# guarantees the cached answer covers the question).
# Lowered from 0.05: a 172-pair labelled corpus (bge-small-en-v1.5, the
# shipped embedder) measured the smallest observed non-match distance at
# ~0.0036 overall / ~0.0103 Hebrew-only - so 0.05 left a real population of
# genuinely-different sibling questions fully unchecked (no validator, no
# inspection at all). 0.003 sits below that measured floor with margin, the
# same half-the-zero-false-merge-ceiling logic the image gate uses for its
# own thresholds. This is a mitigation, not a fix: the sibling-merge bug
# (dejaq-cache-sibling-merge) reproduces at distances as high as 0.0476, well
# above even the old 0.05 skip line, because the failure lives partly in the
# validator's own judgment on "same template, swapped differentiator"
# questions, not only in what skips it entirely.
VALIDATOR_SKIP_DISTANCE = _get_float("DEJAQ_VALIDATOR_SKIP_DISTANCE", 0.003)

# Below this cosine distance, on a single-turn request only (no prior
# conversation history - see openai_compat.py's use of `history`), skip
# adjust() entirely and serve the stored generalized_answer verbatim. Measured
# in a follow-up sweep over 3 cached anchor questions:
# single-turn typo/rephrase repeats of an already-cached question - no real
# tone or length ask - measured 0.0261-0.1687 (10 cases, 3 anchors); the
# lowest single-turn request that DID explicitly ask for something different
# ("explain in simple terms...") measured 0.0799. 0.075 sits inside that
# narrow gap, covering the diagnosed incident (0.0706) with a small margin on
# both sides. The gap is real but thin (13 samples total) and the tone side
# has only 3 - narrower evidence than ADJUSTER_MIN_TOPIC_OVERLAP's 52-case
# sweep, so this is a starting point to widen with more data, not a settled
# constant.
#
# The single-turn restriction is load-bearing, not a nicety: a multi-turn
# follow-up that DOES explicitly ask to shorten ("give me the short version")
# measured distance 0.0000-0.0093 in the same sweep - indistinguishable from
# or closer than typo noise - because the context enricher folds a
# conversational "make that shorter" turn back into a standalone restatement
# of the original question, discarding the length/tone request before the
# embedding is ever computed. Distance alone cannot separate that case from a
# meaningless typo repeat; requiring empty history rules out every case where
# that collapse was observed, since a fresh single-turn message has no prior
# answer for "shorter"/"like I'm 5" to refer to in the first place.
ADJUSTER_SKIP_DISTANCE = _get_float("DEJAQ_ADJUSTER_SKIP_DISTANCE", 0.075)

# Post-hoc safety net for the context adjuster: the minimum fraction of the
# cached answer's content words that must survive into the tone-adjusted
# answer. Below this, the adjustment is treated as a drift (e.g. the small
# adjuster model regurgitating an unrelated topic) and the known-good cached
# answer is served verbatim instead. Measured, not guessed: across 52 recorded
# safety-net firings, genuine drift never exceeded 0.0185 overlap while good
# short condensations of long cached answers started at 0.0229 - the old
# default of 0.1 was rejecting the latter as false positives on ~70% of its
# firings. See app/services/context_adjuster.py for the check itself.
ADJUSTER_MIN_TOPIC_OVERLAP = _get_float("DEJAQ_ADJUSTER_MIN_TOPIC_OVERLAP", 0.02)

# Store-time safety net for generalize(): catches the generalizer model
# finishing the real rewrite and then failing to stop, looping through
# paraphrases of its own few-shot examples until it hits the token cap
# (incident: dejaq-generalizer-runaway - a captured real answer went from 52
# input characters to a 5,456-character loop that never terminated). Measured
# against that capture plus a fresh 20-query batch: every clean rewrite
# stayed within 8x the raw answer's length; the shortest observed corrupted
# case (a contained few-shot leak, not even a full runaway) was 13.0x
# (415 characters from a 32-character raw answer). This sits inside that gap.
# See app/services/context_adjuster.py:is_generalization_sane.
#
# generalize()'s max_tokens moved from 1024 to REWRITE_MAX_TOKENS so a long
# answer stops truncating mid-sentence under the "Keep all facts" prompt (a raw
# miss answer can reach ~3,700 tokens, openai_compat.DEFAULT_MAX_TOKENS) - see
# is_generalization_sane's docstring for why this ratio still holds at the
# larger budget: it is a proportion of the raw answer's own length, not tied to
# the token budget, so a longer-running loop only pushes it further past this
# ceiling, never back under it.
GENERALIZE_LENGTH_RATIO_MAX = _get_float("DEJAQ_GENERALIZE_LENGTH_RATIO_MAX", 10.0)
# Below this absolute length, never flag on ratio alone - protects a short,
# correct rewrite of a very short raw answer (e.g. "Au") from a ratio false
# positive. Every captured corrupted case was far over this floor.
GENERALIZE_LENGTH_ABS_FLOOR = _get_float("DEJAQ_GENERALIZE_LENGTH_ABS_FLOOR", 200.0)
# Fraction of word 4-grams that repeat elsewhere in the output. Measured
# clean rewrites at 0.000 (no repeated 4-grams at all, n=3 sampled); the two
# captured runaways measured 0.136-0.150 even where each loop paraphrased
# itself differently (never a literal repeat, which is why line/substring
# matching alone misses this shape). Threshold sits inside that gap with
# margin both directions. Applied unless the raw answer was itself repetitive,
# the rewrite kept its size, and the rewrite is no more repetitive than the raw
# answer plus this same value (see NGRAM_EXEMPT_LENGTH_RATIO below) - which is
# the only population this value cannot serve.
GENERALIZE_NGRAM_REPEAT_RATIO_MAX = _get_float("DEJAQ_GENERALIZE_NGRAM_REPEAT_RATIO_MAX", 0.08)

# Serve-time safety net for adjust(), the same two signals the generalize()
# block above uses and for the same underlying failure - a small instruct model
# finishing the real rewrite and then looping through paraphrases of its own
# few-shot turns. Three differences from the generalize() constants, which is
# why these are separate knobs rather than a reuse:
#   - The baseline is the CACHED answer adjust() was handed, not a raw miss
#     answer. A tone rewrite is the same content in different words, so its
#     length should stay in the same neighbourhood.
#   - This runs on the synchronous cache-hit path, in front of a waiting user,
#     where generalize() runs in a background Celery task. Since adjust()'s cap
#     is REWRITE_MAX_TOKENS a loop now spends the full budget before returning,
#     bounded only by ADJUST_TIMEOUT_SECONDS above.
#   - Growth only. adjust() legitimately SHRINKS a long cached answer whenever
#     the question asks it to ("give me the short version", "explain it
#     simply"), so there is no lower length bound here; ADJUSTER_MIN_TOPIC_
#     OVERLAP above is what guards that direction.
# Not independently swept - carried over from the generalize() measurements,
# which cover the same models and the same runaway shape (incident:
# dejaq-generalizer-runaway). 10.0 sits in the gap those measurements found
# between clean rewrites (highest 8.0x) and corrupted output (lowest 13.0x),
# and the legitimate tone expansions recorded in
# tests/test_context_adjuster.py top out around 2.8x, well inside it.
ADJUST_LENGTH_RATIO_MAX = _get_float("DEJAQ_ADJUST_LENGTH_RATIO_MAX", 10.0)
# Minimum length of the CACHED answer for the ratio above to apply at all.
# Below it the denominator is too small for a ratio to mean anything: an
# "explain that in more detail" follow-up against a one-line cached answer
# ("The capital of France is Paris.", 31 characters) legitimately produces
# several hundred characters, which is a 10x+ ratio and a perfectly good
# rewrite. Note this measures the OPPOSITE side from
# GENERALIZE_LENGTH_ABS_FLOOR, which floors the output: for generalize() the
# output tracks the input's size (it only neutralizes tone, it never
# elaborates), so flooring either side comes to the same thing. adjust() is
# asked to expand, so only the baseline is a safe thing to floor - flooring the
# output would exempt small rewrites and reject exactly the large, correct
# elaborations this is meant to protect. Runaways on a short cached answer are
# left to the repetition signal below, which is what actually identifies a loop.
ADJUST_LENGTH_ABS_FLOOR = _get_float("DEJAQ_ADJUST_LENGTH_ABS_FLOOR", 200.0)
# Fraction of word 4-grams that repeat elsewhere in the output. This is the
# signal that actually catches the shape is_topically_consistent() is blind to:
# a loop that paraphrases the CACHED answer over and over scores near 1.0 on
# topic overlap and passes clean, because every repetition is drawn from the
# very vocabulary that check is looking for. Same threshold as the generalizer,
# measured against the same population - clean rewrites at 0.000, captured
# runaways at 0.136-0.150 even when each pass reworded itself - and likewise
# skipped for a rewrite of an already-repetitive cached answer that kept its
# size and added no repetition beyond it (see NGRAM_EXEMPT_LENGTH_RATIO below,
# which uses this same value as that headroom). That exemption matters more
# here than on the generalize() side: adjust()'s system prompt explicitly REQUIRES the
# rewrite to keep every bullet and numbered item of the cached answer, so
# without it the prompt would manufacture the very repetition that discards its
# own output - silently turning adjust() into a no-op for every templated
# answer, after paying its full serve-time latency.
ADJUST_NGRAM_REPEAT_RATIO_MAX = _get_float("DEJAQ_ADJUST_NGRAM_REPEAT_RATIO_MAX", 0.08)

# How far an output's length may differ from the answer it was rewriting, in
# either direction, and still be exempt from the two repetition ceilings above.
# Shared by both guards: the exemption exists for one population and it is the
# same population on both paths - a faithful rewrite of an answer that is
# ALREADY repetitive (a templated list, a weekly schedule), which both prompts
# require to keep every item and which therefore inherits its source's
# repetition without inventing any.
#
# This is only one of the exemption's three conditions. The other two both
# concern the repetition itself, and neither needs a constant of its own - the
# ceiling being exempted serves as both:
#   - The baseline must already exceed that ceiling, i.e. carry repetition for
#     the rewrite to inherit at all. Size alone would also exempt a
#     self-paraphrase loop over ordinary prose, which lands at its input's size
#     while inventing every repetition it has (measured on a 657-character
#     non-repetitive answer: loops at 0.877x and 1.102x scoring 0.202-0.208).
#   - The output may exceed the baseline's own repetition by at most that
#     ceiling. Otherwise the condition above is a binary gate and a baseline a
#     hair over it exempts any same-size output however repetitive (measured on
#     a mildly structured answer at 0.088: same-size loops score 0.570-0.618).
#     The faithful templated rewrite this exemption exists for sits at +0.079.
# See context_adjuster._inherits_baseline_repetition().
#
# Size is what separates the templated case from a loop, in both directions: a
# loop repeats itself into MORE text than it was given (measured on a 50-item
# templated list: a faithful rewrite is 1.18x, self-paraphrase loops 2.27x and
# up), or collapses onto one item and repeats that instead (0.56x). 1.3 admits
# the faithful rewrite with margin and leaves both loop shapes facing the
# unmodified ceiling.
#
# Scaling the ceilings to the baseline's own repetition was tried instead and
# removed: at 1.5x the baseline it opened a fail-open band on this very
# population, where a loop running 2-3 further self-paraphrase passes scored
# 0.508-0.526 against a 0.527 ceiling while staying far under the length arm's
# 10x. This form leaves the measured 0.08 thresholds untouched.
NGRAM_EXEMPT_LENGTH_RATIO = _get_float("DEJAQ_NGRAM_EXEMPT_LENGTH_RATIO", 1.3)
