from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from app.core.config import get_settings

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


async def origin_check_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Defense in depth on top of SameSite=Lax cookies: reject state-changing browser requests
    whose Origin is not ours. Requests without an Origin (server-to-server) pass through."""
    origin = request.headers.get("origin")
    if request.method in UNSAFE_METHODS and origin:
        settings = get_settings()
        if origin not in {settings.public_web_url, *settings.cors_origins}:
            return JSONResponse({"detail": "Origin not allowed"}, status_code=403)
    return await call_next(request)
