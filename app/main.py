from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import chat, feedback
from app.utils.logger import setup_logging
from app.config import USE_CELERY
import logging

# 1. Setup Global Logging
setup_logging()
logger = logging.getLogger("dejaq.main")

# 2. Initialize App
app = FastAPI(title="DejaQ Middleware", version="0.1.0")

# 3. CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 4. Include Routers
app.include_router(chat.router)
app.include_router(feedback.router)

@app.on_event("startup")
async def startup_event():
    logger.info("DejaQ Middleware starting up...")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("DejaQ Middleware shutting down...")

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