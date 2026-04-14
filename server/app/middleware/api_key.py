# server/app/middleware/api_key.py
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("dejaq.middleware.api_key")

# Known tenant registry — extend this dict as tenants are onboarded.
# Format: { "token": "tenant_id" }
_KNOWN_KEYS: dict[str, str] = {}


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Extract Bearer token from Authorization header and attach to request state.

    Always allows the request through — auth enforcement is future work.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        api_key: str | None = None
        tenant_id: str = "anonymous"

        auth_header = request.headers.get("Authorization", "")
        if auth_header:
            parts = auth_header.split(" ", 1)
            if len(parts) == 2 and parts[0].lower() == "bearer":
                api_key = parts[1]
                tenant_id = _KNOWN_KEYS.get(api_key, "anonymous")
                if tenant_id == "anonymous":
                    redacted = api_key[:8] + "..." if len(api_key) > 8 else api_key
                    logger.warning("Unrecognized API key: %s — serving as anonymous", redacted)
            else:
                logger.warning(
                    "Malformed Authorization header (expected 'Bearer <token>'): %s",
                    auth_header[:30],
                )

        request.state.api_key = api_key
        request.state.tenant_id = tenant_id
        return await call_next(request)
