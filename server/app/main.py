from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import openai_compat, departments, feedback
from app.middleware.api_key import ApiKeyMiddleware
from app.utils.logger import setup_logging
from app.config import (
    CONTEXT_ADJUSTER_BACKEND,
    CONTEXT_ADJUSTER_MODEL_NAME,
    ENRICHER_BACKEND,
    ENRICHER_MODEL_NAME,
    GENERALIZER_BACKEND,
    GENERALIZER_MODEL_NAME,
    LOCAL_LLM_BACKEND,
    LOCAL_LLM_MODEL_NAME,
    NORMALIZER_BACKEND,
    NORMALIZER_MODEL_NAME,
    OLLAMA_URL,
    USE_CELERY,
)
from app.services.request_logger import request_logger
from app.services.service_factory import (
    get_context_adjuster_service,
    get_context_enricher_service,
    get_llm_router_service,
    get_normalizer_service,
)
import logging
from contextlib import asynccontextmanager

# 1. Setup Global Logging
setup_logging()
logger = logging.getLogger("dejaq.main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("DejaQ Middleware starting up...")
    logger.info(
        "Model config: enricher=%s/%s normalizer=%s/%s local_llm=%s/%s generalizer=%s/%s context_adjuster=%s/%s",
        ENRICHER_BACKEND,
        ENRICHER_MODEL_NAME,
        NORMALIZER_BACKEND,
        NORMALIZER_MODEL_NAME,
        LOCAL_LLM_BACKEND,
        LOCAL_LLM_MODEL_NAME,
        GENERALIZER_BACKEND,
        GENERALIZER_MODEL_NAME,
        CONTEXT_ADJUSTER_BACKEND,
        CONTEXT_ADJUSTER_MODEL_NAME,
    )
    if any(
        backend == "ollama"
        for backend in (
            ENRICHER_BACKEND,
            NORMALIZER_BACKEND,
            LOCAL_LLM_BACKEND,
            GENERALIZER_BACKEND,
            CONTEXT_ADJUSTER_BACKEND,
        )
    ):
        logger.info("Ollama enabled: url=%s", OLLAMA_URL)
    get_normalizer_service()
    get_llm_router_service()
    get_context_adjuster_service()
    get_context_enricher_service()
    await request_logger.init()
    yield
    await request_logger.close()
    logger.info("DejaQ Middleware shutting down...")

# 2. Initialize App
app = FastAPI(title="DejaQ Middleware", version="0.1.0", lifespan=lifespan)

# 3. CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["x-dejaq-model-used", "x-dejaq-conversation-id", "x-dejaq-response-id"],
)

# 3b. API key middleware (runs after CORS)
app.add_middleware(ApiKeyMiddleware)

# 4. Include Routers
app.include_router(openai_compat.router, prefix="/v1")
app.include_router(feedback.router, prefix="/v1")
app.include_router(departments.router)

# Replaced by lifespan context manager

@app.get("/health")
async def health_check():
    logger.debug("Health check requested")
    result = {"status": "ok", "service": "DejaQ Middleware", "celery": "disabled"}

    if USE_CELERY:
        try:
            from app.celery_app import celery_app
            ping = celery_app.control.ping(timeout=1.0)
            result["celery"] = "ok" if ping else "no_workers"
        except Exception:
            result["celery"] = "redis_unreachable"

    return result
