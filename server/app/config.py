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

ENRICHER_MODEL_NAME = _get_text("DEJAQ_ENRICHER_MODEL_NAME", "qwen_1_5b")
NORMALIZER_MODEL_NAME = _get_text("DEJAQ_NORMALIZER_MODEL_NAME", "gemma_e2b")
LOCAL_LLM_MODEL_NAME = _get_text("DEJAQ_LOCAL_LLM_MODEL_NAME", "gemma_local")
GENERALIZER_MODEL_NAME = _get_text("DEJAQ_GENERALIZER_MODEL_NAME", "phi_generalizer")
CONTEXT_ADJUSTER_MODEL_NAME = _get_text("DEJAQ_CONTEXT_ADJUSTER_MODEL_NAME", "qwen_1_5b")
VALIDATOR_MODEL_NAME = _get_text("DEJAQ_VALIDATOR_MODEL_NAME", "gemma_e2b")
VALIDATOR_ENABLED = _get_bool("DEJAQ_VALIDATOR_ENABLED", True)
