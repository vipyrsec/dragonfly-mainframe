import logging
import logging.config
import tomllib
from contextlib import asynccontextmanager
from typing import Any

import httpx
import sentry_sdk
from asgi_correlation_id import CorrelationIdMiddleware, correlation_id
from fastapi import Depends, FastAPI
from fastapi_pagination import add_pagination
from letsbuilda.pypi import PyPIServices
from sentry_sdk.integrations.logging import LoggingIntegration
from structlog_sentry import SentryProcessor
from logging_config import configure_logger
from logging_config.middleware import LoggingMiddleware

from mainframe.constants import GIT_SHA, Sentry, mainframe_settings
from mainframe.dependencies import validate_token, validate_token_override
from mainframe.endpoints import routers
from mainframe.models.schemas import ServerMetadata
from mainframe.rules import Rules, fetch_rules

from . import __version__


def add_correlation(logger: logging.Logger, method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Add request id to log message."""
    if request_id := correlation_id.get():
        event_dict["request_id"] = request_id
    return event_dict


def setup_logging():
    with open(mainframe_settings.log_config_file, "rb") as f:
        data = tomllib.load(f)

    configure_logger(data, [add_correlation, SentryProcessor(event_level=logging.ERROR, level=logging.DEBUG)])


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

    http_client = httpx.Client()
    pypi_client = PyPIServices(http_client)
    rules = fetch_rules(http_client)

    app_.state.rules = rules
    app_.state.http_session = http_client
    app_.state.pypi_client = pypi_client

    setup_logging()

    yield


app = FastAPI(
    lifespan=lifespan,
    title="Mainframe",
    description="A service that provides a REST API for managing rules.",
    version=__version__,
)
add_pagination(app)

if GIT_SHA in ("development", "testing"):
    app.dependency_overrides[validate_token] = validate_token_override


app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(LoggingMiddleware)


@app.get("/", tags=["metadata"])
async def metadata() -> ServerMetadata:
    """Get server metadata"""

    rules: Rules = app.state.rules
    return ServerMetadata(
        server_commit=GIT_SHA,
        rules_commit=rules.rules_commit,
    )


@app.post("/update-rules/", tags=["rules"], dependencies=[Depends(validate_token)])
async def update_rules():
    """Update the rules"""
    rules = fetch_rules(app.state.http_session)
    app.state.rules = rules


for router in routers:
    app.include_router(router)
