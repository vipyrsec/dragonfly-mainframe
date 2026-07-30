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
    PerformanceProjectionState,
    PerformanceRollup,
    Rule,
    RuleHitRollup,
    ScoreRollup,
)
from mainframe.models.schemas import PerformanceStatus


class PerformanceProjectionIncompleteError(RuntimeError):
    """Raised while historical analytics are still being projected."""


def read_performance_status(
    session: Session,
    *,
    now: dt.datetime,
) -> PerformanceStatus:
    """Read compact analytics without scanning operational history."""
    threshold = session.scalar(
        select(AlertingConfiguration.production_score_threshold).where(AlertingConfiguration.id == 1)
    )
    if threshold is None:
        msg = "Alerting configuration is missing"
        raise RuntimeError(msg)

    state = session.get(PerformanceProjectionState, 1)
    if state is None or state.initial_backfill_completed_at is None:
        msg = "Initial performance projection is incomplete"
        raise PerformanceProjectionIncompleteError(msg)

    totals = session.get(PerformanceRollup, 1)
    if totals is None:
        msg = "Performance rollup is missing"
        raise RuntimeError(msg)

    above_threshold = session.scalar(
        select(func.coalesce(func.sum(ScoreRollup.scans), 0)).where(ScoreRollup.score >= threshold)
    )
    rule_rows = session.execute(
        select(
            Rule.name,
            func.coalesce(RuleHitRollup.hits, 0),
        )
        .select_from(Rule)
        .outerjoin(RuleHitRollup, Rule.id == RuleHitRollup.rule_id)
        .order_by(Rule.name)
    )

    return PerformanceStatus(
        packages_scanned=totals.packages_scanned,
        packages_failed=totals.packages_failed,
        packages_dead_lettered=totals.packages_dead_lettered,
        packages_above_production_threshold=int(above_threshold or 0),
        packages_reported=totals.packages_reported,
        production_score_threshold=threshold,
        rule_hits={name: int(hit_count) for name, hit_count in rule_rows},
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
    ) -> PerformanceStatus:
        sampled_at = now or dt.datetime.now(dt.UTC)
        with Session(bind=self.engine) as session, session.begin():
            snapshot = read_performance_status(
                session,
                now=sampled_at,
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
