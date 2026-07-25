import asyncio
import logging
import tomllib
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

import httpx
import sentry_sdk
from asgi_correlation_id import CorrelationIdMiddleware, correlation_id
from fastapi import Depends, FastAPI
from fastapi_pagination import add_pagination
from prometheus_fastapi_instrumentator import Instrumentator
from sentry_sdk.integrations.logging import LoggingIntegration
from structlog_sentry import SentryProcessor

from logging_config import configure_logger
from logging_config.middleware import LoggingMiddleware
from mainframe.constants import GIT_SHA, Sentry, mainframe_settings
from mainframe.database import engine
from mainframe.dependencies import validate_token
from mainframe.endpoints import routers
from mainframe.metrics import (
    packages_queue_refresh_failures,
    performance_refresh_failures,
)
from mainframe.models.schemas import ServerMetadata
from mainframe.performance_monitor import PerformanceMonitor
from mainframe.pypi import PyPIClient
from mainframe.queue_monitor import QueueMonitor
from mainframe.rules import Rules, fetch_rules

from . import __version__


def add_correlation(_logger: logging.Logger, _method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Add request id to log message."""
    if request_id := correlation_id.get():
        event_dict["request_id"] = request_id
    return event_dict


def setup_logging() -> None:
    with Path(mainframe_settings.log_config_file).open("rb") as f:
        data = tomllib.load(f)

    configure_logger(data, [add_correlation, SentryProcessor(event_level=logging.ERROR, level=logging.DEBUG)])


async def monitor_queue(monitor: QueueMonitor, refresh_seconds: int) -> None:
    """Refresh queue metrics on a bounded interval independent of scrape traffic."""
    while True:
        await asyncio.sleep(refresh_seconds)
        try:
            await asyncio.to_thread(monitor.refresh)
        except Exception:
            packages_queue_refresh_failures.inc()
            logging.getLogger(__name__).exception("Failed to refresh queue metrics")


async def monitor_performance(
    monitor: PerformanceMonitor,
    refresh_seconds: int,
) -> None:
    """Refresh performance metrics independently of scrape traffic."""
    while True:
        await asyncio.sleep(refresh_seconds)
        try:
            await asyncio.to_thread(monitor.refresh)
        except Exception:
            performance_refresh_failures.inc()
            logging.getLogger(__name__).exception("Failed to refresh performance metrics")


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
async def lifespan(app_: FastAPI) -> AsyncGenerator[None, None]:
    """Load the state for the app."""
    http_client = httpx.Client()
    pypi_client = PyPIClient(http_client)
    rules = fetch_rules(http_client)

    app_.state.rules = rules
    app_.state.http_session = http_client
    app_.state.pypi_client = pypi_client

    setup_logging()
    queue_monitor = QueueMonitor(engine, job_timeout=mainframe_settings.job_timeout)
    app_.state.queue_monitor = queue_monitor
    try:
        await asyncio.to_thread(queue_monitor.refresh)
    except Exception:
        packages_queue_refresh_failures.inc()
        logging.getLogger(__name__).exception("Failed to load initial queue metrics")
    queue_monitor_task = asyncio.create_task(
        monitor_queue(queue_monitor, mainframe_settings.queue_metrics_refresh_seconds)
    )
    performance_monitor = PerformanceMonitor(engine)
    app_.state.performance_monitor = performance_monitor
    try:
        await asyncio.to_thread(performance_monitor.refresh)
    except Exception:
        performance_refresh_failures.inc()
        logging.getLogger(__name__).exception("Failed to load initial performance metrics")
    performance_monitor_task = asyncio.create_task(
        monitor_performance(
            performance_monitor,
            mainframe_settings.queue_metrics_refresh_seconds,
        )
    )

    yield

    queue_monitor_task.cancel()
    performance_monitor_task.cancel()
    with suppress(asyncio.CancelledError):
        await queue_monitor_task
    with suppress(asyncio.CancelledError):
        await performance_monitor_task


app = FastAPI(
    lifespan=lifespan,
    title="Mainframe",
    description="A service that provides a REST API for managing rules.",
    version=__version__,
)

Instrumentator().instrument(app).expose(app)

app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(LoggingMiddleware)


@app.get("/", tags=["metadata"])
async def metadata() -> ServerMetadata:
    """Get server metadata."""
    rules: Rules = app.state.rules
    return ServerMetadata(
        server_commit=GIT_SHA,
        rules_commit=rules.rules_commit,
    )


@app.post("/update-rules/", tags=["rules"], dependencies=[Depends(validate_token)])
async def update_rules() -> None:
    """Update the rules."""
    rules = fetch_rules(app.state.http_session)
    app.state.rules = rules


for router in routers:
    app.include_router(router)

add_pagination(app)
