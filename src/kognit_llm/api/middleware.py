"""Request middleware: identifiers, body cap, rate limit, concurrency, auth seam.

This middleware generates the per-request ``request_id`` (36-char UUIDv4, R1.15)
and ``correlation_id`` (from a bounded correlation header, else generated,
R14.34-R14.35), enforces the 16384-byte body cap with HTTP 413 (R13.34), the
per-IP rate limit and in-flight concurrency bound with HTTP 429 (R13.20-R13.22),
and reserves the position for a future authentication layer: an ``Authorization``
header is accepted and ignored, so Bearer auth can be added later without
changing the contract (R1.17). CORS itself is registered in ``app.py`` through
Starlette's ``CORSMiddleware`` with the configured allow-list (R13.10).

Rate limiting and concurrency are per execution environment and in-memory, which
matches the single-process Lambda execution model; they are best-effort bounds,
not a distributed limiter.
"""

import threading
import time
import uuid
from collections import defaultdict, deque
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from kognit_llm.agent.state import ErrorCategory

if TYPE_CHECKING:
    from starlette.middleware.base import RequestResponseEndpoint

    from kognit_llm.config.settings import Settings

__all__ = [
    "CORRELATION_HEADER",
    "CORRELATION_ID_MAX_LEN",
    "RequestContextMiddleware",
]

CORRELATION_HEADER = "X-Correlation-Id"
CORRELATION_ID_MAX_LEN = 128
_RATE_WINDOW_SECONDS = 60.0


def _new_id() -> str:
    """Return a 36-character UUIDv4 string (R1.15)."""
    return str(uuid.uuid4())


def _validation_body(request_id: str, message: str) -> dict[str, str]:
    return {
        "error_category": ErrorCategory.VALIDATION_ERROR.value,
        "message": message,
        "request_id": request_id,
    }


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach identifiers and enforce body, rate and concurrency bounds."""

    def __init__(self, app: ASGIApp, settings: "Settings") -> None:
        super().__init__(app)
        self._settings = settings
        self._lock = threading.Lock()
        self._in_flight = 0
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(
        self, request: Request, call_next: "RequestResponseEndpoint"
    ) -> Response:
        request_id = _new_id()
        correlation_id = self._resolve_correlation_id(request)
        request.state.request_id = request_id
        request.state.correlation_id = correlation_id

        cap = self._settings.request_body_max_bytes
        declared = request.headers.get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > cap:
            return self._reject(
                413,
                request_id,
                correlation_id,
                f"The request body exceeds the maximum size of {cap} bytes.",
            )

        client_ip = request.client.host if request.client else "unknown"
        if self._rate_limited(client_ip):
            return self._reject(
                429,
                request_id,
                correlation_id,
                "The request rate limit was exceeded.",
            )

        if not self._enter_in_flight():
            return self._reject(
                429,
                request_id,
                correlation_id,
                "The service is at capacity.",
            )
        try:
            response = await call_next(request)
        finally:
            self._exit_in_flight()

        response.headers[CORRELATION_HEADER] = correlation_id
        return response

    def _resolve_correlation_id(self, request: Request) -> str:
        supplied = request.headers.get(CORRELATION_HEADER)
        if supplied is not None and 1 <= len(supplied) <= CORRELATION_ID_MAX_LEN:
            return supplied
        return _new_id()

    def _reject(
        self, status: int, request_id: str, correlation_id: str, message: str
    ) -> JSONResponse:
        response = JSONResponse(
            status_code=status,
            content=_validation_body(request_id, message),
        )
        response.headers[CORRELATION_HEADER] = correlation_id
        return response

    def _rate_limited(self, client_ip: str) -> bool:
        limit = self._settings.rate_limit_per_minute
        now = time.monotonic()
        with self._lock:
            hits = self._hits[client_ip]
            cutoff = now - _RATE_WINDOW_SECONDS
            while hits and hits[0] < cutoff:
                hits.popleft()
            if len(hits) >= limit:
                return True
            hits.append(now)
            return False

    def _enter_in_flight(self) -> bool:
        with self._lock:
            if self._in_flight >= self._settings.concurrent_request_max:
                return False
            self._in_flight += 1
            return True

    def _exit_in_flight(self) -> None:
        with self._lock:
            self._in_flight = max(0, self._in_flight - 1)
