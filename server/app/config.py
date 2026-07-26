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


# Redis
REDIS_URL = os.getenv("DEJAQ_REDIS_URL", "redis://localhost:6379/0")

# ChromaDB
CHROMA_HOST = os.getenv("DEJAQ_CHROMA_HOST", "127.0.0.1")
CHROMA_PORT = int(os.getenv("DEJAQ_CHROMA_PORT", "8001"))

# External LLM
EXTERNAL_MODEL_NAME = os.getenv("DEJAQ_EXTERNAL_MODEL", "gemini-2.5-flash")
ROUTING_THRESHOLD = _get_float("DEJAQ_ROUTING_THRESHOLD", 0.3)
CREDENTIAL_ENCRYPTION_KEY = os.getenv("DEJAQ_CREDENTIAL_ENCRYPTION_KEY", "")

# API key cache
KEY_CACHE_TTL = int(os.getenv("DEJAQ_KEY_CACHE_TTL", "60"))

# Stats DB
STATS_DB_PATH = os.getenv("DEJAQ_STATS_DB", "dejaq_stats.db")

# Feature flags
USE_CELERY = os.getenv("DEJAQ_USE_CELERY", "true").lower() == "true"

# Logging
LOG_LEVEL = _get_text("DEJAQ_LOG_LEVEL", "INFO").upper()
LOG_SHOW_CONTENT = _get_bool("DEJAQ_LOG_SHOW_CONTENT", False)

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
# (dHash) hamming distance are within bounds. Offline validation across two
# datasets (own photos + INRIA Copydays) showed the closest genuinely-different
# photo pair at CLIP ~0.048, inside any plausible "trusted" zone — so unlike the
# text path, image hits get NO unguarded fast tier: dHash (~0.24ms) gates every
# one. hamming<=15 held cross-group rejection at 89.5% (own) / 99.3% (Copydays).
CACHE_IMAGE_MAX_DISTANCE = _get_float("DEJAQ_CACHE_IMAGE_MAX_DISTANCE", 0.10)
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
# every floor** (max cross-photo token_jaccard 0.038 against a 0.35 threshold).
# The cost is that src032's variants split across kinds, losing some of its own
# recall — a miss, never a wrong answer.
CACHE_IMAGE_OCR_ENABLED = _get_bool("DEJAQ_CACHE_IMAGE_OCR_ENABLED", True)
CACHE_IMAGE_OCR_MIN_CONFIDENCE = _get_float("DEJAQ_CACHE_IMAGE_OCR_MIN_CONFIDENCE", 80.0)
CACHE_IMAGE_OCR_MIN_WORDS = int(_get_float("DEJAQ_CACHE_IMAGE_OCR_MIN_WORDS", 25))

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

# Matching: one threshold on OCR token overlap. 0.80 is the measured
# zero-false-merge point — over 69,411 different-document pairs the highest
# overlap any of them reached was 0.798 (two exam papers for the same course
# differing only by a date, a time and one letter).
#
# It was previously 0.70 plus a digit-token rule, which measured 234 false merges.
# Both the extra zones and the digit rule are gone: a joint sweep found that every
# configuration keeping them admitted merges. This costs recall (~45% coursework,
# ~54% forms and papers, from 89.8%) and that is the intended trade — a miss costs
# one API call, a merge serves an answer about someone else's document.
# Raise the value for more safety, lower it for more hits; 0.70 buys ~78% recall
# at a measured 114 merges. Full curve in docs/image-gate.md.
CACHE_IMAGE_TEXT_MIN_JACCARD = _get_float("DEJAQ_CACHE_IMAGE_TEXT_MIN_JACCARD", 0.80)

TESSERACT_BIN = _get_text("DEJAQ_TESSERACT_BIN", "tesseract")
TESSERACT_LANGS = _get_text("DEJAQ_TESSERACT_LANGS", "heb+eng")
OCR_TIMEOUT_SECONDS = _get_float("DEJAQ_OCR_TIMEOUT_SECONDS", 20.0)

# Model backend: generation runs through Ollama (local or remote per this URL).
OLLAMA_URL = _get_text("DEJAQ_OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_TIMEOUT_SECONDS = _get_float("DEJAQ_OLLAMA_TIMEOUT_SECONDS", 60.0)

# Supabase management auth
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")
# Service-role key: only for explicit setup/seed paths, never for HTTP request auth
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

# Management auth mode: "supabase" validates JWTs via Supabase; "local" grants an
# unauthenticated dev-admin context (local development only — never expose remotely).
# Defaults to "local" when Supabase is unconfigured, "supabase" otherwise.
AUTH_MODE = _get_text(
    "DEJAQ_AUTH_MODE",
    "local" if not SUPABASE_URL.strip() else "supabase",
).strip().lower()

# Control-plane access control:
# DEJAQ_ADMIN_LOOPBACK_ONLY (default True) — /admin/v1/* only accepts loopback peers.
# DEJAQ_BIND_HOST — uvicorn listen host; used by start.sh (127.0.0.1 for bare uv run).
ADMIN_LOOPBACK_ONLY = _get_bool("DEJAQ_ADMIN_LOOPBACK_ONLY", True)
BIND_HOST = _get_text("DEJAQ_BIND_HOST", "127.0.0.1")

ENRICHER_MODEL_NAME = _get_text("DEJAQ_ENRICHER_MODEL_NAME", "qwen_1_5b")
NORMALIZER_MODEL_NAME = _get_text("DEJAQ_NORMALIZER_MODEL_NAME", "gemma_e2b")
LOCAL_LLM_MODEL_NAME = _get_text("DEJAQ_LOCAL_LLM_MODEL_NAME", "gemma_local")
GENERALIZER_MODEL_NAME = _get_text("DEJAQ_GENERALIZER_MODEL_NAME", "phi_generalizer")
CONTEXT_ADJUSTER_MODEL_NAME = _get_text("DEJAQ_CONTEXT_ADJUSTER_MODEL_NAME", "qwen_1_5b")
VALIDATOR_MODEL_NAME = _get_text("DEJAQ_VALIDATOR_MODEL_NAME", "gemma_e2b")
# Cache hits at or below this cosine distance are near-identical to the stored
# query; skip the validator and serve them directly (the embedding already
# guarantees the cached answer covers the question).
VALIDATOR_SKIP_DISTANCE = _get_float("DEJAQ_VALIDATOR_SKIP_DISTANCE", 0.05)
