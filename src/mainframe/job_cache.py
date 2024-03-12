import queue
import threading
from datetime import datetime, timedelta, timezone
from queue import Queue
from typing import Optional

import structlog
from sqlalchemy import and_, or_, select, tuple_
from sqlalchemy.orm import Session, selectinload, sessionmaker

from mainframe.constants import mainframe_settings
from mainframe.models.orm import Rule, Scan, Status
from mainframe.models.schemas import PackageScanResult, PackageScanResultFail

logger: structlog.stdlib.BoundLogger = structlog.get_logger()


class JobCache:
    """Handles caching of jobs and results"""

    def __init__(self, sessionmaker: sessionmaker[Session], size: int = 1) -> None:
        self.scan_queue: Queue[Scan] = Queue(maxsize=size)
        self.pending: list[Scan] = []
        self.results_queue: Queue[PackageScanResult | PackageScanResultFail] = Queue(maxsize=size)

        self._refill_lock = threading.Lock()
        self._presisting_lock = threading.Lock()
        self.enabled = size > 1

        self.sessionmaker = sessionmaker

    def requeue_timeouts(self) -> list[Scan]:
        """Send all timed out pending packages back to the queue. Return a list of `Scan`s that were requeued."""
        timeout_limit = timedelta(seconds=mainframe_settings.job_timeout)
        timedout_scans: list[Scan] = []
        pending_scans: list[Scan] = []
        for pending_scan in self.pending:
            # this should never happen, but the type checker must be appeased
            assert pending_scan.pending_at is not None

            pending_for = datetime.now(timezone.utc) - pending_scan.pending_at

            if pending_for > timeout_limit:
                pending_scan.status = Status.QUEUED
                pending_scan.pending_at = None
                self.scan_queue.put(pending_scan)
                timedout_scans.append(pending_scan)
                logger.debug(
                    "Timed out package found. Requeueing.", name=pending_scan.name, version=pending_scan.version
                )
            else:
                pending_scans.append(pending_scan)

        self.pending = pending_scans
        return timedout_scans

    def refill(self) -> None:
        # refill from timed out pending scans first
        logger.debug("Refilling from timed out pending scans")
        requeued_scans = self.requeue_timeouts()
        logger.debug(f"Moved {len(requeued_scans)} timed out scans from pending to queue")

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

        with self.sessionmaker() as session:
            scans = session.scalars(query).all()

        logger.info(f"Fetched {len(scans)} scans from DB to refill queue with.")

        for scan in scans:
            try:
                self.scan_queue.put_nowait(scan)
                logger.debug("Put scan into queue.", name=scan.name, version=scan.version)
            except queue.Full:
                # this scenario can happen if some jobs from the timeout have already
                # been added into the queue. In this case we just ignore the remaining
                # jobs from the DB since we're already full
                logger.debug("Overfetched. Ignoring extras.")
                break

        logger.debug("Refilled jobs queue")

    def persist_all_results(self) -> None:
        """Pop off all results and persist them in the database"""
        results: list[PackageScanResult | PackageScanResultFail] = []
        while not self.results_queue.empty():
            result = self.results_queue.get(timeout=5)
            results.append(result)

        name_versions = [(result.name, result.version) for result in results]
        query = select(Scan).where(tuple_(Scan.name, Scan.version).in_(name_versions))
        session = self.sessionmaker()
        scans = session.scalars(query).all()
        all_rules = session.scalars(select(Rule)).all()

        for result in results:
            scan = next((scan for scan in scans if (scan.name, scan.version) == (result.name, result.version)), None)
            if scan is None:
                logger.warn("Results submitted for a package that doesn't exist, skipping", **result.model_dump())
                continue

            if scan.status == Status.FINISHED:
                logger.warn("Package is already in a FINISHED state, skipping", **result.model_dump())
                continue

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

                session.add(scan)

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

        session.commit()

    def fetch_job(self) -> Optional[Scan]:
        """Directly fetch a job from the database. Used only when cache is disabled."""
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

        session = self.sessionmaker()
        scan = session.scalar(query)
        if scan is None:
            return None

        scan.status = Status.PENDING
        scan.pending_at = datetime.now(timezone.utc)

        session.commit()

        return scan

    def get_job(self) -> Optional[Scan]:
        """Get one job. Refills the cache if necessary."""

        if not self.enabled:
            return self.fetch_job()

        with self._refill_lock:
            if self.scan_queue.empty():
                self.refill()

            # If it's still empty after a refill, there aren't any more jobs in the DB.
            if self.scan_queue.empty():
                return None
            else:
                scan = self.scan_queue.get()

        scan.status = Status.PENDING
        scan.pending_at = datetime.now(timezone.utc)
        self.pending.append(scan)

        return scan

    def submit_result(self, result: PackageScanResult | PackageScanResultFail) -> None:
        logger.info("Incoming result", result=result)

        if not self.enabled:
            with self._presisting_lock:
                self.results_queue.put(result)
                self.persist_all_results()
            logger.debug("Caching disabled. Wrote results directly to DB.")
            return

        if scan := next((s for s in self.pending if (s.name, s.version) == (result.name, result.version)), None):
            self.pending.remove(scan)
            logger.info("Removed scan from pending list", name=scan.name, version=scan.version)
        else:
            logger.warn("Scan not found in pending list", name=result.name, version=result.version)

        with self._presisting_lock:
            if self.results_queue.full():
                self.persist_all_results()
                logger.info("Results queue full, drained and wrote to DB")

            self.results_queue.put(result)
            logger.info("Put result in results queue", result=result)
