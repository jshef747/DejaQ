import os

# Redis
REDIS_URL = os.getenv("DEJAQ_REDIS_URL", "redis://localhost:6379/0")

# ChromaDB
CHROMA_HOST = os.getenv("DEJAQ_CHROMA_HOST", "127.0.0.1")
CHROMA_PORT = int(os.getenv("DEJAQ_CHROMA_PORT", "8001"))

# External LLM
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
EXTERNAL_MODEL_NAME = os.getenv("DEJAQ_EXTERNAL_MODEL", "gpt-4o")
EXTERNAL_API_BASE = os.getenv("DEJAQ_EXTERNAL_API_BASE", None)

# Feature flags
USE_CELERY = os.getenv("DEJAQ_USE_CELERY", "true").lower() == "true"

# Feedback loop thresholds
FEEDBACK_TRUSTED_THRESHOLD = int(os.getenv("DEJAQ_TRUSTED_THRESHOLD", "3"))
FEEDBACK_FLAG_THRESHOLD = int(os.getenv("DEJAQ_FLAG_THRESHOLD", "-3"))
FEEDBACK_AUTO_DELETE_THRESHOLD = int(os.getenv("DEJAQ_AUTO_DELETE_THRESHOLD", "-5"))
FEEDBACK_TRUSTED_SIMILARITY = float(os.getenv("DEJAQ_TRUSTED_SIMILARITY", "0.20"))
FEEDBACK_SUPPRESSION_TTL = int(os.getenv("DEJAQ_SUPPRESSION_TTL", "300"))
