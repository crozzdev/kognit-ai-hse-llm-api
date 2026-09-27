"""FastAPI application assembly (R1.1, R1.16, R15.36).

``create_app`` builds the ``FastAPI`` app with ``root_path="/llm"``, installs the
request-context middleware and the CORS allow-list, registers the health and
service-identity routes, and installs the exception handlers that render every
failure as the uniform ``{error_category, message, request_id}`` body (R13.32).

The chat route ``POST /chat/message`` is registered by the LangGraph milestone
(M-13); the published OpenAPI already advertises the status codes 200, 400, 415,
422, 503 and 504 for the contract (R1.16).
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError as FastAPIValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from kognit_llm.agent.state import ErrorCategory
from kognit_llm.api.errors import LlmApiError, error_body
from kognit_llm.api.middleware import RequestContextMiddleware
from kognit_llm.api.models import ErrorBody
from kognit_llm.api.routes_health import build_health_router

if TYPE_CHECKING:
    from kognit_llm.config.settings import Settings

__all__ = ["create_app"]

# Status codes the chat contract advertises in its OpenAPI schema (R1.16).
_CONTRACT_STATUS_CODES = (200, 400, 415, 422, 503, 504)


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "")


def _error_json(status: int, body: ErrorBody) -> JSONResponse:
    return JSONResponse(status_code=status, content=body.model_dump())


def _validation_body(request_id: str, message: str) -> ErrorBody:
    return ErrorBody(
        error_category=ErrorCategory.VALIDATION_ERROR.value,
        message=message,
        request_id=request_id,
    )


def create_app(settings: "Settings") -> FastAPI:
    """Assemble and return the configured FastAPI application."""
    app = FastAPI(
        title="Kognit AI HSE LLM API",
        version=settings.service_version,
        root_path="/llm",
        responses={
            code: {"model": ErrorBody} for code in _CONTRACT_STATUS_CODES if code >= 400
        },
    )

    # Middleware is applied in reverse registration order, so CORS runs outermost
    # and the request-context middleware sees the request first for id assignment.
    app.add_middleware(RequestContextMiddleware, settings=settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["POST", "GET", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
    )

    app.include_router(build_health_router(settings))
    app.include_router(_build_chat_router(settings))

    _register_exception_handlers(app)
    return app


def _build_chat_router(settings: "Settings"):
    """Assemble node dependencies, compile the graph, and build the chat router."""
    from kognit_llm.agent.graph import build_graph
    from kognit_llm.agent.nodes.deps import NodeDeps
    from kognit_llm.api.routes_chat import build_chat_router
    from kognit_llm.config.secrets import SecretResolver
    from kognit_llm.data.executor import WarehouseExecutor
    from kognit_llm.data.pool import build_pool
    from kognit_llm.memory.in_memory import InMemoryConversationStore
    from kognit_llm.observability.logger import RequestLogger
    from kognit_llm.observability.redaction import Redactor
    from kognit_llm.providers.factory import build_provider
    from kognit_llm.schema.allowlist import load_allowlist

    redactor = Redactor()
    resolver = SecretResolver(settings=settings, publish=redactor.publish)
    logger = RequestLogger(redactor)
    provider = build_provider(settings, resolver)
    store = InMemoryConversationStore(
        turn_max=settings.conversation_turn_max,
        conversation_max=settings.conversation_max,
        ttl_seconds=settings.conversation_ttl_seconds,
        char_budget=settings.conversation_char_budget,
        clock=lambda: _utcnow(),
    )
    # The pool opens on first warehouse use, so building it needs no live DB.
    pool = build_pool(settings, resolver.database())
    executor = WarehouseExecutor(
        pool,
        row_cap=settings.row_cap,
        max_result_columns=settings.max_result_columns,
        max_result_bytes=settings.max_result_bytes,
    )
    deps = NodeDeps(
        settings=settings,
        provider=provider,
        executor=executor,
        store=store,
        allowlist=load_allowlist(),
    )
    graph = build_graph(deps)
    return build_chat_router(settings, deps, graph, logger)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(LlmApiError)
    async def _handle_llm_error(request: Request, exc: LlmApiError) -> JSONResponse:
        body = error_body(exc, _request_id(request))
        return _error_json(exc.http_status, body)

    @app.exception_handler(FastAPIValidationError)
    async def _handle_validation(
        request: Request, exc: FastAPIValidationError
    ) -> JSONResponse:
        field = _first_invalid_field(exc.errors())
        message = f"The field '{field}' is missing or invalid." if field else (
            "The request body failed validation."
        )
        return _error_json(422, _validation_body(_request_id(request), message))

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        request_id = _request_id(request)
        if exc.status_code == 415:
            message = "application/json is the supported media type."
        elif exc.status_code == 400:
            message = "The request body is not valid JSON."
        else:
            message = str(exc.detail)
        return _error_json(exc.status_code, _validation_body(request_id, message))


def _first_invalid_field(errors: Sequence[Any]) -> str:
    """Return the first offending field name from a validation error list."""
    for err in errors:
        loc = err.get("loc", ())
        # Skip the leading "body" element to name the field itself.
        parts = [str(p) for p in loc if p != "body"]
        if parts:
            return parts[0]
    return ""
