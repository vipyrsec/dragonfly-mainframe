import datetime as dt
from threading import Lock

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from mainframe.metrics import (
    packages_above_production_threshold,
    packages_reported_snapshot,
    packages_scan_outcomes,
    packages_scanned,
    performance_snapshot_timestamp_seconds,
    production_score_threshold,
    rule_hits,
)
from mainframe.models.orm import (
    AlertingConfiguration,
    Rule,
    Scan,
    Status,
    package_rules,
)
from mainframe.models.schemas import PerformanceStatus


def read_performance_status(
    session: Session,
    *,
    now: dt.datetime,
    cached_rule_hits: dict[str, int] | None = None,
) -> PerformanceStatus:
    """Read durable package and per-rule performance totals."""
    threshold = session.scalar(
        select(AlertingConfiguration.production_score_threshold).where(AlertingConfiguration.id == 1)
    )
    if threshold is None:
        msg = "Alerting configuration is missing"
        raise RuntimeError(msg)

    totals = session.execute(
        select(
            func.count().filter(Scan.status == Status.FINISHED),
            func.count().filter((Scan.status == Status.FAILED) & Scan.dead_lettered_at.is_(None)),
            func.count().filter((Scan.status == Status.FAILED) & Scan.dead_lettered_at.is_not(None)),
            func.count().filter((Scan.status == Status.FINISHED) & (Scan.score >= threshold)),
            func.count().filter(Scan.reported_at.is_not(None)),
        ).select_from(Scan)
    ).one()
    if cached_rule_hits is None:
        rule_rows = session.execute(
            select(
                Rule.name,
                func.count(package_rules.c.scan_id).filter(Scan.status == Status.FINISHED),
            )
            .select_from(Rule)
            .outerjoin(package_rules, Rule.id == package_rules.c.rule_id)
            .outerjoin(Scan, Scan.scan_id == package_rules.c.scan_id)
            .group_by(Rule.id, Rule.name)
            .order_by(Rule.name)
        )
        rule_hits_snapshot = {name: int(hit_count) for name, hit_count in rule_rows}
    else:
        rule_hits_snapshot = cached_rule_hits

    return PerformanceStatus(
        packages_scanned=int(totals[0]),
        packages_failed=int(totals[1]),
        packages_dead_lettered=int(totals[2]),
        packages_above_production_threshold=int(totals[3]),
        packages_reported=int(totals[4]),
        production_score_threshold=threshold,
        rule_hits=rule_hits_snapshot,
        sampled_at=now,
    )


class PerformanceMonitor:
    """Periodically publish durable performance totals to Prometheus."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._snapshot: PerformanceStatus | None = None
        self._published_rules: set[str] = set()
        self._lock = Lock()

    def refresh(
        self,
        *,
        now: dt.datetime | None = None,
        refresh_rule_hits: bool = True,
    ) -> PerformanceStatus:
        sampled_at = now or dt.datetime.now(dt.UTC)
        cached_rule_hits = None
        if not refresh_rule_hits and self._snapshot is not None:
            cached_rule_hits = self._snapshot.rule_hits
        with Session(bind=self.engine) as session, session.begin():
            snapshot = read_performance_status(
                session,
                now=sampled_at,
                cached_rule_hits=cached_rule_hits,
            )

        packages_scanned.set(snapshot.packages_scanned)
        packages_scan_outcomes.labels(outcome="finished").set(snapshot.packages_scanned)
        packages_scan_outcomes.labels(outcome="failed").set(snapshot.packages_failed)
        packages_scan_outcomes.labels(outcome="dead_lettered").set(snapshot.packages_dead_lettered)
        packages_above_production_threshold.set(snapshot.packages_above_production_threshold)
        packages_reported_snapshot.set(snapshot.packages_reported)
        production_score_threshold.set(snapshot.production_score_threshold)
        performance_snapshot_timestamp_seconds.set(snapshot.sampled_at.timestamp())

        current_rules = set(snapshot.rule_hits)
        with self._lock:
            removed_rules = self._published_rules - current_rules
            self._published_rules = current_rules
            self._snapshot = snapshot
        for rule_name in removed_rules:
            rule_hits.remove(rule_name)
        for rule_name, hit_count in snapshot.rule_hits.items():
            rule_hits.labels(rule=rule_name).set(hit_count)

        return snapshot

    def get_snapshot(self) -> PerformanceStatus | None:
        """Return the latest database-derived performance snapshot."""
        with self._lock:
            return self._snapshot
