import datetime as dt
import uuid
from collections import Counter
from dataclasses import dataclass

from sqlalchemy import Engine, exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, selectinload

from mainframe.models.orm import (
    PerformanceProjectionState,
    PerformanceRollup,
    RuleHitRollup,
    Scan,
    ScoreRollup,
    Status,
)


@dataclass(frozen=True)
class ProjectionBatch:
    """Result of one bounded projection transaction."""

    outcomes: int
    reports: int
    initial_backfill_complete: bool

    @property
    def processed(self) -> int:
        return self.outcomes + self.reports


def _increment_rule_hits(
    session: Session,
    rule_counts: Counter[uuid.UUID],
) -> None:
    if not rule_counts:
        return
    statement = insert(RuleHitRollup).values(
        [{"rule_id": rule_id, "hits": hits} for rule_id, hits in rule_counts.items()]
    )
    session.execute(
        statement.on_conflict_do_update(
            index_elements=[RuleHitRollup.rule_id],
            set_={"hits": RuleHitRollup.hits + statement.excluded.hits},
        )
    )


def _increment_score_totals(
    session: Session,
    score_counts: Counter[int],
) -> None:
    if not score_counts:
        return
    statement = insert(ScoreRollup).values([{"score": score, "scans": scans} for score, scans in score_counts.items()])
    session.execute(
        statement.on_conflict_do_update(
            index_elements=[ScoreRollup.score],
            set_={"scans": ScoreRollup.scans + statement.excluded.scans},
        )
    )


class PerformanceProjector:
    """Project authoritative scans into compact analytics in bounded batches."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def process_batch(
        self,
        *,
        batch_size: int,
        now: dt.datetime | None = None,
    ) -> ProjectionBatch:
        processed_at = now or dt.datetime.now(dt.UTC)
        with Session(bind=self.engine) as session, session.begin():
            session.execute(
                insert(PerformanceRollup).values(id=1).on_conflict_do_nothing(index_elements=[PerformanceRollup.id])
            )
            rollup = session.get(PerformanceRollup, 1, with_for_update=True)
            if rollup is None:
                msg = "Performance rollup could not be initialized"
                raise RuntimeError(msg)

            session.execute(
                insert(PerformanceProjectionState)
                .values(id=1)
                .on_conflict_do_nothing(index_elements=[PerformanceProjectionState.id])
            )
            state = session.get(PerformanceProjectionState, 1, with_for_update=True)
            if state is None:
                msg = "Performance projection state could not be initialized"
                raise RuntimeError(msg)

            outcomes = (
                session.scalars(
                    select(Scan)
                    .where(
                        Scan.analytics_outcome_processed_at.is_(None),
                        Scan.status.in_((Status.FINISHED, Status.FAILED)),
                    )
                    .order_by(Scan.scan_id)
                    .limit(batch_size)
                    .with_for_update(skip_locked=True)
                    .options(selectinload(Scan.rules))
                )
                .unique()
                .all()
            )

            rule_counts: Counter[uuid.UUID] = Counter()
            score_counts: Counter[int] = Counter()
            for scan in outcomes:
                if scan.status == Status.FINISHED:
                    if scan.score is None:
                        msg = f"Finished scan {scan.scan_id} has no score"
                        raise RuntimeError(msg)
                    rollup.packages_scanned += 1
                    score_counts[scan.score] += 1
                    rule_counts.update(rule.id for rule in scan.rules)
                elif scan.dead_lettered_at is None:
                    rollup.packages_failed += 1
                else:
                    rollup.packages_dead_lettered += 1
                scan.analytics_outcome_processed_at = processed_at

            _increment_rule_hits(session, rule_counts)
            _increment_score_totals(session, score_counts)

            reports = session.scalars(
                select(Scan)
                .where(
                    Scan.analytics_report_processed_at.is_(None),
                    Scan.reported_at.is_not(None),
                )
                .order_by(Scan.scan_id)
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            ).all()
            for scan in reports:
                rollup.packages_reported += 1
                scan.analytics_report_processed_at = processed_at

            if outcomes or reports:
                state.last_processed_at = processed_at

            outcome_pending = session.scalar(
                select(
                    exists().where(
                        Scan.analytics_outcome_processed_at.is_(None),
                        Scan.status.in_((Status.FINISHED, Status.FAILED)),
                    )
                )
            )
            report_pending = session.scalar(
                select(
                    exists().where(
                        Scan.analytics_report_processed_at.is_(None),
                        Scan.reported_at.is_not(None),
                    )
                )
            )
            if not outcome_pending and not report_pending and state.initial_backfill_completed_at is None:
                state.initial_backfill_completed_at = processed_at

            return ProjectionBatch(
                outcomes=len(outcomes),
                reports=len(reports),
                initial_backfill_complete=state.initial_backfill_completed_at is not None,
            )
