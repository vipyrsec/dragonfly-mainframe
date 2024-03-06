import queue
from datetime import datetime, timedelta, timezone
from queue import Queue
from typing import Optional

import structlog
from sqlalchemy import and_, or_, select, tuple_
from sqlalchemy.orm import Session, selectinload

from mainframe.constants import mainframe_settings
from mainframe.models.orm import Rule, Scan, Status
from mainframe.models.schemas import PackageScanResult, PackageScanResultFail

logger: structlog.stdlib.BoundLogger = structlog.get_logger()


class JobCache:
    """Handles caching of jobs and results"""

    def __init__(self, session: Session, size: int = 1) -> None:
        self.scan_queue: Queue[Scan] = Queue(maxsize=size)
        self.pending: list[Scan] = []
        self.results_queue: Queue[PackageScanResult | PackageScanResultFail] = Queue(maxsize=size)
        self.enabled = size > 1

        self.session = session

    def requeue_timeouts(self) -> list[Scan]:
        """Send all timed out pending packages back to the queue. Return a list of `Scan`s that were requeued."""
        scans: list[Scan] = []
        TIMEOUT_LIMIT = timedelta(minutes=mainframe_settings.job_timeout)
        for pending_scan in self.pending:
            # this should never happen, but the type checker must be appeased
            if pending_scan.pending_at is None:
                continue

            pending_for = datetime.now(timezone.utc) - pending_scan.pending_at

            if pending_for > TIMEOUT_LIMIT:
                self.pending.remove(pending_scan)
                self.scan_queue.put_nowait(pending_scan)
                scans.append(pending_scan)
                logger.warn(
                    "Timed out package found. Requeueing.", name=pending_scan.name, version=pending_scan.version
                )

        return scans

    def refill(self) -> None:
        # refill from timed out pending scans first
        print("qsize 2", self.scan_queue.qsize())
        logger.info("Refilling from timed out pending scans")
        requeued_scans = self.requeue_timeouts()
        logger.info(f"Moved {len(requeued_scans)} timed out scans from pending to queue")
        print("qsize 3", self.scan_queue.qsize())

        # exclude packages that we just put back into the queue
        # and packages that are currently pending from our database query
        requeued_scans_name_version = [(s.name, s.version) for s in requeued_scans]
        pending_name_version = [(s.name, s.version) for s in self.pending]
        scans_to_exclude = requeued_scans_name_version + pending_name_version

        query = (
            select(Scan)
            .where(Scan.status == Status.QUEUED)
            .where(tuple_(Scan.name, Scan.version).not_in(scans_to_exclude))
            .order_by(Scan.queued_at)
            .limit(self.scan_queue.maxsize)
            .options(selectinload(Scan.rules), selectinload(Scan.download_urls))
        )

        scans = self.session.scalars(query).all()

        logger.info(f"Fetched {len(scans)} scans from DB to refill queue with.")

        for scan in scans:
            try:
                print("qsize 4", self.scan_queue.qsize())
                self.scan_queue.put(scan, timeout=5)
                logger.info("Put scan into queue.", name=scan.name, version=scan.version)
            except queue.Full:
                # this scenario can happen if some jobs from the timeout have already
                # been added into the queue. In this case we just ignore the remaining
                # jobs from the DB since we're already full
                logger.warn("Overfetched. Ignoring extras.")
                break

        logger.info("Refilled jobs queue")

    def persist_all_results(self) -> None:
        """Pop off all results and persist them in the database"""
        results: list[PackageScanResult | PackageScanResultFail] = []
        while not self.results_queue.empty():
            result = self.results_queue.get(timeout=5)
            results.append(result)

        name_versions = [(result.name, result.version) for result in results]
        query = select(Scan).where(tuple_(Scan.name, Scan.version).in_(name_versions))
        scans = self.session.scalars(query).all()

        all_rules = self.session.scalars(select(Rule)).all()

        for result in results:
            scan = next((scan for scan in scans if (scan.name, scan.version) == (result.name, result.version)), None)
            if scan is None:
                logger.warn("Results submitted for a package that doesn't exist, skipping", **result.model_dump())
                continue

            if scan.status == Status.FINISHED:
                logger.warn("Package is already in a FINISHED state, skipping", **result.model_dump())

            if isinstance(result, PackageScanResultFail):
                scan.status = Status.FAILED
                scan.fail_reason = result.reason
                logger.error("Package failed to scan", reason=result.reason)

            if isinstance(result, PackageScanResult):
                scan.status = Status.FINISHED
                scan.finished_at = datetime.now(timezone.utc)
                scan.inspector_url = result.inspector_url
                scan.score = result.score
                scan.commit_hash = result.commit

                # These are the rules that already have an entry in the database
                old_rules = [rule for rule in all_rules if rule.name in result.rules_matched]

                # These are the rules that had to be created
                all_rule_names = {rule.name for rule in all_rules}
                new_rules = [Rule(name=name) for name in result.rules_matched if name not in all_rule_names]

                scan.rules.extend(old_rules + new_rules)

                self.session.add(scan)

                logger.info(
                    "Scan results submitted",
                    package={
                        "name": scan.name,
                        "version": scan.version,
                        "status": scan.status,
                        "finished_at": scan.finished_at,
                        "inspector_url": result.inspector_url,
                        "score": result.score,
                        "existing_rules": old_rules,
                        "created_rules": [rule.name for rule in new_rules],
                    },
                    tag="scan_submitted",
                )

        self.session.commit()
        for scan in self.session.scalars(select(Scan)):
            print(scan.name, scan.version, scan.status)

    def fetch_job(self) -> Optional[Scan]:
        """Directly fetch a job from the database. Used only when cache is disabled."""
        print("fetching job, bypassing cache")
        query = (
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
            .options(selectinload(Scan.download_urls))
            .with_for_update()
        )

        scan = self.session.scalar(query)
        if scan is None:
            return None

        scan.status = Status.PENDING
        scan.pending_at = datetime.now(timezone.utc)

        self.session.commit()

        return scan

    def get_job(self) -> Optional[Scan]:
        """Get one job. Refills the cache if necessary."""

        if not self.enabled:
            return self.fetch_job()

        try:
            scan = self.scan_queue.get_nowait()
        except queue.Empty:
            self.refill()

            # If it's still empty after a refill, there aren't any more jobs in the DB.
            try:
                scan = self.scan_queue.get_nowait()
            except queue.Empty:
                return None

        scan.status = Status.PENDING
        scan.pending_at = datetime.now(timezone.utc)
        self.pending.append(scan)

        return scan

    def submit_result(self, result: PackageScanResult | PackageScanResultFail) -> None:
        logger.info("Incoming result", result=result)

        if not self.enabled:
            self.results_queue.put(result, timeout=5)
            self.persist_all_results()
            logger.info("Caching disabled. Wrote results directly to DB.")
            return

        if scan := next((s for s in self.pending if (s.name, s.version) == (result.name, result.version)), None):
            self.pending.remove(scan)
            logger.info("Removed scan from pending list", name=scan.name, version=scan.version)
        else:
            logger.warn("Scan not found in pending list", name=result.name, version=result.version)

        try:
            self.results_queue.put_nowait(result)
        except queue.Full:
            self.persist_all_results()
            logger.info("Results queue full, drained and wrote to DB")
        finally:
            self.results_queue.put_nowait(result)
            logger.info("Put result in results queue", result=result)
