from typing import Annotated

import structlog
from fastapi import APIRouter, Depends

from mainframe.dependencies import get_rules, job_cache, validate_token
from mainframe.job_cache import JobCache
from mainframe.json_web_token import AuthenticationData
from mainframe.models.orm import Scan
from mainframe.models.schemas import JobResult
from mainframe.rules import Rules

router = APIRouter(tags=["job"])
logger: structlog.stdlib.BoundLogger = structlog.get_logger()


@router.post("/jobs")
def get_jobs(
    job_cache: Annotated[JobCache, Depends(job_cache)],
    auth: Annotated[AuthenticationData, Depends(validate_token)],
    state: Annotated[Rules, Depends(get_rules)],
    batch: int = 1,
) -> list[JobResult]:
    """
    Request one or more releases to work on.

    Clients can specify the number of jobs they want to be given
    using the `batch` query string parameter. If omitted, it defaults
    to `1`.

    Clients are assigned the oldest release in the queue, i.e., the release
    with the oldest `queued_at` time.

    We also consider releases with a `pending_at` older than
    `now() - JOB_TIMEOUT` to be queued at the current time. This way, timed out
    packages are always processed after newly queued packages.
    """

    scans: list[Scan] = []
    for _ in range(batch):
        scan = job_cache.get_job()
        if scan:
            scans.append(scan)

    response_body: list[JobResult] = []
    for scan in scans:
        logger.info(
            "Job given",
            package={
                "name": scan.name,
                "status": scan.status,
                "pending_at": scan.pending_at,
                "pending_by": auth.subject,
                "version": scan.version,
            },
            tag="job_given",
        )

        job_result = JobResult(
            name=scan.name,
            version=scan.version,
            distributions=[dist.url for dist in scan.download_urls],
            hash=state.rules_commit,
        )

        response_body.append(job_result)

    return response_body
