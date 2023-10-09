import logging
import time
from contextlib import asynccontextmanager
from typing import Awaitable, Callable

import sentry_sdk
import structlog
from asgi_correlation_id import CorrelationIdMiddleware
from asgi_correlation_id.context import correlation_id
from fastapi import FastAPI, Request, Response
from httpx import Client
from letsbuilda.pypi import PyPIServices
from sentry_sdk.integrations.logging import LoggingIntegration
from structlog_sentry import SentryProcessor

from mainframe.constants import GIT_SHA, Sentry
from mainframe.dependencies import validate_token, validate_token_override
from mainframe.endpoints import routers
from mainframe.models.schemas import ServerMetadata
from mainframe.rules import Rules, fetch_rules

from . import __version__


def configure_logger():
    # Define the shared processors, regardless of whether API is running in prod or dev.
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.stdlib.ExtraAdder(),
        SentryProcessor(event_level=logging.ERROR, level=logging.DEBUG),
        structlog.processors.format_exc_info,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.CallsiteParameterAdder(
            {
                structlog.processors.CallsiteParameter.FILENAME,
                structlog.processors.CallsiteParameter.FUNC_NAME,
                structlog.processors.CallsiteParameter.MODULE,
                structlog.processors.CallsiteParameter.LINENO,
            }
        ),
    ]

    structlog.configure(
        processors=shared_processors + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # log_renderer: structlog.types.Processor
    # # If running in production, render logs with JSON.
    # if mainframe_settings.production:
    #     log_renderer = structlog.processors.JSONRenderer()
    # else:
    #     # If running in a development environment, pretty print logs
    #     log_renderer = structlog.dev.ConsoleRenderer()

    # TODO: Once infra for log aggregation is up and running, remove this and go back to
    # TODO: JSON logging in production.
    log_renderer = structlog.dev.ConsoleRenderer(colors=False)

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            log_renderer,
        ],
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.DEBUG)

    # Disable uvicorn's logging
    for _log in ["uvicorn", "uvicorn.error"]:
        logging.getLogger(_log).handlers.clear()
        logging.getLogger(_log).propagate = True

    logging.getLogger("uvicorn.access").handlers.clear()
    logging.getLogger("uvicorn.access").propagate = False


sentry_sdk.init(
    dsn=Sentry.dsn,
    environment=Sentry.environment,
    send_default_pii=True,
    traces_sample_rate=0.05,
    profiles_sample_rate=0.05,
    release=f"{Sentry.release_prefix}@{GIT_SHA}",
    integrations=[LoggingIntegration(event_level=None, level=None)],
)


@asynccontextmanager
async def lifespan(app_: FastAPI):
    """Load the state for the app"""

    http_session = Client()
    pypi_client = PyPIServices(http_session)
    rules = fetch_rules(http_session=http_session)

    app_.state.rules = rules
    app_.state.http_session = http_session
    app_.state.pypi_client = pypi_client

    configure_logger()

    yield


app = FastAPI(
    lifespan=lifespan,
    title="Mainframe",
    description="A service that provides a REST API for managing rules.",
    version=__version__,
)

if GIT_SHA in ("development", "testing"):
    app.dependency_overrides[validate_token] = validate_token_override


@app.middleware("http")
async def logging_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    structlog.contextvars.clear_contextvars()

    request_id = correlation_id.get() or ""
    url = request.url
    client_host = request.client.host if request.client else ""
    client_port = request.client.port if request.client else ""
    structlog.contextvars.bind_contextvars(
        request_id=request_id,
        url=url,
        network={"client": {"ip": client_host, "port": client_port}},
    )

    start_time = time.perf_counter_ns()
    logger: structlog.stdlib.BoundLogger = structlog.get_logger()

    response: Response = Response(status_code=500)
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("Uncaught exception")
        raise
    finally:
        process_time = time.perf_counter_ns() - start_time
        status_code = response.status_code
        http_method = request.method
        http_version = request.scope["http_version"]
        await logger.ainfo(
            f'{client_host}:{client_port} - "{http_method} {url} HTTP/{http_version}" {status_code}',
            http={
                "url": str(url),
                "status_code": status_code,
                "method": http_method,
                "request_id": request_id,
                "version": http_version,
            },
            duration=process_time,
            tag="request",
        )

        return response


app.add_middleware(CorrelationIdMiddleware)


@app.get("/", tags=["metadata"])
async def metadata() -> ServerMetadata:
    """Get server metadata"""
    rules: Rules = app.state.rules
    return ServerMetadata(
        server_commit=GIT_SHA,
        rules_commit=rules.rules_commit,
    )


@app.post("/update-rules/", tags=["rules"])
async def update_rules():
    """Update the rules"""
    rules = fetch_rules(app.state.http_session)
    app.state.rules = rules


for router in routers:
    app.include_router(router)
