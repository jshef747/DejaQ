import os

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
try:
    EVICTION_FLOOR = float(os.getenv("DEJAQ_EVICTION_FLOOR", "-5.0"))
except ValueError:
    import logging as _logging
    _logging.getLogger("dejaq.config").warning(
        "Invalid DEJAQ_EVICTION_FLOOR value; using default -5.0"
    )
    EVICTION_FLOOR = -5.0

