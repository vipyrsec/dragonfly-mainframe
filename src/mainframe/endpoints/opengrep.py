"""Staging-only OpenGrep shadow queue and result endpoints."""

import datetime as dt
import uuid
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select, text, update
from sqlalchemy.orm import Session

from mainframe.constants import mainframe_settings
from mainframe.database import get_db
from mainframe.dependencies import get_rules, validate_token
from mainframe.json_web_token import AuthenticationData
from mainframe.models.orm import OpenGrepScan, Scan, Status
from mainframe.models.schemas import (
    GetRules,
    JobResult,
    OpenGrepAlert,
    OpenGrepPublicationClaim,
    OpenGrepPublicationProgress,
    OpenGrepPublished,
    OpenGrepResult,
    OpenGrepScanResult,
    OpenGrepScanResultFail,
    QueuePackageResponse,
)
from mainframe.rules import Rules


def require_opengrep_shadow() -> None:
    """Hide the shadow API unless staging explicitly enables it."""
    if not mainframe_settings.opengrep_shadow_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND)


router = APIRouter(
    prefix="/opengrep",
    tags=["opengrep"],
    dependencies=[
        Depends(validate_token),
        Depends(require_opengrep_shadow),
    ],
)


Authenticated = Annotated[AuthenticationData, Depends(validate_token)]
Database = Annotated[Session, Depends(get_db)]


@router.get("/rules")
def get_opengrep_rules(state: Annotated[Rules, Depends(get_rules)]) -> GetRules:
    """Return the reviewed OpenGrep corpus without exposing YARA rules."""
    return GetRules(hash=state.rules_commit, rules=state.opengrep_rules)


def dead_letter_expired_shadow_scans(
    session: Session,
    *,
    retry_before: dt.datetime,
    now: dt.datetime,
) -> None:
    """Fail expired shadow leases after the configured attempt budget."""
    reason = f"Worker lease expired after {mainframe_settings.max_job_attempts} scan attempts"
    session.execute(
        update(OpenGrepScan)
        .where(
            OpenGrepScan.alerted_at.is_not(None),
            OpenGrepScan.status == Status.PENDING,
            OpenGrepScan.pending_at < retry_before,
            OpenGrepScan.attempt_count >= mainframe_settings.max_job_attempts,
        )
        .values(
            status=Status.FAILED,
            fail_reason=reason,
            dead_lettered_at=now,
            finished_at=now,
        )
    )


@router.post("/alerts")
def queue_opengrep_alert(
    package: OpenGrepAlert,
    session: Database,
    auth: Authenticated,
) -> QueuePackageResponse:
    """Create idempotent shadow work only for a package selected for alerting."""
    with session.begin():
        scan = session.scalar(
            select(Scan).where(Scan.name == package.name, Scan.version == package.version).with_for_update()
        )
        if scan is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        if scan.status != Status.FINISHED:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "OpenGrep shadow work requires a finished canonical scan.",
            )

        shadow = session.get(OpenGrepScan, scan.scan_id)
        if shadow is None:
            now = dt.datetime.now(dt.UTC)
            shadow = OpenGrepScan(
                scan_id=scan.scan_id,
                alerted_at=now,
                queued_at=now,
                queued_by=auth.subject,
                discord_alert_message_id=package.discord_alert_message_id,
            )
            session.add(shadow)
        elif shadow.alerted_at is None:
            now = dt.datetime.now(dt.UTC)
            shadow.status = Status.QUEUED
            shadow.alerted_at = now
            shadow.queued_at = now
            shadow.queued_by = auth.subject
            shadow.pending_at = None
            shadow.pending_by = None
            shadow.attempt_count = 0
            shadow.assignment_id = None
            shadow.dead_lettered_at = None
            shadow.finished_at = None
            shadow.finished_by = None
            shadow.fail_reason = None
            shadow.commit_hash = None
            shadow.duration_ms = None
            shadow.findings = []
            shadow.publication_id = None
            shadow.publication_claimed_at = None
            shadow.discord_alert_message_id = package.discord_alert_message_id
            shadow.discord_message_id = None
            shadow.discord_thread_id = None
            shadow.published_chunks = 0
            shadow.published_at = None

        elif shadow.discord_alert_message_id is None:
            shadow.discord_alert_message_id = package.discord_alert_message_id
        elif (
            package.discord_alert_message_id is not None
            and shadow.discord_alert_message_id != package.discord_alert_message_id
        ):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "OpenGrep shadow work is already attached to another Discord alert.",
            )

        return QueuePackageResponse(id=str(scan.scan_id))


@router.post("/jobs")
def get_opengrep_jobs(
    session: Database,
    auth: Authenticated,
    state: Annotated[Rules, Depends(get_rules)],
    batch: Annotated[int, Query(ge=1, le=100)] = 1,
) -> list[JobResult]:
    """Lease OpenGrep work without consuming the canonical YARA queue."""
    statement = text("""\
WITH candidates AS (
    SELECT opengrep_scans.scan_id
    FROM opengrep_scans
    WHERE
        opengrep_scans.alerted_at IS NOT NULL
        AND
        opengrep_scans.attempt_count < :max_job_attempts
        AND (
            opengrep_scans.status = 'QUEUED'
            OR (
                opengrep_scans.status = 'PENDING'
                AND opengrep_scans.pending_at < :retry_before
            )
        )
    ORDER BY opengrep_scans.pending_at NULLS FIRST, opengrep_scans.queued_at
    LIMIT :batch
    FOR UPDATE OF opengrep_scans SKIP LOCKED
), updated AS (
    UPDATE opengrep_scans
    SET
        status = 'PENDING',
        pending_at = :pending_at,
        pending_by = :pending_by,
        attempt_count = opengrep_scans.attempt_count + 1,
        assignment_id = gen_random_uuid()
    FROM candidates
    WHERE opengrep_scans.scan_id = candidates.scan_id
    RETURNING opengrep_scans.*
)
SELECT
    updated.scan_id,
    updated.attempt_count,
    updated.assignment_id,
    scans.name,
    scans.version,
    download_urls.url
FROM updated
JOIN scans ON scans.scan_id = updated.scan_id
LEFT JOIN download_urls ON download_urls.scan_id = updated.scan_id
ORDER BY updated.queued_at, download_urls.id
""")
    now = dt.datetime.now(dt.UTC)
    retry_before = now - dt.timedelta(seconds=mainframe_settings.job_timeout)
    with session.begin():
        dead_letter_expired_shadow_scans(
            session,
            retry_before=retry_before,
            now=now,
        )
        rows = session.execute(
            statement,
            {
                "batch": batch,
                "max_job_attempts": mainframe_settings.max_job_attempts,
                "pending_at": now,
                "pending_by": auth.subject,
                "retry_before": retry_before,
            },
        ).mappings()
        jobs: dict[uuid.UUID, JobResult] = {}
        for row in rows:
            scan_id = row["scan_id"]
            if scan_id not in jobs:
                jobs[scan_id] = JobResult(
                    name=row["name"],
                    version=row["version"],
                    distributions=[],
                    hash=state.rules_commit,
                    attempt=row["attempt_count"],
                    assignment_id=row["assignment_id"],
                )
            if row["url"] is not None:
                jobs[scan_id].distributions.append(row["url"])
    return list(jobs.values())


@router.put("/package")
def submit_opengrep_result(
    result: OpenGrepScanResult | OpenGrepScanResultFail,
    session: Database,
    auth: Authenticated,
) -> None:
    """Store a leased shadow result without changing the canonical scan."""
    now = dt.datetime.now(dt.UTC)
    with session.begin():
        row = session.execute(
            select(OpenGrepScan, Scan)
            .join(Scan, Scan.scan_id == OpenGrepScan.scan_id)
            .where(Scan.name == result.name, Scan.version == result.version)
            .with_for_update(of=OpenGrepScan)
        ).one_or_none()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        shadow, _scan = row
        valid_lease = (
            shadow.status == Status.PENDING
            and shadow.pending_by == auth.subject
            and shadow.attempt_count == result.attempt
            and shadow.assignment_id == result.assignment_id
        )
        if not valid_lease:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "OpenGrep scan is no longer assigned to this worker lease.",
            )

        shadow.duration_ms = result.duration_ms
        shadow.finished_at = now
        shadow.finished_by = auth.subject
        if isinstance(result, OpenGrepScanResultFail):
            shadow.status = Status.FAILED
            shadow.fail_reason = result.reason
            shadow.findings = []
            return

        shadow.status = Status.FINISHED
        shadow.commit_hash = result.commit
        shadow.findings = [finding.model_dump(mode="json") for finding in result.findings]


@router.get("/results")
def get_unpublished_opengrep_results(
    session: Database,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[OpenGrepResult]:
    """Atomically lease completed shadow results to one publisher."""
    now = dt.datetime.now(dt.UTC)
    claim_before = now - dt.timedelta(seconds=mainframe_settings.opengrep_publication_timeout)
    with session.begin():
        rows = session.execute(
            select(OpenGrepScan, Scan)
            .join(Scan, Scan.scan_id == OpenGrepScan.scan_id)
            .where(
                OpenGrepScan.alerted_at.is_not(None),
                OpenGrepScan.status.in_((Status.FINISHED, Status.FAILED)),
                OpenGrepScan.published_at.is_(None),
                or_(
                    OpenGrepScan.publication_id.is_(None),
                    OpenGrepScan.publication_claimed_at.is_(None),
                    OpenGrepScan.publication_claimed_at < claim_before,
                ),
            )
            .order_by(OpenGrepScan.finished_at)
            .limit(limit)
            .with_for_update(of=OpenGrepScan, skip_locked=True)
        ).all()
        for shadow, _scan in rows:
            shadow.publication_id = uuid.uuid4()
            shadow.publication_claimed_at = now

    results: list[OpenGrepResult] = []
    for shadow, scan in rows:
        if shadow.finished_at is None:
            msg = "Terminal OpenGrep scan is missing finished_at"
            raise RuntimeError(msg)
        results.append(
            OpenGrepResult(
                scan_id=shadow.scan_id,
                name=scan.name,
                version=scan.version,
                status=shadow.status.name.lower(),
                commit=shadow.commit_hash,
                duration_ms=shadow.duration_ms,
                findings=shadow.findings,
                fail_reason=shadow.fail_reason,
                finished_at=shadow.finished_at,
                publication_id=cast("uuid.UUID", shadow.publication_id),
                discord_alert_message_id=shadow.discord_alert_message_id,
                discord_message_id=shadow.discord_message_id,
                discord_thread_id=shadow.discord_thread_id,
                published_chunks=shadow.published_chunks,
            )
        )
    return results


def require_publication_claim(
    shadow: OpenGrepScan | None,
    publication_id: uuid.UUID,
) -> OpenGrepScan:
    """Return a matching terminal publication lease or raise a safe conflict."""
    if shadow is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if shadow.status not in (Status.FINISHED, Status.FAILED):
        raise HTTPException(status.HTTP_409_CONFLICT, "OpenGrep scan is not complete.")
    if shadow.publication_id != publication_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "OpenGrep publication lease is stale.")
    return shadow


@router.post("/results/{scan_id}/publication")
def checkpoint_opengrep_publication(
    scan_id: uuid.UUID,
    progress: OpenGrepPublicationProgress,
    session: Database,
) -> None:
    """Persist monotonic Discord thread progress for retry-safe resumption."""
    with session.begin():
        shadow = require_publication_claim(
            session.scalar(select(OpenGrepScan).where(OpenGrepScan.scan_id == scan_id).with_for_update()),
            progress.publication_id,
        )
        if shadow.published_at is not None:
            return
        if shadow.discord_message_id is not None and progress.discord_message_id not in (
            None,
            shadow.discord_message_id,
        ):
            raise HTTPException(status.HTTP_409_CONFLICT, "discord_message_id cannot change after it is recorded.")
        replacing_thread = (
            shadow.discord_thread_id is not None
            and progress.discord_thread_id is not None
            and shadow.discord_thread_id != progress.discord_thread_id
        )
        if replacing_thread and progress.published_chunks != 0:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "A replacement Discord thread must restart publication progress.",
            )
        if not replacing_thread and progress.published_chunks < shadow.published_chunks:
            raise HTTPException(status.HTTP_409_CONFLICT, "OpenGrep publication progress cannot move backwards.")
        if progress.discord_message_id is not None:
            shadow.discord_message_id = progress.discord_message_id
        if progress.discord_thread_id is not None:
            shadow.discord_thread_id = progress.discord_thread_id
        shadow.published_chunks = progress.published_chunks
        shadow.publication_claimed_at = dt.datetime.now(dt.UTC)


@router.post("/results/{scan_id}/heartbeat")
def heartbeat_opengrep_publication(
    scan_id: uuid.UUID,
    claim: OpenGrepPublicationClaim,
    session: Database,
) -> None:
    """Renew an active publication lease without changing its progress."""
    with session.begin():
        shadow = require_publication_claim(
            session.scalar(select(OpenGrepScan).where(OpenGrepScan.scan_id == scan_id).with_for_update()),
            claim.publication_id,
        )
        if shadow.published_at is None:
            shadow.publication_claimed_at = dt.datetime.now(dt.UTC)


@router.post("/results/{scan_id}/published")
def acknowledge_opengrep_result(
    scan_id: uuid.UUID,
    claim: OpenGrepPublicationClaim,
    session: Database,
) -> OpenGrepPublished:
    """Acknowledge publication only after the complete Discord thread exists."""
    published_at = dt.datetime.now(dt.UTC)
    with session.begin():
        shadow = require_publication_claim(
            session.scalar(select(OpenGrepScan).where(OpenGrepScan.scan_id == scan_id).with_for_update()),
            claim.publication_id,
        )
        if shadow.published_at is None:
            shadow.published_at = published_at
        else:
            published_at = shadow.published_at
    return OpenGrepPublished(published_at=published_at)
