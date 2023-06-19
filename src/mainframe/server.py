import asyncio
import logging
import time
from contextlib import asynccontextmanager
from os import getenv
from typing import Annotated
from unittest.mock import MagicMock
import sentry_sdk
import aiohttp
import structlog
from asgi_correlation_id import CorrelationIdMiddleware
from asgi_correlation_id.context import correlation_id
from fastapi import Depends, FastAPI, Response
from h11 import Request
from letsbuilda.pypi import PyPIServices
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from mainframe.constants import mainframe_settings
from mainframe.database import async_session, get_db
from mainframe.dependencies import validate_token, validate_token_override
from mainframe.endpoints import routers
from mainframe.models.orm import Rule
from mainframe.models.schemas import ServerMetadata
from mainframe.rules import Rules, fetch_rules


async def sync_rules(*, http_session: aiohttp.ClientSession, session: AsyncSession):
    rules = await fetch_rules(http_session)
    session.add_all(Rule(name=rule_name) for rule_name in rules.rules)
    try:
        await session.commit()
    except IntegrityError:
        # Ignore rules that already exist in the database
        pass


def configure_logger():
    # Define the shared processors, regardless of whether API is running in prod or dev.
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.stdlib.ExtraAdder(),
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

    log_renderer: structlog.types.Processor
    # If running in production, render logs with JSON.
    if mainframe_settings.production:
        log_renderer = structlog.processors.JSONRenderer()
    else:
        # If running in a development environment, pretty print logs
        log_renderer = structlog.dev.ConsoleRenderer()

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


release_prefix = getenv("DRAGONFLY_SENTRY_RELEASE_PREFIX", "dragonfly")
git_sha = getenv("GIT_SHA", "development")
sentry_sdk.init(
    dsn=getenv("DRAGONFLY_SENTRY_DSN"),
    environment=getenv("DRAGONFLY_SENTRY_ENV"),
    send_default_pii=True,
    traces_sample_rate=0.0025,
    profiles_sample_rate=0.0025,
    release=f"{release_prefix}@{git_sha}",
)


@asynccontextmanager
async def lifespan(app_: FastAPI):
    """Load the state for the app"""

    http_session = aiohttp.ClientSession()
    pypi_client = PyPIServices(http_session)
    rules = await fetch_rules(http_session)

    if getenv("env") == "test":
        fut: asyncio.Future[MagicMock] = asyncio.Future()
        fut.set_result(MagicMock(return_value=MagicMock()))
        pypi_client.get_package_metadata = MagicMock(return_value=fut)
        pypi_client.get_package_metadata.return_value.urls = [MagicMock(url=None), MagicMock(url=None)]

    app_.state.rules = rules
    app_.state.http_session = http_session
    app_.state.pypi_client = pypi_client

    session = async_session()
    await sync_rules(http_session=http_session, session=session)
    await session.close()

    configure_logger()

    yield


app = FastAPI(lifespan=lifespan)

if mainframe_settings.production is False:
    app.dependency_overrides[validate_token] = validate_token_override


@app.middleware("http")
async def logging_middleware(request: Request, call_next) -> Response:
    structlog.contextvars.clear_contextvars()

    request_id = correlation_id.get()
    url = request.url
    client_host = request.client.host
    client_port = request.client.port
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


@app.get("/")
async def root_route() -> ServerMetadata:
    rules: Rules = app.state.rules
    return ServerMetadata(
        server_commit=getenv("GIT_SHA", "development"),
        rules_commit=rules.rules_commit,
    )


@app.post("/update-rules/")
async def update_rules(session: Annotated[AsyncSession, Depends(get_db)]):
    """Update the rules"""
    rules = await fetch_rules(app.state.http_session)
    app.state.rules = rules

    await sync_rules(http_session=app.state.http_session, session=session)


for router in routers:
    app.include_router(router)
