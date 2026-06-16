import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import ADMIN_LOOPBACK_ONLY

logger = logging.getLogger("dejaq.middleware.admin_loopback")

# Addresses that are considered loopback / local-only.
# The raw transport peer (request.client.host) is used exclusively;
# X-Forwarded-For is intentionally ignored — there is no trusted proxy on-prem.
_LOOPBACK_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "::1", "localhost"})


class AdminLoopbackMiddleware(BaseHTTPMiddleware):
    """Restrict /admin/v1/* to loopback peers (127.0.0.1 / ::1) when
    DEJAQ_ADMIN_LOOPBACK_ONLY is True (the default).

    This runs BEFORE ApiKeyMiddleware (add_middleware is LIFO in FastAPI/Starlette,
    so add this AFTER ApiKeyMiddleware in main.py to ensure it executes first).

    Security notes:
    - Uses only request.client.host (transport peer). Never trusts X-Forwarded-For.
    - request.client is None in some test harnesses; treat None as non-loopback (deny).
    - /health and /v1/* are unaffected.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        if not ADMIN_LOOPBACK_ONLY:
            return await call_next(request)

        if not request.url.path.startswith("/admin/v1"):
            return await call_next(request)

        client = request.client
        if client is None or client.host not in _LOOPBACK_HOSTS:
            peer = client.host if client else "unknown"
            logger.warning(
                "Admin API access denied from non-loopback peer %s %s",
                peer,
                request.url.path,
            )
            return JSONResponse(
                status_code=403,
                content={"detail": "Admin API is restricted to localhost. Use SSH tunneling for remote access."},
            )

        return await call_next(request)
