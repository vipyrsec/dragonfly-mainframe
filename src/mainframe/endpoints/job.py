from datetime import datetime, timedelta, timezone
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session, joinedload, aliased

from mainframe.constants import mainframe_settings
from mainframe.database import get_db
from mainframe.dependencies import get_rules, validate_token
from mainframe.json_web_token import AuthenticationData
from mainframe.models.orm import Scan, Status
from mainframe.models.schemas import JobResult
from mainframe.rules import Rules

router = APIRouter(tags=["job"])
logger: structlog.stdlib.BoundLogger = structlog.get_logger()


@router.post("/jobs")
def get_jobs(
    session: Annotated[Session, Depends(get_db)],
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

    with session, session.begin():
        # Use a CTE to limit the number of rows we fetch
        cte = (
            select(Scan)
            .where(
                or_(
                    Scan.status == Status.QUEUED,
                    and_(
                        Scan.pending_at
                        < datetime.now(timezone.utc) - timedelta(seconds=mainframe_settings.job_timeout),
                        Scan.status == Status.PENDING,
                    ),
                )
            )
            .order_by(Scan.pending_at.nulls_first(), Scan.queued_at)
            .limit(batch)
            .options(joinedload(Scan.download_urls))
            .with_for_update(skip_locked=True)
            .cte()
        )

        scan_cte = aliased(Scan, cte)

        # Uses a Postgres `UPDATE .. FROM`. https://docs.sqlalchemy.org/en/20/tutorial/data_update.html#update-from
        scans = session.scalars(
            update(Scan)
            .where(Scan.scan_id == scan_cte.scan_id)
            .values(status=Status.PENDING, pending_at=datetime.now(timezone.utc), pending_by=auth.subject)
            .returning(Scan)
        )

        response_body: list[JobResult] = []
        for scan in scans:
            logger.info(
                "Job given and status set to pending in database",
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
