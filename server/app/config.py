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


def _get_backend(name: str, default: str = "in_process") -> str:
    value = os.getenv(name, default).strip().lower()
    if value not in {"in_process", "ollama"}:
        logger.warning("Invalid %s value %r; using default %r", name, value, default)
        return default
    return value


def _get_text(name: str, default: str) -> str:
    value = os.getenv(name, default).strip()
    return value or default

# Redis
REDIS_URL = os.getenv("DEJAQ_REDIS_URL", "redis://localhost:6379/0")

# ChromaDB
CHROMA_HOST = os.getenv("DEJAQ_CHROMA_HOST", "127.0.0.1")
CHROMA_PORT = int(os.getenv("DEJAQ_CHROMA_PORT", "8001"))

# External LLM
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
EXTERNAL_MODEL_NAME = os.getenv("DEJAQ_EXTERNAL_MODEL", "gemini-2.5-flash")

# API key cache
KEY_CACHE_TTL = int(os.getenv("DEJAQ_KEY_CACHE_TTL", "60"))

# Stats DB
STATS_DB_PATH = os.getenv("DEJAQ_STATS_DB", "dejaq_stats.db")

# Feature flags
USE_CELERY = os.getenv("DEJAQ_USE_CELERY", "true").lower() == "true"

# Cache eviction
EVICTION_FLOOR = _get_float("DEJAQ_EVICTION_FLOOR", -5.0)

# Model backend config
OLLAMA_URL = _get_text("DEJAQ_OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_TIMEOUT_SECONDS = _get_float("DEJAQ_OLLAMA_TIMEOUT_SECONDS", 60.0)

ENRICHER_BACKEND = _get_backend("DEJAQ_ENRICHER_BACKEND")
NORMALIZER_BACKEND = _get_backend("DEJAQ_NORMALIZER_BACKEND")
LOCAL_LLM_BACKEND = _get_backend("DEJAQ_LOCAL_LLM_BACKEND")
GENERALIZER_BACKEND = _get_backend("DEJAQ_GENERALIZER_BACKEND")
CONTEXT_ADJUSTER_BACKEND = _get_backend("DEJAQ_CONTEXT_ADJUSTER_BACKEND")

ENRICHER_MODEL_NAME = _get_text("DEJAQ_ENRICHER_MODEL_NAME", "qwen_1_5b")
NORMALIZER_MODEL_NAME = _get_text("DEJAQ_NORMALIZER_MODEL_NAME", "gemma_e2b")
LOCAL_LLM_MODEL_NAME = _get_text("DEJAQ_LOCAL_LLM_MODEL_NAME", "gemma_local")
GENERALIZER_MODEL_NAME = _get_text("DEJAQ_GENERALIZER_MODEL_NAME", "phi_generalizer")
CONTEXT_ADJUSTER_MODEL_NAME = _get_text("DEJAQ_CONTEXT_ADJUSTER_MODEL_NAME", "qwen_1_5b")
