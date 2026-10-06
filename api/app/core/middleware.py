from collections.abc import Awaitable, Callable

from fastapi import Request, Response

from app.core.logging import parse_trace_header, trace_id_var


async def trace_context_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    token = trace_id_var.set(parse_trace_header(request.headers.get("x-cloud-trace-context")))
    try:
        return await call_next(request)
    finally:
        trace_id_var.reset(token)
